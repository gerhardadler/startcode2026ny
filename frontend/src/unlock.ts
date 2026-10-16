import type { Stories, Story } from "./api";
import { appUrl } from "./base";

type PrivateStory = Pick<Story, "lead" | "authors" | "modifiedAt" | "summary" | "body" | "opplystSummary"> &
  Partial<Pick<Story, "image">>;

/**
 * On the hosted app, add the full stories (Adressa's summary, the article text, the photos and
 * Oppdatert's bullet points) from /private/stories.json, which the build writes from the local
 * Adressa import and the site's password protects (see scripts/copy-stories.mjs). Locally the
 * backend has them already; without the file the stories stay as the public facts.
 */
export async function withFullStories(data: Stories): Promise<Stories> {
  if (data.stories.every((s) => s.imported)) return data;
  try {
    const res = await fetch(appUrl("/private/stories.json"), { cache: "no-cache" });
    if (!res.ok) return data;
    const full = (await res.json()) as { importedAt: string | null; stories: Record<string, PrivateStory> };
    return {
      ...data,
      importedAt: data.importedAt ?? full.importedAt,
      stories: data.stories.map((s) => {
        const extra = full.stories[s.id];
        if (!extra || s.imported) return s;
        return {
          ...s,
          ...extra,
          lead: extra.lead ?? s.lead,
          image: extra.image ? { ...extra.image, src: appUrl(extra.image.src) } : s.image,
          opplystSummary: extra.opplystSummary ?? s.opplystSummary ?? null,
          imported: true,
        };
      }),
    };
  } catch {
    // No file (the dev server answers with the app itself) or a damaged one: the public stories.
    return data;
  }
}
