import { appUrl, mediaUrl } from "./base";

export type StoryImage ={ src: string; alt: string | null; caption: string | null; credit: string | null };

/** Adressa's own «Kort oppsummert», unchanged, with its AI and editorial disclosure. */
export type Summary = {
  heading: string;
  bullets: string[];
  source: string;
  sourceUrl: string;
  disclosure: string | null;
  disclosureUrl: string | null;
};

/** Opplyst's own short version, written by Claude on the server. Never Adressa's. */
export type OpplystSummary = {
  /** Two or three short bullet points. */
  points: string[];
  label: string;
  model: string;
  promptVersion: string;
  generatedAt: string;
  source: string;
  sourceUrl: string;
};

export type Block = { type: "paragraph" | "heading" | "list"; text: string | null; items: string[] | null };

export type Story = {
  id: string;
  title: string;
  url: string;
  category: string;
  source: string;
  publishedAt: string;
  modifiedAt: string | null;
  authors: string[];
  lead: string | null;
  summary: Summary | null;
  image: StoryImage | null;
  body: Block[];
  /** True when the local Adressa import has the full article on this machine. */
  imported: boolean;
  opplystSummary: OpplystSummary | null;
};

/** One of Adressa's own vertical videos. articleId is null until a link to a story is documented. */
export type Video = {
  id: string;
  title: string;
  description: string | null;
  publishedAt: string;
  source: string;
  platform: string;
  sourceUrl: string;
  articleId: string | null;
  duration: number;
  width: number;
  height: number;
  src: string;
  poster: string;
};

export type FeedEntry = { type: "article" | "video"; id: string };

export type Stories = {
  week: number;
  importedAt: string | null;
  stories: Story[];
  videos: Video[];
  /** The order of the one feed that mixes stories and videos. */
  feed: FeedEntry[];
};

export type Headline = { id: number; text: string; story_id: string };

export type Quiz = { id: string; date: string; week: number; max_hints: number; headlines: Headline[] };

export type GuessResult = {
  score: number;
  solved: boolean;
  answer: string | null;
  full_text: string | null;
};


async function request<T>(path: string, init: RequestInit | undefined, failure: string): Promise<T> {
  const res = await fetch(appUrl(path), init);
  if (!res.ok) throw new Error(`${failure} (${res.status})`);
  return res.json();
}

export async function fetchStories(): Promise<Stories> {
  const data = await request<Stories>("/api/stories", undefined, "Vi kunne ikke hente sakene");
  // An older backend has no videos or feed order: then the feed is the stories.
  return {
    ...data,
    stories: data.stories.map((s) => (s.image ? { ...s, image: { ...s.image, src: mediaUrl(s.image.src) } } : s)),
    videos: (data.videos ?? []).map((v) => ({ ...v, src: mediaUrl(v.src), poster: mediaUrl(v.poster) })),
    feed: data.feed ?? data.stories.map((s) => ({ type: "article" as const, id: s.id })),
  };
}

export function fetchQuiz(): Promise<Quiz> {
  return request("/api/quiz", undefined, "Vi kunne ikke hente dagens quiz");
}

export function submitGuess(headlineId: number, guess: string): Promise<GuessResult> {
  return request(
    "/api/guess",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ headline_id: headlineId, guess }),
    },
    "Vi fikk ikke sjekket svaret. Prøv igjen",
  );
}

export function revealAnswer(headlineId: number): Promise<{ answer: string; full_text: string }> {
  return request(
    `/api/headlines/${headlineId}/reveal`,
    { method: "POST" },
    "Vi fikk ikke hentet svaret",
  );
}
