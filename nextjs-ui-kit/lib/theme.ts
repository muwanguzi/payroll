/**
 * Runs before first paint to apply the saved theme and avoid a flash.
 * Inject it in <head> verbatim:
 *
 *   <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
 *
 * The rest of the theming lives in styles/app.css:
 *   :root                         -> light tokens + `color-scheme: light`
 *   @media (prefers-color-scheme: dark) :root:not([data-theme="light"])  -> dark tokens
 *   :root[data-theme="dark"]      -> dark tokens (manual toggle wins both ways)
 *
 * So the only state is the `data-theme` attribute on <html>: "" (follow OS),
 * "light", or "dark" — persisted in localStorage under `nm-theme`.
 */
export const THEME_KEY = "nm-theme";

export const THEME_INIT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t)document.documentElement.setAttribute("data-theme",t)}catch(e){}`;

export type Theme = "" | "light" | "dark";

/** Next theme when the toggle is pressed: light <-> dark, seeded from OS on first press. */
export function nextTheme(current: Theme): "light" | "dark" {
  if (current === "dark") return "light";
  if (current === "light") return "dark";
  return matchMedia("(prefers-color-scheme: dark)").matches ? "light" : "dark";
}

export function applyTheme(next: "light" | "dark") {
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {}
}

export function isDark(): boolean {
  const cur = document.documentElement.getAttribute("data-theme");
  return cur === "dark" || (cur === "" && matchMedia("(prefers-color-scheme: dark)").matches);
}
