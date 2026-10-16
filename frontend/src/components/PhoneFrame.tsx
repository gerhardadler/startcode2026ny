import { useEffect, useLayoutEffect, useRef, useState } from "react";

// An iPhone 15 screen in CSS pixels, and the phone around it (see .phone in styles.css).
const SCREEN_W = 393;
const SCREEN_H = 852;
const BEZEL = 14;
const MARGIN = 24;

function clock(): string {
  return new Date().toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" });
}

/**
 * The page on a computer: a drawn iPhone with the app running inside it (see frame.ts). The phone
 * is drawn once and never repaints while the app scrolls; only the clock changes, once a minute.
 */
export default function PhoneFrame() {
  const phoneRef = useRef<HTMLDivElement>(null);
  const [time, setTime] = useState(clock);

  // Smaller windows get a smaller phone, so the whole phone is always in view.
  useLayoutEffect(() => {
    const fit = () => {
      const scale = Math.min(
        1,
        (innerHeight - 2 * MARGIN) / (SCREEN_H + 2 * BEZEL),
        (innerWidth - 2 * MARGIN) / (SCREEN_W + 2 * BEZEL),
      );
      phoneRef.current!.style.transform = scale < 1 ? `scale(${scale})` : "";
    };
    fit();
    addEventListener("resize", fit);
    return () => removeEventListener("resize", fit);
  }, []);

  useEffect(() => {
    let timer: number;
    const tick = () => {
      setTime(clock());
      timer = window.setTimeout(tick, 60_000 - (Date.now() % 60_000));
    };
    timer = window.setTimeout(tick, 60_000 - (Date.now() % 60_000));
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="phone-stage">
      <div className="phone" ref={phoneRef}>
        <span className="phone-button action" aria-hidden="true" />
        <span className="phone-button volume-up" aria-hidden="true" />
        <span className="phone-button volume-down" aria-hidden="true" />
        <span className="phone-button side" aria-hidden="true" />
        <div className="phone-screen">
          {/* No fullscreen in here: it would take the app out of the phone. */}
          <iframe src={location.href} title="Oppdatert" width={SCREEN_W} height={SCREEN_H} allow="fullscreen 'none'" />
          <div className="phone-status" aria-hidden="true">
            <span className="phone-time">{time}</span>
            <span className="phone-island" />
            <span className="phone-icons">
              <svg width="18" height="12" viewBox="0 0 18 12">
                <rect x="0" y="8" width="3" height="4" rx="1" />
                <rect x="5" y="5.5" width="3" height="6.5" rx="1" />
                <rect x="10" y="3" width="3" height="9" rx="1" />
                <rect x="15" y="0" width="3" height="12" rx="1" />
              </svg>
              <svg width="16" height="12" viewBox="0 0 16 12">
                <path d="M8 2.6c2.3 0 4.4.9 6 2.4l1.3-1.3A10.4 10.4 0 0 0 8 .8 10.4 10.4 0 0 0 .7 3.7L2 5c1.6-1.5 3.7-2.4 6-2.4Z" />
                <path d="M8 6.2c1.3 0 2.5.5 3.4 1.3l1.3-1.3A6.6 6.6 0 0 0 8 4.4c-1.8 0-3.5.7-4.7 1.8l1.3 1.3c.9-.8 2.1-1.3 3.4-1.3Z" />
                <path d="M8 9.6 10 7.9a2.9 2.9 0 0 0-4 0L8 9.6Z" transform="translate(0 1.6)" />
              </svg>
              <svg width="27" height="13" viewBox="0 0 27 13">
                <rect x="0.5" y="0.5" width="23" height="12" rx="3.8" fill="none" stroke="currentColor" opacity="0.4" />
                <rect x="2" y="2" width="20" height="9" rx="2.5" />
                <path d="M25 4.5v4c.8-.3 1.3-1.1 1.3-2s-.5-1.7-1.3-2Z" opacity="0.4" />
              </svg>
            </span>
          </div>
          <span className="phone-home" aria-hidden="true" />
        </div>
      </div>
    </div>
  );
}
