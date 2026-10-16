"""Scrape the week's student-relevant Adressa articles into the local cache the backend reads.

    uv run --group scraper python -m app.scraper [--limit 8] [--days 7] [--refresh]

1. Reads Adressa's RSS feed and sorts the items on publication time, not on RSS order.
2. Picks the up to 8 news stories from the last week that matter most to students (adressa.py).
3. Opens each one in a hidden Chrome with the user's own saved Adressa login (browser.py) and keeps
   only text the logged-in page shows. A story the page doesn't show in full is skipped.
4. Saves the main photo after checking that it really is an image.
5. Replaces ADRESSA_CACHE_DIR/articles.json in one atomic step, which app.stories reads.

While ADRESSA_CACHE_DIR/PAUSED exists nothing is fetched or written, so the app keeps showing the
last import. A failed run keeps the previous cache too, a lock file stops two runs at once, and
every run records its outcome in import-status.json.

The cache holds article text and photos from the subscription, so it is git-ignored and never
published. The public facts reach the hosted app through data/week.json (app.export_week, which
app.generate_questions runs).
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import floor
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.config import settings
from app.scraper.adressa import (
    IMAGE_EXTENSIONS,
    IMAGE_HOST,
    MAX_FEED_BYTES,
    MAX_IMAGE_BYTES,
    RSS_URL,
    ScraperError,
    article_key,
    category_for,
    image_type,
    iso,
    merge_articles,
    parse_rss,
    parse_time,
    safe_link,
    section_of,
    select_candidates,
    split_caption,
    stable_id,
    to_iso,
    write_file_atomic,
)
from app.stories import IMAGE_FILE, SOURCE, cache_dir

REPO = Path(__file__).resolve().parents[3]
MAX_ARTICLES = 12
FEED_WIDTH = 2000  # a phone shows the photo full screen, so the page's 1000 px copy is too soft
USER_AGENT = "Opplyst/0.1 (personal local RSS reader)"

LOGIN_HELP = """Logg inn på nytt i scraperens Adressa-profil, fra rotmappen i repoet:
  make adressa-login
Lukk innloggingsvinduet når du er ferdig, og kjør importen igjen."""


class Browser(Protocol):
    def read(self, url: str) -> tuple[dict, dict | None]: ...

    def close(self) -> None: ...


def check_profile(profile: Path) -> None:
    """The browser profile holds the saved login, so it may never be in the repo, which is public."""
    if profile.resolve().is_relative_to(REPO):
        raise ScraperError(
            "PROFILE_INSIDE_REPO",
            "Innloggingsprofilen kan ikke ligge i repoet. Flytt den ut og pek "
            "ADRESSA_PROFILE_DIR i backend/.env dit.",
        )


def read_rss(rss_file: Path | None = None) -> str:
    if rss_file:
        try:
            return rss_file.read_text(encoding="utf-8")
        except OSError:
            raise ScraperError(
                "RSS_UNAVAILABLE", "Fant ikke RSS-filen som ble oppgitt med --rss-file."
            ) from None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"}
    try:
        with httpx.stream("GET", RSS_URL, headers=headers, timeout=15) as response:
            if not response.is_success:
                raise ValueError("feed")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_FEED_BYTES:
                    raise ValueError("size")
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")
    except (httpx.HTTPError, ValueError):
        raise ScraperError(
            "RSS_UNAVAILABLE",
            "Kunne ikke hente Adressas RSS-feed. Kontroller nettet og prøv igjen.",
        ) from None


def _number(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def feed_sized_image_url(url: str) -> str:
    """The CDN renders each size on request, so ask for FEED_WIDTH instead of the page's own size
    (1000 px, far too soft on a full-screen phone card). It never goes beyond the original. Very large
    originals (3200 px) can take long enough to time out the first time, hence no more than this."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    width, height = _number(dict(query).get("w")), _number(dict(query).get("h"))
    if not width or width == FEED_WIDTH:
        return url
    sizes = {"w": str(FEED_WIDTH)}
    if height:
        sizes["h"] = str(floor(height * FEED_WIDTH / width + 0.5))
    return urlunsplit(parts._replace(query=urlencode([(k, sizes.get(k, v)) for k, v in query])))


def _fetch_image(url: str, story_id: str, image_dir: Path) -> dict:
    try:
        with httpx.stream("GET", url, timeout=30) as response:
            declared = response.headers.get("content-type", "").split(";")[0].strip()
            if not response.is_success or declared not in IMAGE_EXTENSIONS:
                return {"error": "IMAGE_NOT_AVAILABLE"}
            if _number(response.headers.get("content-length")) > MAX_IMAGE_BYTES:
                return {"error": "IMAGE_TOO_LARGE"}
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    return {"error": "IMAGE_TOO_LARGE"}
                chunks.append(chunk)
    except httpx.TimeoutException:
        return {"error": "IMAGE_TIMEOUT", "retry": True}
    except httpx.HTTPError:
        return {"error": "IMAGE_DOWNLOAD_FAILED", "retry": True}
    data = b"".join(chunks)
    sniffed = image_type(data)
    # The bytes must really be an image, and the same kind the server said it sent.
    if not sniffed or sniffed != declared or len(data) < 1024:
        return {"error": "IMAGE_INVALID"}
    file = f"{story_id}.{IMAGE_EXTENSIONS[sniffed]}"
    write_file_atomic(image_dir / file, data)
    return {"file": file, "contentType": sniffed, "bytes": len(data)}


def download_image(url: str, story_id: str, image_dir: Path) -> dict:
    """Saves a photo from Adressa's image service as <story id>.<type>. On failure: {"error": code}."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return {"error": "IMAGE_URL_INVALID"}
    if parts.scheme != "https" or parts.hostname != IMAGE_HOST:
        return {"error": "IMAGE_HOST_NOT_ALLOWED"}
    sized = feed_sized_image_url(url)
    result = _fetch_image(sized, story_id, image_dir)
    if result.pop("retry", False):
        result = _fetch_image(sized, story_id, image_dir)
        result.pop("retry", None)
    return result


def share_image_url(url: str | None) -> str | None:
    """Adressa's own share image (og:image), only from its image service."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return None
    return url if parts.scheme == "https" and parts.hostname == IMAGE_HOST else None


def import_one(browser: Browser, candidate: dict, imported_at: str, image_dir: Path) -> dict:
    """{"article": …, "warnings": […]} for a story the page shows in full, else {"skipped": …}."""
    visible, structure = browser.read(candidate["url"])
    if structure is None:
        # partial, restricted and unknown are unconfirmed access, never a successful import.
        access = visible["access"]
        return {
            "skipped": {
                "id": candidate["id"],
                "title": candidate["title"],
                "access": access["state"],
                "gated": bool(re.search("gate", access.get("reason") or "", re.IGNORECASE)),
            }
        }
    url = safe_link(visible.get("url")) or candidate["url"]
    summary = structure.get("summary")
    summary_text = {
        *(summary["bullets"] if summary else []),
        structure.get("lead"),
        "Kort oppsummert",
        "Vis mer",
        "Vis mindre",
    }
    body = structure["blocks"] or [
        {"type": "paragraph", "text": text}
        for text in visible["body"].split("\n\n")
        if text not in summary_text
    ]

    image = None
    warnings = []
    page_image = structure.get("image") or {}
    image_url = page_image.get("url") or candidate.get("rssImage") or structure.get("ogImage")
    if image_url:
        saved = download_image(image_url, candidate["id"], image_dir)
        if "error" in saved:
            warnings.append(saved["error"])
        else:
            caption, credit = split_caption(page_image.get("caption"))
            # Photos are fetched FEED_WIDTH px wide (see feed_sized_image_url); so is the size,
            # unless the original is smaller.
            width, height = page_image.get("width"), page_image.get("height")
            scale = FEED_WIDTH / width if width else 1
            image = {
                "src": f"/api/media/adressa/{saved['file']}",
                "file": saved["file"],
                "alt": page_image.get("alt"),
                "caption": caption,
                "credit": credit,
                "width": floor(width * scale + 0.5) if width else None,
                "height": floor(height * scale + 0.5) if height else None,
                "contentType": saved["contentType"],
                "bytes": saved["bytes"],
            }

    return {
        "warnings": warnings,
        "article": {
            "id": candidate["id"],
            "key": candidate["key"],
            "title": visible.get("title") or candidate["title"],
            "category": category_for(url) or candidate["category"],
            "section": section_of(url),
            "source": SOURCE,
            "url": url,
            "authors": visible.get("authors") or [],
            "publishedAt": to_iso(visible.get("published")) or candidate["publishedAt"],
            "modifiedAt": to_iso(visible.get("modified")),
            # The page's own lead. Pages without one fall back to the RSS description; the page's
            # meta description is not used, since it can be the generic site description.
            "lead": structure.get("lead") or candidate.get("description"),
            # Adressa's own «Kort oppsummert». None when the article has none; we never write one.
            "summary": {
                "heading": summary["heading"],
                "bullets": summary["bullets"],
                "source": SOURCE,
                "sourceUrl": url,
                "disclosure": summary.get("disclosure"),
                "disclosureUrl": safe_link(summary.get("disclosureUrl")),
            }
            if summary
            else None,
            "image": image,
            # Adressa's share image, the public picture for link previews. Unlike the local copy
            # above it may be shown in the published app, linked from Adressa's image service.
            "shareImage": share_image_url(structure.get("ogImage")),
            "body": body,
            "access": "available",
            "relevance": candidate["relevance"],
            "importedAt": imported_at,
        },
    }


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    write_file_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _now() -> str:
    return iso(datetime.now(UTC))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_lock(lock: Path) -> None:
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip())
            except (OSError, ValueError):
                pid = 0
            if pid and _alive(pid):
                raise ScraperError(
                    "LOCKED", "En annen import kjører allerede. Vent til den er ferdig."
                ) from None
            lock.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as file:
            file.write(str(os.getpid()))
        return
    raise ScraperError("LOCKED", f"Fikk ikke låst importen. Slett {lock} hvis ingen import kjører.")


def _remove_unused_images(image_dir: Path, articles: list[dict]) -> None:
    used = {(a.get("image") or {}).get("file") for a in articles}
    for path in image_dir.iterdir():
        if IMAGE_FILE.match(path.name) and path.name not in used:
            path.unlink(missing_ok=True)


def _open_browser(profile: Path) -> Browser:
    from app.scraper.browser import AdressaBrowser

    return AdressaBrowser(profile, channel=settings.adressa_browser)


def scrape(
    folder: Path,
    *,
    profile: Path,
    limit: int = 8,
    days: int = 7,
    refresh: bool = False,
    rss_file: Path | None = None,
    open_browser: Callable[[Path], Browser] | None = None,
) -> bool:
    """One import into `folder`. Prints what happens; False when nothing new was saved."""
    image_dir = folder / "images"
    cache_file = folder / "articles.json"
    status_file = folder / "import-status.json"
    lock = folder / ".import.lock"
    pause = folder / "PAUSED"

    # While paused nothing is fetched or written, so the app keeps showing the current set.
    if pause.exists():
        print(
            f"PAUSED: Importen er satt på pause. Slett {pause.resolve()} for å hente nye saker "
            "igjen.",
            file=sys.stderr,
        )
        print("Appen fortsetter å vise forrige vellykkede import.", file=sys.stderr)
        return False
    image_dir.mkdir(parents=True, exist_ok=True)
    try:
        _acquire_lock(lock)
    except ScraperError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return False

    started_at = _now()
    status = _read_json(status_file) or {}
    browser: Browser | None = None
    try:
        check_profile(profile)
        if not profile.is_dir() or not os.access(profile, os.R_OK):
            raise ScraperError("LOGIN_REQUIRED", f"Fant ikke innloggingsprofilen.\n{LOGIN_HELP}")
        if open_browser is None:
            if importlib.util.find_spec("playwright") is None:
                raise ScraperError(
                    "PLAYWRIGHT_MISSING",
                    "Scraperen trenger Playwright. Kjør den med make scrape fra rotmappen.",
                )
            open_browser = _open_browser

        previous = (_read_json(cache_file) or {}).get("articles")
        cached = [a for a in previous if isinstance(a, dict)] if isinstance(previous, list) else []
        cached_ids = {a.get("id") for a in cached}

        items = parse_rss(read_rss(rss_file))
        candidates = select_candidates(items, limit=limit, days=days)
        if not candidates:
            raise ScraperError(
                "NO_CANDIDATES", "Fant ingen relevante saker fra den siste uken i RSS-feeden."
            )
        to_import = candidates if refresh else [c for c in candidates if c["id"] not in cached_ids]
        reused = len(candidates) - len(to_import)
        print(
            f"RSS: {len(items)} saker, {len(candidates)} valgt for studenter, "
            f"{len(to_import)} skal hentes."
        )

        browser = open_browser(profile)
        imported: list[dict] = []
        skipped: list[dict] = []
        imported_at = _now()
        for candidate in to_import:
            try:
                result = import_one(browser, candidate, imported_at, image_dir)
            except Exception as error:
                code = getattr(error, "code", None)
                if code == "BROWSER_UNAVAILABLE":
                    raise
                if not (isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]+", code)):
                    code = "ARTICLE_FAILED"
                skipped.append(
                    {
                        "id": candidate["id"],
                        "title": candidate["title"],
                        "access": "unknown",
                        "error": code,
                    }
                )
                print(f"  feilet       {candidate['id']}  {code}  {candidate['title']}")
                continue
            if "skipped" in result:
                skipped.append(result["skipped"])
                access = result["skipped"]["access"]
                print(f"  hoppet over  {candidate['id']}  tilgang: {access}  {candidate['title']}")
                continue
            article = result["article"]
            imported.append(article)
            summary = article["summary"]
            points = (
                f"{len(summary['bullets'])} oppsummeringspunkter"
                if summary
                else "ingen oppsummering"
            )
            photo = "bilde"
            if not article["image"]:
                photo = "uten bilde" + (
                    f" ({', '.join(result['warnings'])})" if result["warnings"] else ""
                )
            print(f"  hentet       {article['id']}  {points}, {photo}  {article['title']}")

        gated = sum(1 for s in skipped if s.get("gated"))
        if to_import and not imported:
            if gated:
                raise ScraperError(
                    "LOGIN_REQUIRED",
                    "Adressa viste betalingsmur på sakene. Innloggingen ser ut til å være utløpt."
                    f"\n{LOGIN_HELP}",
                )
            raise ScraperError(
                "NOTHING_IMPORTED",
                "Ingen saker kunne hentes med bekreftet tilgang. Forrige datasett beholdes.",
            )

        # After a successful run the cache holds this week's picks. Earlier imports stay if they
        # are still picked, or if they have only dropped out of RSS; older than `days` they go.
        picked = {c["id"] for c in candidates}
        in_rss = {stable_id(key) for item in items if (key := article_key(item["url"]))}
        oldest = datetime.now(UTC) - timedelta(days=days)
        kept = [
            a
            for a in cached
            if (a.get("id") in picked or a.get("id") not in in_rss)
            and (published := parse_time(a.get("publishedAt")))
            and published >= oldest
        ]
        articles = merge_articles(kept, imported, MAX_ARTICLES)
        finished_at = _now()
        _write_json(
            cache_file,
            {
                "version": 1,
                "source": SOURCE,
                "rss": RSS_URL,
                "importedAt": finished_at,
                "articles": articles,
            },
        )
        _remove_unused_images(image_dir, articles)
        warning = (
            f"{gated} sak(er) lå bak betalingsmur. Innloggingen kan være utløpt; kjør ny "
            "innlogging hvis det gjelder abonnementssaker."
            if gated
            else None
        )
        _write_json(
            status_file,
            {
                "lastSuccessAt": finished_at,
                "lastAttempt": {
                    "startedAt": started_at,
                    "finishedAt": finished_at,
                    "ok": True,
                    "imported": len(imported),
                    "reused": reused,
                    "skipped": [
                        {k: s[k] for k in ("id", "title", "access", "error") if k in s}
                        for s in skipped
                    ],
                    "warning": warning,
                },
            },
        )
        print(
            f"Ferdig: {len(imported)} nye, {reused} fra før, {len(skipped)} hoppet over. "
            f"Cachen har {len(articles)} saker."
        )
        if warning:
            print(f"Advarsel: {warning}\n{LOGIN_HELP}")
        return True
    # Every failure is recorded, and the previous cache stays.
    except Exception as error:  # noqa: BLE001
        known = isinstance(error, ScraperError)
        code = error.code if known else "UNEXPECTED_ERROR"
        # Browser errors can carry session URLs, so unknown errors are never printed as they are.
        message = error.message if known else "Importen stoppet uventet. Forrige datasett beholdes."
        try:
            _write_json(
                status_file,
                {
                    **status,
                    "lastAttempt": {
                        "startedAt": started_at,
                        "finishedAt": _now(),
                        "ok": False,
                        "code": code,
                        "message": message.split("\n")[0],
                    },
                },
            )
        except OSError:
            pass
        print(f"{code}: {message}", file=sys.stderr)
        print("Appen fortsetter å vise forrige vellykkede import.", file=sys.stderr)
        return False
    finally:
        if browser is not None:
            browser.close()
        lock.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hent ukens studentrelevante saker fra Adressa til den lokale cachen"
    )
    parser.add_argument("--limit", type=int, default=8, help="antall saker, 1–20 (8)")
    parser.add_argument("--days", type=int, default=7, help="dager tilbake, 1–14 (7)")
    parser.add_argument("--refresh", action="store_true", help="hent også saker som er i cachen")
    parser.add_argument("--rss-file", type=Path, help="les RSS fra en fil i stedet for adressa.no")
    args = parser.parse_args()

    folder = cache_dir()
    if folder is None:
        sys.exit(
            "Sett ADRESSA_CACHE_DIR i backend/.env til mappen for Adressa-cachen (cache/adressa)"
        )
    ok = scrape(
        folder,
        profile=Path(settings.adressa_profile_dir).expanduser(),
        limit=min(20, max(1, args.limit)),
        days=min(14, max(1, args.days)),
        refresh=args.refresh,
        rss_file=args.rss_file,
    )
    if not ok:
        sys.exit(1)
