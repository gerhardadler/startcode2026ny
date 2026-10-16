import json
import os
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import pytest

from app.scraper import run
from app.scraper.adressa import (
    OSLO,
    ScraperError,
    article_key,
    category_for,
    image_type,
    merge_articles,
    parse_rss,
    safe_url,
    select_candidates,
    split_caption,
    stable_id,
    student_relevance,
    to_iso,
    write_file_atomic,
)

NOW = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)


def item(key, section, published, title, **extra):
    return {
        "title": title,
        "url": f"https://www.adressa.no/{section}/i/{key}/slug",
        "published": published,
        **extra,
    }


def test_article_keys_become_stable_ids():
    assert article_key("https://www.adressa.no/nyheter/trondheim/i/gdBzx0/samboeren") == "gdBzx0"
    assert article_key("https://www.adressa.no/nyheter/trondheim/") is None
    assert stable_id("gdBzx0") == "adressa-gdBzx0"


def test_only_https_links_on_adressa_are_followed():
    assert (
        safe_url("https://www.adressa.no/nyheter/i/a1/x?utm=1#top", article=True)
        == "https://www.adressa.no/nyheter/i/a1/x"
    )
    assert safe_url("/sport/i/b2/y") == "https://www.adressa.no/sport/i/b2/y"
    for bad in [
        "http://www.adressa.no/nyheter/i/a1/x",
        "https://adressa.no.example.com/nyheter/i/a1/x",
        "https://www.adressa.no:8443/nyheter/i/a1/x",
        "https://user:pw@www.adressa.no/nyheter/i/a1/x",
    ]:
        with pytest.raises(ScraperError):
            safe_url(bad)
    with pytest.raises(ScraperError, match="/i/"):
        safe_url("https://www.adressa.no/nyheter/", article=True)


def test_sections_map_to_categories_and_opinion_video_and_mn24_are_left_out():
    assert category_for("https://www.adressa.no/nyheter/trondheim/i/a1/x") == "Trondheim"
    assert category_for("https://www.adressa.no/nyheter/trondelag/i/a1/x") == "Trøndelag"
    assert category_for("https://www.adressa.no/nyheter/i/a1/x") == "Nyheter"
    assert category_for("https://www.adressa.no/sport/fotball/i/a1/x") == "Sport"
    for section in ["debatt", "video", "nyhetsstudio", "mn24", "nytte", "trd.by"]:
        assert category_for(f"https://www.adressa.no/{section}/i/a1/x") is None, section


def test_student_relevance_counts_what_the_story_is_about_and_tags_only_by_half():
    exam = {
        "title": "Må ta eksamen med penn og papir",
        "description": "Studenter ved NTNU reagerer",
    }
    assert student_relevance(exam) == {"score": 3, "topics": ["Studentliv"]}
    # An NTNU expert quoted in a US story is not student life.
    texas = {
        "title": "Ville påstander i Texas",
        "description": "Kampen om senatorplass",
        "categories": ["NTNU", "USA"],
    }
    assert student_relevance(texas)["score"] == 1
    assert (
        student_relevance({"title": "Elg på tunet", "description": "Hyggelig besøk"})["score"] == 0
    )
    buses = student_relevance({"title": "Flere busser gjennom Midtbyen"})
    assert "Kollektiv og transport" in buses["topics"]


def test_candidates_are_the_most_relevant_of_the_week_sorted_on_publication_time():
    items = [
        item(
            "old111", "nyheter/trondheim", "Mon, 05 Oct 2026 10:00:00 GMT", "Eksamen for studenter"
        ),
        item(
            "aaa111",
            "nyheter/trondheim",
            "Wed, 14 Oct 2026 08:00:00 GMT",
            "Studentene får ny studentbolig",
        ),
        item("bbb222", "politikk", "Thu, 15 Oct 2026 09:00:00 GMT", "Flere busser og ny bybane"),
        item("ccc333", "debatt", "Thu, 15 Oct 2026 10:00:00 GMT", "Studenter må få bolig"),
        item("ddd444", "kultur", "Thu, 15 Oct 2026 11:00:00 GMT", "Konsert i kveld"),
        item(
            "aaa111", "nyheter/trondheim", "Wed, 14 Oct 2026 08:00:00 GMT", "Duplikat av samme sak"
        ),
        item(
            "eee555",
            "nyheter/trondheim",
            "Thu, 15 Oct 2026 12:00:00 GMT",
            "Annonse om studentrabatt",
            categories=["Annonse"],
        ),
        item(
            "fff666",
            "nyheter/trondheim",
            "Thu, 15 Oct 2026 07:00:00 GMT",
            "Ny jobb til 550 søkere",
            description="Mange vil ha jobb",
        ),
    ]
    picked = select_candidates(items, now=NOW, limit=2)
    assert [c["id"] for c in picked] == ["adressa-bbb222", "adressa-aaa111"]
    assert all(c["relevance"]["score"] >= 2 for c in picked)
    assert picked[1]["publishedAt"] == "2026-10-14T08:00:00.000Z"
    every = select_candidates(items, now=NOW, limit=10)
    assert [c["id"] for c in every] == ["adressa-bbb222", "adressa-fff666", "adressa-aaa111"]


def test_captions_are_split_from_the_photographer_credit():
    assert split_caption("Her er mannen på vei vekk. FOTO: SKJERMPRINT FRA VIDEO") == (
        "Her er mannen på vei vekk.",
        "SKJERMPRINT FRA VIDEO",
    )
    assert split_caption("Foto: Leif Arne Holme") == (None, "Leif Arne Holme")
    assert split_caption("Bare en bildetekst") == ("Bare en bildetekst", None)
    assert split_caption(None) == (None, None)


def test_image_bytes_are_recognised_by_their_signature_not_their_name():
    assert image_type(bytes([0xFF, 0xD8, 0xFF, 0xE1, 0, 0])) == "image/jpeg"
    assert image_type(b"\x89PNG\r\n\x1a\n0000") == "image/png"
    assert image_type(b"RIFF0000WEBPVP8 ") == "image/webp"
    assert image_type(b"0000ftypavif0000") == "image/avif"
    assert image_type(b"<html>not an image</html>") is None


def test_photos_are_fetched_at_feed_width_and_only_from_adressas_image_service(tmp_path):
    large = "https://vcdn.polarismedia.no/abc?fit=crop&h=2000&q=80&w=3200"
    assert run.feed_sized_image_url(large) == (
        "https://vcdn.polarismedia.no/abc?fit=crop&h=1250&q=80&w=2000"
    )
    # The page's own 1000 px copy is too soft for a full-screen phone card, so small ones grow too.
    small = "https://vcdn.polarismedia.no/abc?fit=crop&h=700&q=80&w=1000"
    assert run.feed_sized_image_url(small) == (
        "https://vcdn.polarismedia.no/abc?fit=crop&h=1400&q=80&w=2000"
    )
    # Without a width there is nothing to scale from.
    bare = "https://vcdn.polarismedia.no/abc?q=80"
    assert run.feed_sized_image_url(bare) == bare
    assert run.download_image("https://example.com/a.jpg", "adressa-a1", tmp_path) == {
        "error": "IMAGE_HOST_NOT_ALLOWED"
    }
    assert run.share_image_url("https://vcdn.polarismedia.no/og?w=1200") is not None
    assert run.share_image_url("https://example.com/og.jpg") is None


def test_merging_keeps_earlier_articles_lets_new_imports_win_and_caps_the_set():
    def a(story_id, day, title="x"):
        return {"id": story_id, "title": title, "publishedAt": f"2026-10-{day}T10:00:00Z"}

    merged = merge_articles(
        [a("adressa-1", "10", "gammel"), a("adressa-2", "11")],
        [a("adressa-1", "10", "ny"), a("adressa-3", "12")],
        2,
    )
    assert [x["id"] for x in merged] == ["adressa-3", "adressa-2"]
    assert (
        merge_articles([a("adressa-1", "10", "gammel")], [a("adressa-1", "10", "ny")])[0]["title"]
        == "ny"
    )


def test_atomic_writes_replace_the_file_and_leave_no_temporary_files(tmp_path):
    file = tmp_path / "articles.json"
    write_file_atomic(file, '{"v":1}')
    write_file_atomic(file, '{"v":2}')
    assert file.read_text() == '{"v":2}'
    assert [p.name for p in tmp_path.iterdir()] == ["articles.json"]


def rss(*items: str) -> str:
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{"".join(items)}</channel></rss>'


def rss_item(key, section, title, *, hours_ago=1, description="", categories=()):
    published = format_datetime(datetime.now(UTC) - timedelta(hours=hours_ago), usegmt=True)
    tags = "".join(f"<category>{c}</category>" for c in categories)
    return (
        f"<item><title>{title}</title><link>https://www.adressa.no/{section}/i/{key}/slug</link>"
        f"<pubDate>{published}</pubDate><description>{description}</description>{tags}</item>"
    )


def test_rss_items_are_read_and_unsupported_feeds_refused():
    items = parse_rss(
        rss(
            rss_item(
                "aaa111",
                "nyheter/trondheim",
                "Ny studentbolig",
                description="&lt;p&gt;Mer  om\n saken&lt;/p&gt;",
                categories=["NTNU", "Bolig"],
            ),
            "<item><title>Ekstern</title><link>https://mn24.no/i/x1/y</link></item>",
            "<item><title>Med bilde</title><link>https://www.adressa.no/sport/i/b2/z</link>"
            '<enclosure url="https://vcdn.polarismedia.no/b2.jpg" type="image/jpeg"/></item>',
        )
    )
    assert [i["url"] for i in items] == [
        "https://www.adressa.no/nyheter/trondheim/i/aaa111/slug",
        "https://www.adressa.no/sport/i/b2/z",
    ]
    assert items[0]["description"] == "Mer om saken"
    assert items[0]["categories"] == ["NTNU", "Bolig"]
    assert items[1]["image"] == "https://vcdn.polarismedia.no/b2.jpg"
    for bad in [
        '<!DOCTYPE rss [<!ENTITY x "y">]><rss><channel><item/></channel></rss>',
        "<rss><channel><item><title>Ødelagt",
        rss(),
    ]:
        with pytest.raises(ScraperError) as error:
            parse_rss(bad)
        assert error.value.code == "INVALID_FEED"


BODY = " ".join(["Studentene i Trondheim får flere boliger neste høst, sier Sit."] * 3)


class FakeBrowser:
    """Answers like browser.AdressaBrowser: readable stories, or a paywall."""

    def __init__(self, gated: set[str] = frozenset()):
        self.gated = gated
        self.published = (datetime.now(UTC) - timedelta(hours=2)).astimezone(OSLO).isoformat()
        self.read_urls: list[str] = []
        self.closed = False

    def read(self, url):
        self.read_urls.append(url)
        if any(key in url for key in self.gated):
            reason = "A visible subscription or login gate is present."
            return {
                "url": url,
                "body": "",
                "access": {"state": "restricted", "reason": reason},
            }, None
        visible = {
            "url": url + "?utm_source=rss",
            "title": "Tittel fra siden",
            "authors": ["Kari Nordmann"],
            "published": self.published,
            "modified": None,
            "body": f"Ingressen.\n\nPunkt en.\n\n{BODY}\n\n{BODY}\n\n{BODY}",
            "access": {"state": "available", "reason": "Substantial article text."},
        }
        structure = {
            "lead": "Ingressen.",
            "summary": {
                "heading": "Kort oppsummert",
                "bullets": ["Punkt en."],
                "disclosure": "Laget med KI.",
                "disclosureUrl": "https://www.adressa.no/ki?x=1",
            },
            "image": None,
            "ogImage": "https://vcdn.polarismedia.no/og?w=1200",
            "blocks": [],
        }
        return visible, structure

    def close(self):
        self.closed = True


@pytest.fixture
def cache(tmp_path):
    folder = tmp_path / "cache"
    folder.mkdir()
    profile = tmp_path / "profile"
    profile.mkdir()
    previous = {
        "version": 1,
        "importedAt": "2026-10-01T18:00:00.000Z",
        "articles": [
            {
                "id": "adressa-old111",
                "title": "Forrige sak",
                "publishedAt": "2026-09-01T10:00:00.000Z",
            }
        ],
    }
    (folder / "articles.json").write_text(json.dumps(previous))
    return folder, profile


def scrape_with(folder, profile, feed, browser, tmp_path, **options):
    feed_file = tmp_path / "feed.xml"
    feed_file.write_text(feed)
    return run.scrape(
        folder, profile=profile, rss_file=feed_file, open_browser=lambda _: browser, **options
    )


def test_a_successful_import_replaces_the_cache_and_records_it(cache, tmp_path, capsys):
    folder, profile = cache
    browser = FakeBrowser(gated={"bbb222"})
    feed = rss(
        rss_item("aaa111", "nyheter/trondheim", "Studentene får ny studentbolig"),
        rss_item("bbb222", "politikk", "Flere busser og ny bybane"),
        rss_item("ccc333", "debatt", "Studenter må få bolig"),
    )
    assert scrape_with(folder, profile, feed, browser, tmp_path)
    assert browser.closed
    assert len(browser.read_urls) == 2

    data = json.loads((folder / "articles.json").read_text())
    # The old article is more than a week old, so it goes.
    assert [a["id"] for a in data["articles"]] == ["adressa-aaa111"]
    article = data["articles"][0]
    assert article["url"] == "https://www.adressa.no/nyheter/trondheim/i/aaa111/slug"
    assert article["title"] == "Tittel fra siden"
    assert article["category"] == "Trondheim"
    assert article["publishedAt"] == to_iso(browser.published)
    assert article["lead"] == "Ingressen."
    assert article["summary"]["sourceUrl"] == article["url"]
    assert article["summary"]["disclosureUrl"] == "https://www.adressa.no/ki"
    assert article["shareImage"] == "https://vcdn.polarismedia.no/og?w=1200"
    # Without structured blocks the body is the visible text, minus the lead and summary.
    assert article["body"] == [{"type": "paragraph", "text": BODY}] * 3

    status = json.loads((folder / "import-status.json").read_text())
    assert status["lastAttempt"]["ok"] is True
    assert status["lastAttempt"]["imported"] == 1
    assert status["lastAttempt"]["skipped"] == [
        {"id": "adressa-bbb222", "title": "Flere busser og ny bybane", "access": "restricted"}
    ]
    assert "betalingsmur" in status["lastAttempt"]["warning"]
    assert not (folder / ".import.lock").exists()
    assert "hentet       adressa-aaa111" in capsys.readouterr().out

    # The next run reuses what is cached and opens no page for it.
    again = FakeBrowser()
    assert scrape_with(folder, profile, feed, again, tmp_path)
    assert again.read_urls == ["https://www.adressa.no/politikk/i/bbb222/slug"]


def test_a_paywall_on_every_story_asks_for_a_new_login_and_keeps_the_cache(cache, tmp_path, capsys):
    folder, profile = cache
    before = (folder / "articles.json").read_text()
    feed = rss(rss_item("aaa111", "nyheter/trondheim", "Studentene får ny studentbolig"))
    assert not scrape_with(folder, profile, feed, FakeBrowser(gated={"aaa111"}), tmp_path)
    assert "LOGIN_REQUIRED" in capsys.readouterr().err
    assert (folder / "articles.json").read_text() == before
    status = json.loads((folder / "import-status.json").read_text())
    assert status["lastAttempt"]["code"] == "LOGIN_REQUIRED"


def test_a_failed_update_keeps_the_last_cache_and_records_the_failure(cache, tmp_path, capsys):
    folder, profile = cache
    before = (folder / "articles.json").read_text()
    browser = FakeBrowser()
    assert not scrape_with(folder, profile, "<rss><channel><item><title>Ødelagt", browser, tmp_path)
    err = capsys.readouterr().err
    assert "INVALID_FEED" in err
    assert "forrige vellykkede import" in err
    assert (folder / "articles.json").read_text() == before
    status = json.loads((folder / "import-status.json").read_text())
    assert status["lastAttempt"]["ok"] is False
    assert status["lastAttempt"]["code"] == "INVALID_FEED"
    assert not (folder / ".import.lock").exists()
    assert browser.read_urls == []


def test_a_missing_login_profile_stops_before_anything_is_fetched(cache, tmp_path, capsys):
    folder, _ = cache

    def never(_):
        raise AssertionError("the browser was opened")

    ok = run.scrape(
        folder, profile=tmp_path / "finnes-ikke", rss_file=tmp_path / "x.xml", open_browser=never
    )
    assert not ok
    err = capsys.readouterr().err
    assert "LOGIN_REQUIRED" in err
    assert "make adressa-login" in err


def test_the_login_profile_may_never_be_in_the_repo(cache, capsys):
    folder, _ = cache
    profile = run.REPO / "backend" / "profile"
    assert not run.scrape(folder, profile=profile, open_browser=lambda _: FakeBrowser())
    assert "PROFILE_INSIDE_REPO" in capsys.readouterr().err


def test_a_paused_import_fetches_nothing_and_leaves_cache_and_status_as_they_are(
    cache, tmp_path, capsys
):
    folder, profile = cache
    before = (folder / "articles.json").read_text()
    status = '{"lastSuccessAt":"2026-10-15T18:00:00.000Z","lastAttempt":{"ok":true}}'
    (folder / "import-status.json").write_text(status)
    (folder / "PAUSED").write_text("")
    # Without the pause this feed would fail the import and record it, so a missed pause shows.
    browser = FakeBrowser()
    assert not scrape_with(folder, profile, "<rss><channel><item><title>Ødelagt", browser, tmp_path)
    assert "PAUSED" in capsys.readouterr().err
    assert (folder / "articles.json").read_text() == before
    assert (folder / "import-status.json").read_text() == status
    assert not (folder / "images").exists()
    assert not (folder / ".import.lock").exists()
    assert browser.read_urls == []


def test_a_running_import_locks_out_a_second_one(cache, tmp_path, capsys):
    folder, profile = cache
    (folder / ".import.lock").write_text(str(os.getpid()))
    browser = FakeBrowser()
    assert not scrape_with(folder, profile, rss(), browser, tmp_path)
    assert "LOCKED" in capsys.readouterr().err
    assert (folder / ".import.lock").read_text() == str(os.getpid())


def test_a_lock_left_by_a_stopped_import_is_cleared(cache, tmp_path):
    folder, profile = cache
    (folder / ".import.lock").write_text("999999999")
    feed = rss(rss_item("aaa111", "nyheter/trondheim", "Studentene får ny studentbolig"))
    assert scrape_with(folder, profile, feed, FakeBrowser(), tmp_path)
    assert not Path(folder / ".import.lock").exists()
