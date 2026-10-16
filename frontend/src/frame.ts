// On a computer the app shows inside a drawn iPhone (components/PhoneFrame.tsx). The page then only
// holds the phone, and the app runs in an iframe the size of an iPhone screen, so its layout, fixed
// bars, scrolling and 100dvh are exactly what a phone gets and nothing is scaled while it runs.

/** This is the app inside the phone: the page around it is this same app, on the same site. */
export const inPhone = (() => {
  try {
    return window.parent !== window && window.parent.location.origin === location.origin;
  } catch {
    return false; // Embedded by another site: run as usual.
  }
})();

/** On a computer with a mouse, draw the phone instead of running the app in the window itself. */
export const showPhone =
  window.parent === window && matchMedia("(hover: hover) and (pointer: fine) and (min-width: 600px)").matches;
