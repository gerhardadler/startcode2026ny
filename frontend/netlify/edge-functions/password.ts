// The password in front of the whole hosted app. Behind it, /private/ serves Adressa's full stories
// and photos as they are (see scripts/copy-stories.mjs), so every path except the fonts and the logo
// needs it, /api too. SITE_PASSWORD is set in Netlify (`netlify env:set`); without it nothing opens.
import type { Config, Context } from "@netlify/edge-functions";

const COOKIE = "oppdatert-tilgang";
const DAYS = 30;
const LOGIN = "/logg-inn";
const SIGNED = "oppdatert-tilgang-v1";

const encoder = new TextEncoder();

// The cookie holds a signature made with the password as key: it proves the password was given
// without storing it, and a new password logs everyone out.
async function sign(password: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(password),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(SIGNED)));
  return Array.from(mac, (b) => b.toString(16).padStart(2, "0")).join("");
}

// Takes as long for every wrong answer, so the time says nothing about the password.
function same(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// Back to where the reader was going, but only on this site.
function target(value: unknown, base: string): string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") ? value : `${base}/`;
}

export default async (request: Request, context: Context) => {
  const password = Netlify.env.get("SITE_PASSWORD");
  if (!password) return new Response("Oppdatert er stengt: passordet er ikke satt.", { status: 503 });
  const token = await sign(password);
  if (same(context.cookies.get(COOKIE) ?? "", token)) return context.next();

  // "" on the app's own site. galak.se proxies /oppdatert/* here without the prefix, so that copy
  // has APP_BASE=/oppdatert and puts it back on the addresses the browser gets (see src/base.ts).
  const base = (Netlify.env.get("APP_BASE") ?? "").replace(/\/$/, "");
  const url = new URL(request.url);
  if (url.pathname === LOGIN && request.method === "POST") {
    const form = await request.formData();
    const next = target(form.get("neste"), base);
    const given = form.get("passord");
    if (typeof given === "string" && same(await sign(given), token)) {
      return new Response(null, {
        status: 303,
        headers: {
          Location: next,
          "Set-Cookie": `${COOKIE}=${token}; Path=${base || "/"}; Max-Age=${DAYS * 86400}; HttpOnly; Secure; SameSite=Lax`,
        },
      });
    }
    return page(next, true, base);
  }
  return page(base + (url.pathname === LOGIN ? "/" : url.pathname + url.search), false, base);
};

export const config: Config = {
  path: "/*",
  // The login page needs these, and they are public on adressa.no anyway.
  excludedPath: ["/assets/fonts/*", "/assets/brand/*"],
};

const escape = (text: string) =>
  text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

// Same look as the app: the dark theme tokens and Adressa's fonts, with no script of its own.
function page(next: string, wrong: boolean, base: string): Response {
  const html = `<!doctype html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#101010">
<meta name="robots" content="noindex">
<title>Oppdatert</title>
<link rel="icon" href="${base}/assets/brand/opplyst-icon.svg" type="image/svg+xml">
<style>
@font-face { font-family: Acta; src: url("${base}/assets/fonts/acta_800.woff2") format("woff2"); font-weight: 800; font-display: swap; }
@font-face { font-family: Stag; src: url("${base}/assets/fonts/Stag-Semibold.otf") format("opentype"); font-weight: 600; font-display: swap; }
@font-face { font-family: Roboto; src: url("${base}/assets/fonts/Roboto-Regular.ttf") format("truetype"); font-weight: 400; font-display: swap; }
@font-face { font-family: Roboto; src: url("${base}/assets/fonts/Roboto-Bold.ttf") format("truetype"); font-weight: 700; font-display: swap; }
:root { color-scheme: dark; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #101010; color: #F6F6F6; }
body { font: 400 16px/1.5 Roboto, system-ui, sans-serif; font-synthesis: none; -webkit-font-smoothing: antialiased; }
main { max-width: 420px; min-height: 100dvh; margin: 0 auto; padding: calc(env(safe-area-inset-top, 0px) + 28px) 20px 40px; display: flex; flex-direction: column; }
.brand { margin: 0 0 auto; }
.brand-name { display: block; font: 600 30px/0.95 Stag, Georgia, serif; }
.brand-from { display: block; margin-top: 4px; font: 700 14px/1.2 Roboto, system-ui, sans-serif; }
form { margin: 48px 0 auto; }
h1 { margin: 0 0 12px; font: 800 36px/1.08 Acta, Georgia, serif; }
p { margin: 0 0 24px; color: #B9B9B9; }
label { display: block; margin-bottom: 8px; font-weight: 700; }
input { width: 100%; min-height: 48px; padding: 10px 14px; border: 1.5px solid #3A3A3A; border-radius: 8px; background: #1A1A1A; color: #F6F6F6; font: inherit; }
input:focus-visible, button:focus-visible { outline: 3px solid #28AAE2; outline-offset: 2px; }
button { width: 100%; min-height: 48px; margin-top: 16px; padding: 10px 20px; border: 0; border-radius: 8px; background: #28AAE2; color: #101010; font: 700 17px/1.2 Roboto, system-ui, sans-serif; cursor: pointer; }
button:hover { background: #62C1EB; }
.wrong { margin: 12px 0 0; color: #FFABA4; font-weight: 700; }
</style>
</head>
<body>
<main>
<div class="brand"><span class="brand-name">Oppdatert</span><span class="brand-from">fra Adressa</span></div>
<form method="post" action="${base}${LOGIN}">
<h1>Skriv inn passordet</h1>
<p>Demoen av Oppdatert viser saker fra Adresseavisen og er bare for dem som har fått passordet.</p>
<input type="hidden" name="neste" value="${escape(next)}">
<label for="passord">Passord</label>
<input id="passord" name="passord" type="password" autocomplete="current-password" required autofocus${wrong ? ' aria-describedby="feil" aria-invalid="true"' : ""}>
${wrong ? '<p class="wrong" id="feil" role="alert">Feil passord. Prøv igjen.</p>' : ""}
<button type="submit">Åpne Oppdatert</button>
</form>
</main>
</body>
</html>`;
  return new Response(html, {
    status: 401,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex" },
  });
}
