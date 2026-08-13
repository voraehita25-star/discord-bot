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
| `page-settings` | `CFG // SETTINGS` | Settings | **7 stacked cards**, no sub-navigation |

**There are six, not five.** `Ctrl+1…6`. AI History is a real screen and is
easy to miss because no component card shows it whole.

`#page-chat` has a title bar but hides it *visually* (`position: absolute`, 1px)
so the transcript can take the full column; the `<h1>` stays in the
accessibility tree on purpose.

The stat tiles are fixed: Status shows **Uptime / Mode / Memory / Messages
(hero) / Channels**; Database shows **Total Messages (hero) / Active Channels /
Entities / RAG Memories**. There is no latency metric anywhere.

## Hard constraints — these fail the build, not a review

- **No inline styles. At all.** The CSP is `style-src 'self'` with no
  `unsafe-inline`, declared in both `index.html` and `tauri.conf.json`. A
  `style="…"` attribute or a `<style>` block is silently dropped in the real
  app, and `tests-e2e/h7-csp.spec.ts` fails on any violation. Every proposal has
  to be expressible as rules in a stylesheet. *(This is the single most common
  way a good-looking proposal turns out to be unusable here.)*
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
  a fill plus a left rail, because there is no border left to colour.
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

- `app/index.html` — every screen, verbatim
- `app/chat/message-template.ts`, `app/chat/conversation-list.ts` — the two
  places dynamic markup is generated, if you need to know what a chat message or
  a conversation row is actually made of
- `assets/orbital.css` — tokens and the current skin; its top comment is the
  brand statement and its `HEADING CONTRACT` comment is the type rule
- `assets/styles.css` — the older base sheet that `orbital.css` overrides by
  source order
- `components/`, `foundations/` — one card per component, rendering through the
  real cascade
