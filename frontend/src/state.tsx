import {
  createContext,
  ReactNode,
  RefObject,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { FeedEntry, Quiz, revealAnswer, Stories, Story, submitGuess, Video } from "./api";
import { Icon } from "./icons";
import { isComplete, isDone, loadProgress, newProgress, QuestionState, QuizProgress, saveProgress } from "./quiz";
import { loadIds, save } from "./storage";
import { loadStreak, recordCompletion, Streak } from "./streak";

type FeedFilter = { query: string; category: string };

type AppState = {
  stories: Story[];
  storiesById: Map<string, Story>;
  videos: Video[];
  videosById: Map<string, Video>;
  /** The one feed of stories and videos, in the backend's stable order after api.ts's FEED_FIRST. */
  feed: FeedEntry[];
  /** When the local Adressa import last succeeded, or null when this machine has none. */
  importedAt: string | null;
  quiz: Quiz;
  progress: QuizProgress;
  streak: Streak;
  start: () => void;
  guess: (word: string) => Promise<void>;
  giveUp: () => Promise<void>;
  setDraft: (text: string) => void;
  next: () => void;
  restart: () => void;
  markQuizRead: (storyId: string) => void;
  saved: string[];
  toggleSaved: (id: string) => void;
  /** Stories the reader has opened. Opening is not the same as having read them. */
  opened: string[];
  markOpened: (id: string) => void;
  filter: FeedFilter;
  setFilter: (filter: FeedFilter) => void;
  toast: (message: string) => void;
  showAbout: () => void;
};

const AppContext = createContext<AppState | null>(null);

export function useApp(): AppState {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}

const SAVED_KEY = "opplyst-saved-v1";
const OPENED_KEY = "opplyst-read-v1";

type Props = { data: Stories; quiz: Quiz; children: ReactNode };

export function AppProvider({ data, quiz, children }: Props) {
  const { stories, videos, feed, importedAt } = data;
  const storiesById = useMemo(() => new Map(stories.map((s) => [s.id, s])), [stories]);
  const videosById = useMemo(() => new Map(videos.map((v) => [v.id, v])), [videos]);
  const ids = useMemo(() => [...stories.map((s) => s.id), ...videos.map((v) => v.id)], [stories, videos]);

  const [progress, setProgress] = useState(() => loadProgress(quiz));
  const progressRef = useRef(progress);
  progressRef.current = progress;
  useEffect(() => saveProgress(progress), [progress]);

  const [streak, setStreak] = useState(loadStreak);
  const complete = isComplete(progress);
  useEffect(() => {
    if (complete) setStreak((s) => recordCompletion(s, quiz.date));
  }, [complete, quiz.date]);

  const [saved, setSaved] = useState(() => loadIds(SAVED_KEY, ids));
  const [opened, setOpened] = useState(() => loadIds(OPENED_KEY, ids));
  const [filter, setFilter] = useState<FeedFilter>({ query: "", category: "Alle" });

  const [toastState, setToastState] = useState({ message: "", visible: false });
  const toastTimer = useRef<number | undefined>(undefined);
  const toast = useCallback((message: string) => {
    setToastState({ message, visible: true });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastState((t) => ({ ...t, visible: false })), 3000);
  }, []);

  const aboutRef = useRef<HTMLDialogElement>(null);
  const showAbout = useCallback(() => aboutRef.current?.showModal(), []);

  const updateQuestion = useCallback((index: number, change: (q: QuestionState) => QuestionState) => {
    setProgress((p) => ({ ...p, questions: p.questions.map((q, i) => (i === index ? change(q) : q)) }));
  }, []);

  const start = useCallback(() => setProgress((p) => (p.started ? p : { ...p, started: true })), []);

  const guess = useCallback(
    async (word: string) => {
      const index = progressRef.current.index;
      if (isDone(progressRef.current.questions[index])) return;
      const res = await submitGuess(quiz.headlines[index].id, word);
      updateQuestion(index, (q) =>
        isDone(q)
          ? q
          : {
              ...q,
              // A wrong word stays in the headline's gap, so the player sees how it reads.
              draft: res.solved ? "" : q.draft,
              guesses: [...q.guesses, { word, score: res.score }],
              // Only the backend's verdict solves a question; a high score alone does not.
              ...(res.solved ? { answer: res.answer, fullText: res.full_text } : {}),
            },
      );
    },
    [quiz, updateQuestion],
  );

  const giveUp = useCallback(async () => {
    const index = progressRef.current.index;
    if (isDone(progressRef.current.questions[index])) return;
    const res = await revealAnswer(quiz.headlines[index].id);
    updateQuestion(index, (q) =>
      isDone(q) ? q : { ...q, answer: res.answer, fullText: res.full_text, gaveUp: true, draft: "" },
    );
  }, [quiz, updateQuestion]);

  const setDraft = useCallback(
    (text: string) => updateQuestion(progressRef.current.index, (q) => (q.draft === text ? q : { ...q, draft: text })),
    [updateQuestion],
  );

  const next = useCallback(() => {
    setProgress((p) =>
      p.index >= p.questions.length - 1 ? { ...p, finished: true } : { ...p, index: p.index + 1 },
    );
  }, []);

  const restart = useCallback(() => setProgress({ ...newProgress(quiz), started: true }), [quiz]);

  const markQuizRead = useCallback(
    (storyId: string) => {
      setProgress((p) => {
        const changed = p.questions.some((q, i) => quiz.headlines[i].story_id === storyId && !q.readStory);
        if (!changed) return p;
        return {
          ...p,
          questions: p.questions.map((q, i) =>
            quiz.headlines[i].story_id === storyId ? { ...q, readStory: true } : q,
          ),
        };
      });
    },
    [quiz],
  );

  const toggleSaved = useCallback(
    (id: string) => {
      const wasSaved = saved.includes(id);
      const nextSaved = wasSaved ? saved.filter((x) => x !== id) : [id, ...saved];
      if (!save(SAVED_KEY, nextSaved)) {
        toast("Nettleseren kunne ikke lagre endringen.");
        return;
      }
      setSaved(nextSaved);
      const what = videosById.has(id) ? "Videoen" : "Saken";
      toast(wasSaved ? `${what} er fjernet fra Lagret` : `${what} er lagret på denne enheten`);
    },
    [saved, toast, videosById],
  );

  const markOpened = useCallback((id: string) => {
    setOpened((current) => {
      if (current[0] === id) return current;
      const nextOpened = [id, ...current.filter((x) => x !== id)];
      save(OPENED_KEY, nextOpened);
      return nextOpened;
    });
  }, []);

  const value: AppState = {
    stories,
    storiesById,
    videos,
    videosById,
    feed,
    importedAt,
    quiz,
    progress,
    streak,
    start,
    guess,
    giveUp,
    setDraft,
    next,
    restart,
    markQuizRead,
    saved,
    toggleSaved,
    opened,
    markOpened,
    filter,
    setFilter,
    toast,
    showAbout,
  };

  return (
    <AppContext.Provider value={value}>
      {children}
      <div className={`toast ${toastState.visible ? "visible" : ""}`} role="status" aria-live="polite">
        {toastState.message}
      </div>
      <About dialogRef={aboutRef} />
    </AppContext.Provider>
  );
}

function canGoFullscreen(): boolean {
  return (
    Boolean(document.fullscreenEnabled) &&
    !document.fullscreenElement &&
    !matchMedia("(display-mode: fullscreen), (display-mode: standalone)").matches
  );
}

async function enterFullscreen() {
  try {
    await document.documentElement.requestFullscreen({ navigationUI: "hide" });
    // Phones keep the app upright where the browser allows it.
    await (screen.orientation as ScreenOrientation & { lock?: (o: string) => Promise<void> }).lock?.("portrait");
  } catch {
    // Fullscreen or the orientation lock was refused; the app works the same without.
  }
}

function About({ dialogRef }: { dialogRef: RefObject<HTMLDialogElement | null> }) {
  const close = () => dialogRef.current?.close();
  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="about-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) e.currentTarget.close();
      }}
    >
      <div className="modal-head">
        <h2 id="about-title">Om Oppdatert</h2>
        <button className="icon-button" onClick={close} aria-label="Lukk">
          <Icon name="close" />
        </button>
      </div>
      <div className="modal-body">
        <p>
          Oppdatert gjør én nyhet forståelig om gangen. Hver dag får du en quiz med spørsmål fra ukens
          nyheter. Står du fast, leser du saken og går tilbake til spørsmålet. Det koster ingen poeng. Hopper du over, får
          du se svaret, men ingen poeng for spørsmålet.
        </p>
        <p>
          Nærheten (0–100) viser hvor nær betydningen gjetningen din er ordet som mangler. Claude vurderer
          gjetningene. Kortversjonene merket «Oppsummert av Oppdatert med KI» er skrevet av Claude ut fra
          saken. Avisens egen «Kort oppsummert» vises uendret i saken.
        </p>
        <p className="small">
          Startbildet: Nedre Bakklandet. Foto:{" "}
          <a href="https://commons.wikimedia.org/wiki/File:Nedre_Bakklandet.jpg" target="_blank" rel="noopener noreferrer">
            Guy Delsaut, Wikimedia Commons
          </a>
          ,{" "}
          <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener noreferrer">
            CC BY-SA 4.0
          </a>
          . Nedskalert og komprimert; utsnitt i visningen.
        </p>
        <p className="small">
          Quizfremdrift og lagrede saker lagres bare i denne nettleseren.
        </p>
        <div className="modal-actions">
          {canGoFullscreen() && (
            <button
              className="btn btn-outline"
              onClick={() => {
                close();
                enterFullscreen();
              }}
            >
              Vis i fullskjerm
            </button>
          )}
        </div>
      </div>
    </dialog>
  );
}
