# Designing against this app — the brief

Read this before proposing anything. The stylesheets in `assets/` tell you what
the app *looks* like; they cannot tell you what it *is*, what it already
decided, or what will fail its tests. That is what this file is for.

The real markup is `app/index.html` — every screen, verbatim from the shipping
build. Prefer reading it over inferring structure from the component cards.

## What it is

A **Tauri 2 desktop app** for operating a Discord bot. Vanilla TypeScript, no
framework, no bundler — `tsc` compiles `src-ts/` to plain ES modules. There is
no React, no JSX, no component runtime. A "component" here is a CSS class plus,
where it is dynamic, a function returning an HTML string.

Every screen's markup is **static in `index.html`** as `<section id="page-*"
class="page">`, toggled with `.active`. Nothing is routed or mounted.

## The six screens — these are the real ones

| id | eyebrow | `<h1>` | notes |
| --- | --- | --- | --- |
| `page-status` | `SYS // STATUS` | Bot Control | control card, 5 stat tiles, 2 canvas charts, quick actions, API failover |
| `page-chat` | `COMMS // AI CHAT` | AI Chat | conversation rail + transcript + composer |
| `page-logs` | `LOG // STREAM` | Log Viewer | uses `.page-header`, not `.page-title-bar` — it carries the LIVE chip, a level `<select>` and three buttons on the title row |
| `page-database` | `DATA // STORE` | Database Statistics | 4 stat tiles, Recent Channels, Top Users, Danger Zone |
| `page-history` | `ARCHIVE // AI HISTORY` | AI History | two panes: channel rail + transcript, with inline message editing |
| `page-settings` | `CFG // SETTINGS` | Settings | **8 stacked cards**, no sub-navigation — reached from the command palette instead (see below) |

**There are six, not five.** `Ctrl+1…6`. AI History is a real screen and is
easy to miss because no component card shows it whole.

There is also a seventh surface that is not a screen: the **command palette**
(`Ctrl+K`, `#command-palette`, `app/src/command-palette.ts`). It is a dialog, but
deliberately not shaped like the app's other dialogs — no titled header, no
button row, pinned to the upper third rather than centred, because it is a way
*in* rather than a question about the thing you were looking at. It lists every
non-destructive action in the app, fuzzy-ranked, with each command's existing
chord beside it.

It is also **the Settings page's missing sub-navigation**. That page is 3,023px
— 3.8 screens at the design height — so a `Settings: <section>` command is
generated for each of the eight cards, and running one switches to the page,
scrolls the card to the top of the reading column and moves focus to it. Two
things about those rows are worth knowing before proposing anything near them:
they are **read off the DOM at invocation time**, not listed (label from the
card's `h2`, glyph from the sprite that `h2` already references, search keywords
from every control caption in the card plus its hint) — so a card renamed or
added updates the palette by itself, and `tests-e2e/command-palette.spec.ts`
asserts the two sets are EQUAL rather than overlapping. Consequently a heading
change is a palette change, and a heading that named something destructive would
put it one Enter away.

`#page-chat` has a title bar but hides it *visually* (`position: absolute`, 1px)
so the transcript can take the full column; the `<h1>` stays in the
accessibility tree on purpose.

The stat tiles are fixed: Status shows **Uptime / Mode / Memory / Messages
(hero) / Channels**; Database shows **Total Messages (hero) / Active Channels /
Entities / RAG Memories**. There is no latency metric anywhere.

## Layers that are not in the CSS or the markup

This is the part a stylesheet cannot tell you, and the part most likely to make
a proposal wrong. Several of the things you actually see on this dashboard are
drawn by JavaScript and appear in no rule and no tag.

- **Sakura petals drift behind the whole app.** `#sakura-container` is a WebGL
  field driven by `app/src/sakura-model.ts` (~780 lines of petal physics), sitting
  under every screen and toggleable in Settings. It is the app's signature
  element, and the reason the surfaces above it are opaque tiles rather than
  glass: content has to stay readable over moving petals. **Anything proposed
  here is proposed on top of a live, animated background.**
- **The performance charts are canvas, not SVG or DOM.** `drawChart` in
  `app/src/app.ts` paints them, and it reads `--chart-line`, `--chart-line-2`,
  `--chart-grid`, `--chart-fill-top`, `--chart-fill-bot` and the tooltip tokens
  from the computed style **at draw time** — a deliberate CSS→JS contract, which
  is why `applyTheme()` repaints the charts when the theme flips. Consequence
  worth knowing: chart text is not in the DOM, so axe and every contrast tool
  score it `incomplete` and no automated guard covers it.
- **Toasts, skeletons and the confirm dialog are built at runtime**, not present
  in `index.html` — `showToast()`, `setSkeleton()` and `showConfirmDialog()` in
  `app/src/shared.ts`. So are the command palette's rows, which are rebuilt from
  scratch on every keystroke (`app/src/command-palette.ts`); the only markup in
  `index.html` is the dialog shell and its empty listbox.
- **Stat numerals count up.** `animateNumber()` in `shared.ts` tweens them on an
  ease-out-expo curve deliberately matched to the CSS easing token.
- **Chat content is rendered markdown**, not plain text: `app/src/chat/formatter.ts`
  plus KaTeX for equations and Prism for code, sanitised through DOMPurify. The
  vendor stylesheets for those load *after* `orbital.css` and do affect the
  render — Prism's `#2d2d2d` code background outranked the theme until it was
  pinned. Both are in `app/vendor/`.
- **The icon set is a `<symbol>` sprite** inlined at the top of `index.html`, 58
  glyphs, used as `<svg class="ic"><use href="#i-…"/></svg>`. Inner shapes carry
  no stroke or fill so the page CSS owns them. Those 58 are all there is.
- **Atmosphere in CSS**, for completeness, is `--aurora` (two radial washes) and
  `--grain` (a static fractal-noise data-URI), painted under the body washes.

## Hard constraints — these fail the build, not a review

- **No inline styles. At all.** The CSP is `style-src 'self'` with no
  `unsafe-inline`, declared in both `index.html` and `tauri.conf.json`. A
  `style="…"` attribute or a `<style>` block is silently dropped in the real
  app, and `tests-e2e/h7-csp.spec.ts` fails on any violation. Every proposal has
  to be expressible as rules in a stylesheet. *(This is the single most common
  way a good-looking proposal turns out to be unusable here.)*
  The one escape hatch: **the CSSOM is exempt.** CSP governs style attributes
  and `<style>` blocks at parse time, not `el.style.setProperty()` — which is
  how the thinking box reveals itself and how each data row gets its `--share`.
  So a design CAN take a per-element NUMBER from JS. What it cannot take is
  per-element *rules*: hand the stylesheet a custom property and let the rule
  do the drawing.
- **Never rename a token, class or id.** `orbital.css` states the rule: values
  change, names never do. `--accent-cyan` is the PRIMARY slot and holds sakura
  pink; `--accent-azure` is secondary and holds wisteria. Several tests couple
  to real class names deliberately.
- **No blue, cyan, teal or indigo, anywhere.** `upgrade-guards.spec.ts` scans
  every painted element on every page, both themes, all modals and toasts, and
  rejects any hue in **165–250°** (at s≥0.18, l≥0.10, a≥0.06).
- **`tests-e2e/ui-invariants.spec.ts` measures computed geometry** — ~50 tests
  covering stat-label baselines within 1px, `appearance: none` on every control,
  24×24 pointer targets, the sidebar watermark fitting the collapsed rail, one
  disabled-button treatment, distinct toast rails, and more. Layout changes meet
  it.
- **`tests-e2e/theme-parity.spec.ts` forbids a component from being two
  different shapes.** The two themes may differ in colour and in three named
  places in design (buttons, `kbd` chips, panel edges); they may not differ in
  border widths, radius, padding, weight, case or display. This exists because
  the same defect landed three times — `.stat-card`, `.chart-card` and
  `.data-item` each went on rendering their pre-audit design on dawn, because
  the base sheet writes dawn overrides as `html[data-theme="light"] .x` (0,2,0)
  and every later decision in `orbital.css` is a plain `.x` (0,1,0). Source
  order never gets consulted and the newer decision loses. **Do not answer this
  by restating a decision at higher specificity** — remove the stale override.
  A real intended divergence goes in the spec's `ACCEPTED_DIVERGENCE` list with
  its reason.
- **Korean branding stays.** Product name and window title are Korean
  (디스코드 봇 대시보드); UI copy is English with `lang="ko"` on each Korean
  string.

## Decisions already made — do not re-open without a reason

These were settled by audit (see `docs/DASHBOARD_UI_AUDIT.md` in the repo) and
re-proposing them is churn:

- **Headings have two tiers.** A heading either **names a thing** (display face,
  Title Case, `--step-2`; `--step-1` inside a modal) or **labels a group** (mono,
  UPPERCASE, `.14em`, `--step--1`). Body copy is never mono.
- **Corner ticks are a uniform, not decoration.** Exactly two surfaces wear
  them — `.control-card` and `.log-container` — and those two get the only real
  elevation. Everything else is a flat panel.
- **Empty states are one recipe at two scales**: panel scale gets the icon chip,
  in-list scale keeps the petal without it. Panel states fill and centre in the
  panel they report on.
- **Severity is signalled once**, by a left rail plus a faint row wash on the
  three that matter. Body text stays neutral. CRITICAL is the deliberate
  exception. `--sev-debug` is a muted neutral so the brand accent never means
  "debug".
- **Data rows are one ruled list**, not a stack of bordered cards; selection is
  a fill plus a left rail, because there is no border left to colour. Each row
  also carries a 2px proportion bar along its bottom edge, scaled linearly from
  `--share` (written per row through CSSOM). It is an underline and not a wash
  because the row's background is already spent on state — hover and selected
  sit at 10%/16% accent, so any fill faint enough to read behind the id lands in
  that same band and the busiest row looks permanently hovered.
- **The hero stat tile does not carry a bottom bar** — that bar is every other
  tile's hover state, and pinning it open made both metric strips read as tab
  bars.

## Responsive and density

`≤1100px` collapses the sidebar to a 64px icon rail (labels and shortcut chips
go, accessible names stay). `≤860px` stacks settings rows. `≤820px` stacks the
two-pane screens. The window minimum is **800×600** and is tested. Compact
density is `<html data-density="compact">`, which sets `--density: .7`; paddings
routed through `calc(var(--space-*) * var(--density))` follow it.

## Accessibility is load-bearing

Modals set `inert` on the app, move focus inside and restore it to the opener.
Conversation rows use roving `tabindex`. There are 13 live regions.
Reduced-motion is opt-in rather than opt-out. There are `forced-colors` blocks.
Contrast is pixel-sampled because axe returns `incomplete` on gradient-backed
surfaces. Three spec files enforce this. Do not propose anything that trades it
away.

## Where to look

- `app/index.html` — every screen, verbatim, plus the icon sprite
- `app/src/` — **the entire TypeScript source**, not a selection. Start with
  `app.ts` (bootstrap, page switching, theme, canvas charts), `shared.ts`
  (toasts, skeletons, icons, number tweening), `sakura-model.ts` (the petal
  field), and `chat/message-template.ts` + `chat/conversation-list.ts` for the
  two places dynamic markup is generated
- `app/vendor/` — the KaTeX and Prism sheets that load after the theme
- `app/assets/faust_avatar.jpg` — the default AI avatar
- `assets/orbital.css` — tokens and the current skin; its top comment is the
  brand statement and its `HEADING CONTRACT` comment is the type rule
- `assets/styles.css` — the older base sheet that `orbital.css` overrides by
  source order
- `components/`, `foundations/` — one card per component, rendering through the
  real cascade
