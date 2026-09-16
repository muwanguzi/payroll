# Next Media UI kit — for Next.js / React

The exact look of the Payroll app, ported off Django templates into a
framework-agnostic stylesheet + a small React shell. No Tailwind, no CSS-in-JS,
no build step for the styles — `app.css` is hand-written and self-contained.

```
nextjs-ui-kit/
├─ styles/app.css            the entire design system (tokens + components, light+dark)
├─ public/
│  ├─ fonts/                 Proxima Nova (400/600/800/900) + IBM Plex Mono 400
│  └─ next-media-logo.png    swap for your own mark
├─ lib/theme.ts              theme state helpers + the no-FOUC init script
├─ components/
│  ├─ Shell.tsx              sidebar + topbar + theme toggle (client component)
│  ├─ IconSprite.tsx         inline SVG <symbol> sheet — <use href="#i-…" />
│  └─ Toasts.tsx             optional toast system reusing .toast styles
└─ app/
   ├─ layout.tsx             root layout: imports app.css, injects theme script, mounts Shell
   └─ page.tsx               kitchen-sink gallery — delete after you've seen it
```

## Install (App Router)

1. **Copy** `styles/`, `public/fonts/`, `public/next-media-logo.png`, `lib/`,
   `components/` into your project (keep the relative layout, or fix the imports).
2. Your `app/layout.tsx` needs three things — see the example here:
   - `import "../styles/app.css";`
   - `<script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />` in `<head>`
   - `<html data-theme="" suppressHydrationWarning>` and `<Shell>` wrapping `{children}`
3. Edit the `NAV` array at the top of `components/Shell.tsx` to your routes, and the
   `<span className="tag">` / logo in the `.brand` block.
4. Pass your real session user: `<Shell user={{ name, role }} onSignOut={...}>`.
   Omit `user` on public pages to hide the sidebar footer + who-chip.

No dependencies beyond `next` / `react`. Works with the Pages Router too — put the
`THEME_INIT` script in `_document.tsx` and render `<Shell>` in `_app.tsx`.

## How theming works

State is a single attribute on `<html>`: `data-theme` = `""` (follow OS), `"light"`,
or `"dark"`, persisted in `localStorage["nm-theme"]`.

| Layer | Selector | Sets |
|---|---|---|
| light (default) | `:root` | light tokens + `color-scheme: light` |
| auto-dark | `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])` | dark tokens |
| forced dark | `:root[data-theme="dark"]` | dark tokens (manual toggle wins both ways) |

`color-scheme` is set per state so native controls — the `<input type="date">`
calendar icon, checkboxes, scrollbars — always match the active theme, even when the
manual toggle disagrees with the OS.

The `THEME_INIT` script runs before first paint so there's no flash. The toggle
button in `Shell.tsx` just flips the attribute and writes `localStorage`.

## Recolor it for your brand

Every color is a CSS custom property in the `:root` block (and mirrored in the two
dark blocks) at the top of `styles/app.css`. Change these and the whole UI follows:

```css
--accent: #0e7f8b;        /* primary action / active nav / links / focus ring   */
--accent-hover: #0a656f;
--brand-red: #d73c26;     /* the 3px top rule                                    */
--brand-dark: #0b2e38;
--bg: #f5f4ef;            /* app background (warm neutral)                       */
--surface: #ffffff;       /* cards, inputs, sidebar                              */
--ink: #0f1417;           /* body text                                          */
--good / --warn / --bad / --info  (+ matching -bg / -line)  /* status colours    */
```

Do the same substitution in the `@media (prefers-color-scheme: dark)` block and the
`:root[data-theme="dark"]` block. Fonts: replace the files in `public/fonts/` and the
`font-family` names in the `@font-face` rules + `--font-sans` / `--font-mono`.

## Class vocabulary

All defined in `app.css`. Plain elements — no JS needed except where noted.

**Layout** (provided by `<Shell>`, don't hand-roll)
`.app` `.sidebar` `.main` `.topbar` `.content` `.scrim` `.nav-open`
`.brand` `.nav-group > .label` `.nav-link[.active]` `.side-foot` `.who-chip` `.icon-btn`

**Page**
`.page-head` + `h1` + `p.sub` — standard page header
`.card` — white panel; `.card-head` with an `h2` for its title row
`.grid.c2` / `.c3` / `.c4` — responsive equal columns (collapse on narrow screens)

**Data**
`.stat` with `.l` (label) `.n` (number) `.f` (footnote); modifiers `.good` `.bad`
`.table-wrap` (or `.table-scroll`) wrapping `<table class="data">`; `th.num`/`td.num` right-align
`.pill` — status chip. Modifiers: `.neutral` `.info` `.warn` `.good`/`.ok` `.bad`,
  or pass a run-state name directly (`.DRAFT` `.CALCULATED` `.REVIEWED` `.APPROVED` `.DISBURSED`).
  `.pill.plain` drops the leading dot.
`.kv` — `<dl>` two-column key/value list
`.stepline` with `.step[.done|.now]` + `.dot`, separated by `.sep` — workflow progress
`.bar-track` > `.bar-fill` (set `style={{width}}`) — progress bar
`.empty` — centered empty-state text

**Forms**
`.form-grid` — 2-col field grid (1-col on mobile); `.f` wraps one `label` + control + optional `.help` / `.err`
`.field-label` — standalone uppercase label
`.toolbar` — inline filter row (`.grow` on the item that should stretch)
`.form-actions` — bottom button row with a top border

**Buttons** — `<button class="btn">`; modifiers `.ghost` `.subtle` `.warn` `.danger` `.sm`

**Feedback**
`.banner` (aka `.msg`) — inline callout; `.info` `.warning` `.error`
`.toasts` > `.toast` — fixed top-right stack; `.success` `.error` `.warning`
  (use `components/Toasts.tsx`, or add these classes to your existing toast lib's DOM)

**Auth page** (if you build one) — `.login-wrap` > `.login-card` > `.card`

## Laravel / Blade (server-rendered pages)

If part of the app is Blade rather than React, port `Shell.tsx`'s markup into
`resources/views/layouts/app.blade.php` and translate:

| React / this kit | Blade |
|---|---|
| `import "../styles/app.css"` | `@vite('resources/css/app.css')` (drop `app.css` in `resources/css/`) |
| `<Shell>{children}</Shell>` | `@yield('content')` inside the ported shell markup |
| `usePathname()` active check | `{{ request()->is('reports*') ? 'active' : '' }}` |
| `THEME_INIT` script | paste the same `<script>` string verbatim into `<head>` |
| toggle handler in `Shell.tsx` | paste the vanilla JS from the original `templates/base.html` (lines 132–159) |
| `<Toasts>` | `@foreach (session('flash', []) as $m) <div class="toast {{ $m['kind'] }}">…</div> @endforeach` |
| `IconSprite` | paste the `<svg width="0" height="0">…</svg>` block once at the top of `<body>` |

Fonts and `public/` assets work the same — Laravel serves `public/` at the web root,
so the `/fonts/...` paths in `app.css` resolve with no change.
