// Where the app is served from: "" on its own site, "/oppdatert" where galak.se proxies to a build
// made with APP_BASE=/oppdatert (see vite.config.ts). The app's own paths, like "/nyheter" and
// "/api/quiz", get it in front before the browser sees them.
export const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");

/** A path on this app's site as the browser must ask for it. Full URLs pass through. */
export function appUrl(path: string): string {
  return path.startsWith("/") && !path.startsWith("//") ? BASE + path : path;
}

/** The app's own path for an address the browser shows, without BASE. */
export function appPath(pathname: string): string {
  return BASE && pathname.startsWith(BASE) ? pathname.slice(BASE.length) || "/" : pathname;
}

/**
 * A photo or video from the backend. The backend on Render points the videos at the hosted frontend
 * (VIDEO_PUBLIC_URL). A build under BASE has the same files from its own build, and that other
 * site's password wouldn't let them through here anyway, so it plays its own copies.
 */
export function mediaUrl(src: string): string {
  if (!BASE || !/^https?:/.test(src)) return appUrl(src);
  const { pathname } = new URL(src);
  return pathname.startsWith("/media/video/") ? BASE + pathname : src;
}
