# Dashboard UI audit

**Date:** 2026-08-14 · **Scope:** all 6 pages, 7 modals, both themes, 3 viewports, 2 densities
**Subject:** `native_dashboard/ui/` — Sakura Midnight (밤벚꽃) on ORBITAL bones

## Method

Captures come from two non-asserting Playwright specs writing to `test-results/screenshots/`:

- `tests-e2e/screenshots.spec.ts` — empty/offline state, seeded charts
- `tests-e2e/screenshots-audit.spec.ts` — **new**: populated state (bot online, 400 log lines, 1.2M messages, 12 channels) across both themes; the three modals with no baseline; the ≤1100px icon-rail collapse; the 800×600 window minimum; `data-density="compact"`; keyboard-focus and hover on the control row

Every capture was reviewed against one checklist: type voice · spacing on-ramp · button hierarchy · card treatment · empty-state recipe · focus state · both themes. Findings name the mechanism, not just the symptom, and each was re-checked against the running app before being acted on. Six did not survive that check and are recorded at the bottom rather than deleted.

**Not a finding:** the magenta blocks in `tests-e2e/visual-regression.spec.ts-snapshots/*.png` are Playwright's default mask fill over `.chart-card canvas` (`visual-regression.spec.ts:39`). Test artifact.

## Verdict

The identity is strong and the accessibility work is genuinely good — inert modals, focus restore, roving tabindex, live regions, reduced-motion, forced-colors, and pixel-sampled contrast that catches what axe returns `incomplete` on. Neither needed rescuing.

What the app lacked was **agreement between its screens**. The identity arrived in nine stacked override eras (`orbital.css` section headers read `Base-sheet parity` → `POLISH` → `v5 "BLOOM"` → `v6 "LANTERN"` → `v7 — THE AUDIT LAYER` → `v8 — THE SECOND AUDIT LAYER`), so each screen was fixed in its own pass and no pass could see the others. Two things follow from that, and both showed up in this audit: the same component ends up styled differently depending on what happens to contain it, and **a fix's stated intent and its actual effect drift apart** — three separate findings here turned out to be comments describing something the code no longer did.

The measurable root cause is that half the codebase does not use the design system it ships with:

| | `styles.css` (5,516 ln) | `orbital.css` (4,555 ln) |
| --- | --- | --- |
| `var(--space-*)` uses | **2** | 139 |
| `var(--step-*)` uses | **0** | 54 |
| radius-token uses | 7 | 69 |
| hardcoded px in padding/margin/gap | **283** | 65 |
| `transition:` literals (no token) | **53** | 1 |
| `!important` | 22 | 1 |

## Status

14 findings fixed, 6 withdrawn, 7 left open with reasons. All 177 non-visual e2e tests and 686 vitest cases pass after the changes.

---

## Fixed — High

### H1 · Empty states top-anchored in tall containers
`orbital.css` gave `.empty-state` `justify-content: center`, but the box was sized by its own padding and never stretched. Inside a container that *does* stretch — `.log-container` is `flex: 1` at ~650px — the ~200px box centred its own content and then sat at the top, leaving ~400px of dead space.
**Fixed:** `.empty-state` is `flex: 1`, and `.log-container` / `#log-content` get a flex column via `:has()` so that growth has something to act on. Scoped to the log panel: History and Chat already stretched their placeholders, and an invariant covers it.
**Note the trap:** the first attempt used `min-height: 100%`, which on the 800×600 History page resolved against an auto-height ancestor, grew the scroll height, and pushed the Undo button past a fully-scrolled viewport. Caught by `populated-a11y.spec.ts`. Growth belongs to the flex parent, never to a percentage against a parent with no height of its own.

### H2 · Log lines broke inside identifiers
`styles.css` set `word-break: break-all` on `#log-content`, so a 19-digit guild id came apart across the wrap and left orphan fragments (`789`, `6789`) alone on the next line. At 400 lines that was most of the screen.
**Fixed:** `word-break: normal` + `overflow-wrap: break-word`. A token only breaks when it alone cannot fit, so the id moves whole to the continuation line. The hanging indent that makes a continuation read as subordinate already existed further down the file.

### H3 · The log panel was a different product
`.log-container` was painted green-black (`rgba(7,13,11,.96)` → `rgba(5,9,8,.98)`) with a spring-green inset hairline and, in light, a warm-parchment cream gradient — a phosphor CRT and then a third palette, inside a sakura-plum deck. The largest "these are two apps" moment in the UI.
**Fixed:** the scanline texture stays — it says "terminal" without a borrowed palette to say it — on the same `--tile` every other panel is cut from.

### H4 · Severity was signalled three times, and one signal collided with the brand
Each level had a left rail *and* a tinted row background (`orbital.css`), while `styles.css` also coloured the line's text — turning every ERROR row into a paragraph of low-contrast red. Worse, `--sev-debug` was `var(--accent-cyan)`: the slot holding sakura pink, so the app's signature colour meant "debug".
**Fixed:** the rail (plus a faint wash on the three that matter) is the only signal; body text is neutral. CRITICAL keeps weight and colour as the deliberate exception. `--sev-debug` is now a muted plum-grey in both themes — the right rank for the least important level, and out of every other level's way.

### H5 · Light-theme cards had no edge
`--card-bg` resolved to `#ffffff → #faf3f5` on a `#f7eff0` page with `--edge` at 0.14 alpha and `--shadow-sm` a single 6%-alpha blur. Card boundaries were essentially invisible and the deck read as text floating on a wash.
**Fixed:** `--edge`/`--edge-strong` raised to 0.22/0.34 and the light shadow ramp given two layers (a tight contact shadow plus a soft ambient one). This is not "brighter"; it is what the two grounds allow — on `#0c0812` a panel separates by its own lift and the border finishes the shape, on near-white paper the border *is* the separation.

## Fixed — Medium

- **M1 · Two empty-state recipes on one screen.** The chat page showed `.no-conversations` (dashed frame + tinted fill) in the rail beside `.chat-empty` in the main pane, with `.empty-state` a third recipe elsewhere. The dashed frame also put a box inside a box — every host already carries a card border. **Fixed:** one language, two scales. The petal, the centring and the title/description hierarchy are shared; the icon chip is what marks the panel-scale state, and compact keeps the petal without it.
- **M2 · Body copy changed typeface by container.** `.empty-state p` set no `font-family`, and the Logs state renders inside `<pre id="log-content">`, which is `--font-mono`. The same component read in mono on Logs and sans on History — the mono version wrapping raggedly over two lines. **Fixed:** `.empty-state` declares `--font-ui`. **Rule adopted:** mono is for data and structural labels; body copy is never mono.
- **M3 · Five heading treatments in rotation.** Card titles (display, Title Case), section eyebrows (mono, UPPERCASE, .14em), page titles, modal titles (display, UPPERCASE, .03em) and Danger Zone (display, UPPERCASE, .05em, red). `--step-1` was defined but mapped to no role. **Fixed:** two tiers, documented as a `HEADING CONTRACT` comment in `orbital.css` — a heading either **names a thing** (TITLE) or **labels a group** (EYEBROW), and that is the whole rule. Modal titles are the TITLE tier one step down, which is the role `--step-1` now fills; Danger Zone is the TITLE tier in red.
- **M4 · Corner ticks meant "not selected" on the role card.** A prior era already disciplined this device for page panels (`FRAME DISCIPLINE` keeps brackets on `.control-card` and `.log-container` only). `.role-card` was missed: brackets were painted in every state and merely brightened on `.selected`, so the selected card's own glow washed them out and the **unselected** card was the one visibly wearing them. **Fixed:** brought under the existing discipline — selection is border + glow.
- **M5 · Two hand-tuned "small" button sizes.** `.btn-sm` (`6px 14px`, `.85em`, `8px` radius) and `.btn-small` (`4px 8px`, `.8rem`) — 2px and a unit apart, each hardcoded, one asserting a radius the token scale already owns. Too close to read as a deliberate second size, too far to be the same one. **Fixed:** both names kept (nothing is renamed here), both resolving to one rung of the ramp. The shared AI-History header `min-height` followed the button from 55px to 59px, exactly as its own comment said it would have to.
- **M6 · The hero stat tile read as a selected tab.** `.stat-card--hero::after` pinned open the bar that `.stat-card::after` uses for **hover**, so the hero permanently wore another tile's hover state — a lit background plus an accent underline in a row of flat cells is the grammar of a tab bar, and both metric strips read as one. **Fixed:** the bar is released; emphasis is the lit tile, the sakura glyph, and the accent on the numeral. Three signals that say "look at this number", none that say "this one is chosen".
- **M7 · Two empty conventions in one stat strip.** Status shipped `-` for uptime and mode beside `0` and `0 MB` for the other three, while the error path already used `—`. **Fixed:** all nine tiles start at `—`. A zero is a *value*, and claiming "0 messages" before the data arrives is a small lie.
- **M9 · Two label styles on adjacent fields.** `#role-select-label` is a `<p>`, so it fell outside `.modal-body label` and rendered sans/sentence-case with a trailing colon directly above `AI PROVIDER` in mono caps. **Fixed:** it takes the EYEBROW tier, and the colon went with the sentence.

## Fixed — Low

- **L1 · The sidebar watermark's comment described a bleed it does not perform.** A prior era retuned the sprig into texture and claimed it now bleeds off the rail edge. It does not: a 178px mask at `60% bottom` inside a 220px content box sits fully inside with ~25px to spare — and it must, because `ui-invariants.spec.ts` requires `mask-size ≤` rail width so the 64px collapsed strip never shows a severed branch. **Comment corrected, treatment left alone.**

---

## Open

Left undone deliberately, with the reason.

- **M10 · Database rows are cards pretending to be a table.** Each channel is a bordered card in a stack, and the right column mixes number and unit (`1 message` … `1,234,567 messages`), so right-aligning the string leaves the digits unaligned. `.data-item-value` already carries `tnum`, so rows of the same unit *do* align — only the singular row breaks the column. Truly aligning it needs the number split into its own span and a `subgrid` shared across rows, and `ui-invariants.spec.ts` measures the id↔count gap directly. The surgery is not proportionate to one misaligned row.
- **M11 · The settings form gutter does not adapt.** The label and control columns stay far apart down to 800px, where space is scarcest and `Display Name` is what gets squeezed (`min-window-settings.png`).
- **L2 · Voice drifts in empty-state copy.** `Start a new chat!` beside `Pick a channel on the left to view its AI chat history.` — one exclaims, the other instructs. `.no-conversations` also offers no action even though a NEW button sits above it.
- **L3 · Role cards have unbalanced text blocks** — one description fits a line, the other wraps to two, so the paired cards sit at different internal rhythms. Content-driven; needs a copy decision, not a CSS one.
- **L4 · Native textarea resize grabbers** are unstyled against a control set where everything else computes `appearance: none`.
- **L5 · `README.md:311-315` is stale by three re-skins** — still describes "Fluent Design inspired" and an "anime-style icon".
- **Token migration.** The 283 hardcoded px and 53 literal transitions in `styles.css` are the root cause in the table above and are still there. Worth doing, but note the trap this audit already hit twice: the tokens are fluid `clamp()` values, so swapping a fixed `14px` for `var(--step-0)` is a behaviour change at narrow widths, not a refactor. Spacing and transition literals substitute 1:1 and are the safe half; font sizes are not.

---

## Withdrawn on verification

Six first-pass findings did not survive checking. Recorded because the traps are easy to fall into again.

- **Light theme inverts the control row's emphasis.** *Actual:* the dark baseline had the bot **offline** and the light capture had it **online** — I compared two states, not two themes. Re-shot in dark with the bot running (`state-hover-restart.png`), STOP is the same solid red. The loud STOP is also correct: when the bot is running, stopping it is the only primary action available.
- **Chart ink is unreadable in light.** *Actual:* an artifact of viewing a full-page screenshot downscaled. At the cropped resolution (`charts-seeded-light.png`) the readouts are `--text-primary` `#231423` and the axis labels `--text-tertiary` `#69566f` — roughly 7:1 on the panel.
- **Modal chrome disagrees with itself.** *Claimed:* Rename has no close button, others do. *Actual:* a coherent rule — `.modal-small` dialogs (Rename, Delete) dismiss from the footer, larger content modals carry a `×`.
- **The chat page has no page title bar.** *Actual:* it has one; `#page-chat .page-title-bar` is *visually* hidden (`position: absolute`, 1px) so the flex column reclaims full height, while the `<h1>` stays in the a11y tree for `page-has-heading-one`. Deliberate, documented, and the right call for the most-used screen.
- **The Settings trash button is a different size from CHANGE.** *Actual:* `.btn-small` was never a size class in that pairing — it carries `.btn-danger` colour rules. The two buttons are the same height; only the shape differs, because one is icon-only.
- **The log container clips its last line.** *Actual:* `.log-container` has `padding: 20px`; the cut edge is just where the scroll viewport ends.

---

## Structural notes

- **The cascade is positional, not specific.** `orbital.css` wins over `styles.css` by link order alone. Comments in the file document repeated cascade bugs caused by exactly this. A dead rule added during this audit (a hanging indent already set 2,400 lines further down) was removed rather than left to become the tenth era.
- **Token names lie by design and must stay that way.** `--accent-cyan` holds sakura pink, `--accent-azure` holds wisteria; `orbital.css` states the rule — values change, names never do. `tests-e2e/non-text-contrast.spec.ts` couples to real class names on purpose.
- **93 tokens defined, 94 referenced** — one `var()` has no root definition.
- **`--space-7` is missing** from the ramp (4/8/12/16/24/32/—/48), which is why there is no 6px rung for a small button to land on.
- **Prism loads after `orbital.css`**, so `pre[class*=language-]{background:#2d2d2d}` outranks the theme's code surface. Already patched; still structurally fragile.
- **No component layer exists.** Components are class strings plus template-literal functions, so adding one means editing `index.html`, both stylesheets, and a TS template.

## What not to touch

The accessibility implementation and its test coverage. Inert modals with focus restore, roving tabindex over conversation rows, 13 live regions, reduced-motion as opt-in rather than opt-out, forced-colors blocks, and pixel-sampled contrast guards that exist because axe returns `incomplete` on gradient-backed surfaces. This is better than most shipping products, none of it is implicated above, and two of this audit's own regressions were caught by it.
