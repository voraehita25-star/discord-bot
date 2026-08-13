/**
 * Build the Claude Design bundle for the Sakura Midnight design system.
 *
 * The point of this script is that NOTHING here restates the design. Every
 * preview links the app's real ui/styles.css + ui/orbital.css and inlines the
 * app's real icon sprite, so a card in the Design System pane renders through
 * the same cascade the dashboard does. Change a token in orbital.css and the
 * previews change with it — there is no second copy to keep in sync, which is
 * how the previous upload went stale three re-skins ago.
 *
 * What each spec below owns is the MARKUP a component is made of. That is the
 * one thing a preview genuinely has to assert, and it is short.
 *
 *   node design-system/build.mjs      (from native_dashboard/)
 *
 * Output lands in design-system/out/ (gitignored — this file is the source).
 * The upload map lives in out/_upload.json for the DesignSync step.
 */
import { readFileSync, writeFileSync, mkdirSync, rmSync, copyFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const OUT = join(HERE, 'out');

// ---------------------------------------------------------------------------
// The app's icon sprite, lifted verbatim so <use href="#i-…"> resolves offline.
// ---------------------------------------------------------------------------
const indexHtml = readFileSync(join(ROOT, 'ui/index.html'), 'utf8');
const spriteStart = indexHtml.indexOf('<svg id="orbital-sprite"');
const spriteEnd = indexHtml.indexOf('</defs></svg>', spriteStart);
if (spriteStart < 0 || spriteEnd < 0) throw new Error('icon sprite not found in ui/index.html');
const SPRITE = indexHtml.slice(spriteStart, spriteEnd + '</defs></svg>'.length);

// ---------------------------------------------------------------------------
// Harness chrome. Deliberately thin and namespaced under .ds- so it cannot be
// mistaken for — or collide with — anything the app ships.
// ---------------------------------------------------------------------------
const PREVIEW_CSS = `/* Design System pane harness. Not part of the app. */
html, body { height: auto; overflow: visible; }
body { padding: 28px; }
.ds-head { margin: 0 0 22px; }
.ds-head h1 {
    margin: 0 0 6px;
    font-family: var(--font-display);
    font-size: var(--step-2);
    font-weight: 700;
    letter-spacing: 0.01em;
    color: var(--text-primary);
    text-transform: none;
}
/* The app paints h1 with the brand gradient clipped to the text. Harness
   chrome must not wear a specimen colour, or the doc competes with the thing
   being documented — so this one is forced back to plain ink. */
.ds-head h1::after { content: none; }
.ds-head h1 { background: none; -webkit-text-fill-color: var(--text-primary); }
.ds-head p { margin: 0; max-width: 62ch; font-size: var(--step-0); color: var(--text-tertiary); }
.ds-set { display: flex; flex-direction: column; gap: 22px; }
.ds-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.ds-col { display: flex; flex-direction: column; gap: 12px; }
.ds-note {
    font-family: var(--font-mono);
    font-size: var(--step--1);
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--text-muted);
}
.ds-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 12px; }
.ds-swatch { border: 1px solid var(--edge); border-radius: var(--radius); overflow: hidden; background: var(--tile); }
.ds-swatch i { display: block; height: 54px; }
.ds-swatch b, .ds-swatch code { display: block; padding: 0 10px; font-weight: 500; }
.ds-swatch b { padding-top: 8px; font-size: var(--step--1); color: var(--text-secondary); }
.ds-swatch code { padding-bottom: 8px; font-family: var(--font-mono); font-size: var(--step--1); color: var(--text-muted); }
.ds-stage { padding: 18px; border: 1px solid var(--edge); border-radius: var(--radius-lg); background: var(--tile); }
`;

// ---------------------------------------------------------------------------
// Token helpers used by the foundations pages.
// ---------------------------------------------------------------------------
const swatch = (name) =>
    `<div class="ds-swatch"><i style="background: var(${name})"></i><b>${name.replace(/^--/, '')}</b><code>var(${name})</code></div>`;

const swatches = (names) => `<div class="ds-grid">${names.map(swatch).join('')}</div>`;

// ---------------------------------------------------------------------------
// The catalogue. `group` is the section label in the Design System pane.
// ---------------------------------------------------------------------------
const CARDS = [
    // ---- Foundations -------------------------------------------------------
    {
        path: 'foundations/colors.html', group: 'Foundations', name: 'Colour',
        subtitle: 'Canvas, text ramp, surfaces, accents, severity — both themes',
        title: 'Colour',
        blurb: 'Slot names are historical and never change: <code>--accent-cyan</code> is the PRIMARY slot and holds sakura pink; <code>--accent-azure</code> is the secondary and holds wisteria. Renaming them would orphan hundreds of references in styles.css, so values move and names stay put.',
        body: `
<div class="ds-set">
  <div><p class="ds-note">Canvas &amp; surfaces</p>${swatches(['--bg-primary', '--bg-secondary', '--bg-tertiary', '--surface-1', '--surface-2', '--surface-3', '--tile', '--tile-hi'])}</div>
  <div><p class="ds-note">Text ramp</p>${swatches(['--text-primary', '--text-secondary', '--text-tertiary', '--text-muted'])}</div>
  <div><p class="ds-note">Accents</p>${swatches(['--accent-cyan', '--accent-azure', '--accent-sakura', '--accent-green', '--accent-red', '--accent-orange'])}</div>
  <div><p class="ds-note">Edges &amp; focus</p>${swatches(['--edge', '--edge-strong', '--border-color', '--border-strong', '--border-focus'])}</div>
  <div><p class="ds-note">Severity — debug is a muted neutral on purpose, so the brand accent never means &ldquo;debug&rdquo;</p>${swatches(['--sev-critical', '--sev-error', '--sev-warn', '--sev-info', '--sev-debug'])}</div>
  <div><p class="ds-note">Brand gradients</p>${swatches(['--brand-grad', '--brand-soft', '--danger-grad', '--hairline'])}</div>
</div>`,
    },
    {
        path: 'foundations/typography.html', group: 'Foundations', name: 'Typography',
        subtitle: 'Three faces, two heading tiers, one fluid scale',
        title: 'Typography',
        blurb: 'A heading either <b>names a thing</b> (TITLE tier: display face, Title Case) or <b>labels a group</b> (EYEBROW tier: mono, uppercase, .14em). That is the whole rule. Body copy is never mono — inheriting monospace from a host <code>&lt;pre&gt;</code> is exactly how the Logs empty state used to read in a different typeface from the identical state on History.',
        body: `
<div class="ds-set">
  <div class="ds-stage ds-col">
    <p class="ds-note">Tier 1 — page</p>
    <div class="page-title-bar"><span class="page-eyebrow">SYS // STATUS</span><h1>Bot Control</h1></div>
  </div>
  <div class="ds-stage ds-col">
    <p class="ds-note">Tier 2 — TITLE · names a thing · display, Title Case, --step-2</p>
    <div class="settings-card"><h2>AI Appearance</h2><p>Customize how the AI looks in chat.</p></div>
  </div>
  <div class="ds-stage ds-col">
    <p class="ds-note">Tier 2 — EYEBROW · labels a group · mono, uppercase, .14em, --step--1</p>
    <div class="data-section"><h2>Recent Channels</h2><div class="data-item"><span class="data-item-id">123456789012345671</span><span class="data-item-value">42 messages</span></div></div>
  </div>
  <div class="ds-stage ds-col">
    <p class="ds-note">Scale — --step--1 … --step-4</p>
    <div style="font-family: var(--font-display); color: var(--text-primary)">
      <div style="font-size: var(--step-4)">--step-4 &nbsp;Display</div>
      <div style="font-size: var(--step-3)">--step-3 &nbsp;Stat numerals</div>
      <div style="font-size: var(--step-2)">--step-2 &nbsp;Card title</div>
      <div style="font-size: var(--step-1)">--step-1 &nbsp;Modal title</div>
      <div style="font-size: var(--step-0); font-family: var(--font-ui)">--step-0 &nbsp;Body copy, in the UI face</div>
      <div style="font-size: var(--step--1); font-family: var(--font-mono)">--step--1 &nbsp;Eyebrows, telemetry, timestamps</div>
    </div>
  </div>
</div>`,
    },
    {
        path: 'foundations/spacing-radius.html', group: 'Foundations', name: 'Spacing & radius',
        subtitle: '4 / 8 / 12 / 16 / 24 / 32 / 48 · three radii and a pill',
        title: 'Spacing &amp; radius',
        blurb: 'Note the gap: there is no <code>--space-7</code>, and no 6px rung at all. That absence is load-bearing — it is why two hand-tuned &ldquo;small&rdquo; button paddings (6px and 4px) existed side by side until they were folded onto 8px.',
        body: `
<div class="ds-set">
  <div><p class="ds-note">Space ramp</p><div class="ds-col">
    ${[1, 2, 3, 4, 5, 6, 8].map((n) => `<div class="ds-row"><span class="ds-note" style="width: 9ch">space-${n}</span><i style="display:block;height:14px;width:var(--space-${n});background:var(--brand-grad);border-radius:2px"></i></div>`).join('')}
  </div></div>
  <div><p class="ds-note">Radius</p><div class="ds-row">
    ${[['--radius-sm', '6px'], ['--radius', '10px'], ['--radius-lg', '14px'], ['--r-pill', '999px']].map(([t, v]) => `<div class="ds-stage" style="border-radius: var(${t}); text-align:center"><code style="font-family:var(--font-mono);font-size:var(--step--1);color:var(--text-secondary)">${t}<br>${v}</code></div>`).join('')}
  </div></div>
</div>`,
    },
    {
        path: 'foundations/elevation-motion.html', group: 'Foundations', name: 'Elevation & motion',
        subtitle: 'Shadow ramp, four named easings, three durations',
        title: 'Elevation &amp; motion',
        blurb: 'The shadow ramp is not one set of values tinted twice. On the midnight canvas a panel separates by its own lift and the border merely finishes the shape; on dawn&rsquo;s near-white paper the shadow all but vanishes and the border <i>is</i> the separation — so light carries a heavier edge and a two-layer shadow, and that is a different design, not a brighter one.',
        body: `
<div class="ds-set">
  <div><p class="ds-note">Elevation</p><div class="ds-row">
    ${['--shadow-sm', '--shadow-md', '--shadow-lg', '--shadow-glow'].map((t) => `<div class="ds-stage" style="box-shadow: var(${t})"><code style="font-family:var(--font-mono);font-size:var(--step--1);color:var(--text-secondary)">${t}</code></div>`).join('')}
  </div></div>
  <div><p class="ds-note">Easing — --ease-bounce keeps its overshoot; an invariant pins all four as distinct</p><div class="ds-col">
    ${['--ease', '--ease-smooth', '--ease-out-expo', '--ease-bounce'].map((t) => `<div class="ds-row"><span class="ds-note" style="width:18ch">${t.replace('--', '')}</span><code style="font-family:var(--font-mono);font-size:var(--step--1);color:var(--text-muted)">var(${t})</code></div>`).join('')}
  </div></div>
  <div><p class="ds-note">Duration</p><div class="ds-col">
    ${[['--dur-fast', '.14s'], ['--dur-base', '.22s'], ['--dur-slow', '.45s']].map(([t, v]) => `<div class="ds-row"><span class="ds-note" style="width:18ch">${t.replace('--', '')}</span><code style="font-family:var(--font-mono);font-size:var(--step--1);color:var(--text-muted)">${v}</code></div>`).join('')}
  </div></div>
</div>`,
    },

    // ---- Actions -----------------------------------------------------------
    {
        path: 'components/buttons.html', group: 'Actions', name: 'Buttons',
        subtitle: 'Primary / secondary / ghost / danger / warning, two sizes, icon-only',
        title: 'Buttons',
        blurb: '<code>.btn-sm</code> and <code>.btn-small</code> are two historical names for one size and now resolve to the same rung of the spacing ramp. Disabled state is deliberately one treatment across every variant — an invariant asserts all four control buttons resolve to a single background pair with no gradient.',
        body: `
<div class="ds-set">
  <div><p class="ds-note">Variants</p><div class="ds-row">
    <button class="btn btn-primary"><svg class="ic" aria-hidden="true"><use href="#i-play"/></svg> Start</button>
    <button class="btn btn-secondary"><svg class="ic" aria-hidden="true"><use href="#i-camera"/></svg> Change</button>
    <button class="btn"><svg class="ic" aria-hidden="true"><use href="#i-restart"/></svg> Restart</button>
    <button class="btn btn-warning"><svg class="ic" aria-hidden="true"><use href="#i-flask"/></svg> Dev</button>
    <button class="btn btn-danger"><svg class="ic" aria-hidden="true"><use href="#i-trash"/></svg> Clear All History</button>
  </div></div>
  <div><p class="ds-note">Sizes</p><div class="ds-row">
    <button class="btn btn-primary btn-large">Start Bot</button>
    <button class="btn btn-primary">New Conversation</button>
    <button class="btn btn-sm"><svg class="ic" aria-hidden="true"><use href="#i-restart"/></svg> Refresh</button>
    <button class="btn btn-icon" aria-label="Close"><svg class="ic" aria-hidden="true"><use href="#i-panel-left"/></svg></button>
    <button class="btn btn-danger btn-small" aria-label="Remove"><svg class="ic" aria-hidden="true"><use href="#i-trash"/></svg></button>
  </div></div>
  <div><p class="ds-note">Disabled — one treatment, whatever the variant</p><div class="ds-row">
    <button class="btn btn-primary" disabled>Start</button>
    <button class="btn btn-warning" disabled>Dev</button>
    <button class="btn btn-danger" disabled>Stop</button>
    <button class="btn" disabled>Restart</button>
  </div></div>
</div>`,
    },

    // ---- Panels ------------------------------------------------------------
    {
        path: 'components/hud-panel-card.html', group: 'Panels', name: 'Panel & corner ticks',
        subtitle: 'The card recipe, and the one device that is not decoration',
        title: 'Panel &amp; corner ticks',
        blurb: 'Corner ticks are a uniform, not an ornament. Exactly two surfaces wear them — <code>.control-card</code> (the bot you are controlling) and <code>.log-container</code> (the stream you are watching) — and those two also get the only real elevation. Everything else is a flat panel. Sprinkled on a minority at random, the device reads as noise; reserved for the page&rsquo;s instrument, it reads as information.',
        body: `
<div class="ds-set">
  <div><p class="ds-note">Instrument — ticks + elevation</p>
    <div class="control-card">
      <div class="control-info"><h2>Discord Bot</h2><span id="bot-status-text" class="status-badge online"><svg class="ic" aria-hidden="true"><use href="#i-pulse"/></svg> Online</span></div>
    </div>
  </div>
  <div><p class="ds-note">Plain panel — flat, no ticks, no hover lift</p>
    <div class="settings-card"><h2>Profile</h2><p>This information helps AI understand and remember you better.</p></div>
  </div>
</div>`,
    },
    {
        path: 'components/stat-card.html', group: 'Panels', name: 'Metric tiles',
        subtitle: 'The strip, the hero tile, and the empty convention',
        title: 'Metric tiles',
        blurb: 'The hero is told apart by a lit tile, a sakura glyph and an accent numeral. It deliberately does <i>not</i> carry the bottom bar: that bar is every other tile&rsquo;s hover state, and pinning it open under a lit background is the exact grammar of a selected tab — which is what made both metric strips read as tab bars. Empty is <code>—</code> everywhere; a zero is a value, and claiming &ldquo;0 messages&rdquo; before the data lands is a small lie.',
        body: `
<div class="stats-grid">
  <div class="stat-card"><div class="stat-label"><svg class="ic" aria-hidden="true"><use href="#i-pulse"/></svg> Uptime</div><div class="stat-value">17d 04:23:51</div></div>
  <div class="stat-card"><div class="stat-label"><svg class="ic" aria-hidden="true"><use href="#i-bolt"/></svg> Mode</div><div class="stat-value">PRODUCTION</div></div>
  <div class="stat-card"><div class="stat-label"><svg class="ic" aria-hidden="true"><use href="#i-graph"/></svg> Memory</div><div class="stat-value">512.8 MB</div></div>
  <div class="stat-card stat-card--hero"><div class="stat-label"><svg class="ic" aria-hidden="true"><use href="#i-chat"/></svg> Messages</div><div class="stat-value">1,234,567</div></div>
  <div class="stat-card"><div class="stat-label"><svg class="ic" aria-hidden="true"><use href="#i-network"/></svg> Channels</div><div class="stat-value">&mdash;</div></div>
</div>`,
    },
    {
        path: 'components/data-row.html', group: 'Panels', name: 'Data rows',
        subtitle: 'Section eyebrow + id/count rows, with the long-id case',
        title: 'Data rows',
        blurb: 'One ruled list, not eight cards in a box. Rows carried their own border, fill and radius inside an already-bordered section — a box in a box, and the last place that pattern survived here after the charts section gave it up. Rows are rules now; the section stays the panel, and ~9% more of a channel list fits (54px → 49px). Selection had to be re-said when the border went: it leaned on <code>border-color</code>, and a 1px bottom rule cannot carry &ldquo;this row is armed for deletion&rdquo;, so the fill stays and a left rail does the work — the same device the log viewer uses to rank a line. The count is <b>two</b> elements, not one string: rendered as &ldquo;1&nbsp;message&rdquo; beside &ldquo;1,234,567&nbsp;messages&rdquo; and right-aligned whole, the unit&rsquo;s own length decided where each row&rsquo;s digits landed. Reserved measures put every row&rsquo;s right edge within 1px of every other; <code>subgrid</code> was measured against this and rejected, because it needs <code>display: contents</code> on the value, which removes the box <code>ui-invariants</code> reads to prove a long id never crushes the count.',

        body: `
<div class="data-section">
  <h2>Recent Channels</h2>
  <div class="data-list">
    <div class="data-item"><span class="data-item-id">aVeryLongUnbrokenChannelIdentifier1234567890aVeryLongUnbroken</span><span class="data-item-value"><span class="data-item-count">1</span> <span class="data-item-unit">message</span></span></div>
    <div class="data-item"><span class="data-item-id">123456789012345671</span><span class="data-item-value"><span class="data-item-count">42</span> <span class="data-item-unit">messages</span></span></div>
    <div class="data-item"><span class="data-item-id">123456789012345672</span><span class="data-item-value"><span class="data-item-count">99,999</span> <span class="data-item-unit">messages</span></span></div>
    <div class="data-item"><span class="data-item-id">123456789012345673</span><span class="data-item-value"><span class="data-item-count">1,234,567</span> <span class="data-item-unit">messages</span></span></div>
  </div>
</div>`,
    },
    {
        path: 'components/danger-zone.html', group: 'Panels', name: 'Danger zone',
        subtitle: 'The one panel allowed a coloured border',
        title: 'Danger zone',
        blurb: 'Title tier in red — not a fifth heading style. The red border and the red fill already carry the warning; the heading used to shout a second time in caps, for exactly one heading in the whole app. The danger button&rsquo;s white label clears 4.5:1 against <i>every</i> stop of its gradient, resting and hover, which is pinned by a guard.',
        body: `
<div class="danger-zone">
  <h2><svg class="ic" aria-hidden="true"><use href="#i-alert"/></svg> Danger Zone</h2>
  <p>These actions are irreversible.</p>
  <button class="btn btn-danger"><svg class="ic" aria-hidden="true"><use href="#i-trash"/></svg> Clear All History</button>
</div>`,
    },

    // ---- Navigation --------------------------------------------------------
    {
        path: 'components/sidebar-nav.html', group: 'Navigation', name: 'Sidebar rail',
        subtitle: 'Logo, six nav items with shortcut chips, status pill, theme row',
        title: 'Sidebar rail',
        blurb: 'Below 1100px this collapses to a 64px icon strip — labels and shortcut chips go, accessible names stay. The sakura watermark shrinks or disappears with it: an invariant requires its mask to fit the rail, because a severed branch and a deliberate crop look identical from inside a computed style.',
        body: `
<div class="ds-stage" style="max-width: 300px; padding: 0">
  <nav class="sidebar" style="height: auto">
    <div class="logo"><span class="logo-icon"><svg class="ic" aria-hidden="true"><use href="#i-bot"/></svg></span><span lang="ko">봇 대시보드</span></div>
    <div class="nav-items">
      <button class="nav-item active"><span class="nav-icon"><svg class="ic" aria-hidden="true"><use href="#i-gauge"/></svg></span><span class="nav-label">Status</span><span class="shortcut">Ctrl+1</span></button>
      <button class="nav-item"><span class="nav-icon"><svg class="ic" aria-hidden="true"><use href="#i-chat"/></svg></span><span class="nav-label">AI Chat</span><span class="shortcut">Ctrl+2</span></button>
      <button class="nav-item"><span class="nav-icon"><svg class="ic" aria-hidden="true"><use href="#i-logs"/></svg></span><span class="nav-label">Logs</span><span class="shortcut">Ctrl+3</span></button>
      <button class="nav-item"><span class="nav-icon"><svg class="ic" aria-hidden="true"><use href="#i-database"/></svg></span><span class="nav-label">Database</span><span class="shortcut">Ctrl+4</span></button>
    </div>
    <div class="status-badge online"><svg class="ic" aria-hidden="true"><use href="#i-pulse"/></svg> Online</div>
    <button class="theme-toggle"><svg class="ic" aria-hidden="true"><use href="#i-moon"/></svg> Toggle Theme</button>
  </nav>
</div>`,
    },
    {
        path: 'components/page-title-bar.html', group: 'Navigation', name: 'Page title bar',
        subtitle: 'Mono eyebrow over a display h1 — the frame every page opens with',
        title: 'Page title bar',
        blurb: 'The eyebrow encodes where you are in the system, not decoration: <code>SYS</code>, <code>DATA</code>, <code>LOG</code>, <code>ARCHIVE</code>, <code>COMMS</code>, <code>CFG</code>. AI Chat is the one page that hides this bar visually so the transcript can take the full column — the <code>h1</code> stays in the accessibility tree.',
        body: `
<div class="ds-set">
  <div class="page-title-bar"><span class="page-eyebrow">SYS // STATUS</span><h1>Bot Control</h1></div>
  <div class="page-title-bar"><span class="page-eyebrow">DATA // STORE</span><h1>Database Statistics</h1></div>
  <div class="page-title-bar"><span class="page-eyebrow">ARCHIVE // AI HISTORY</span><h1>AI History</h1></div>
</div>`,
    },

    // ---- Forms -------------------------------------------------------------
    {
        path: 'components/inputs.html', group: 'Forms', name: 'Inputs',
        subtitle: 'Text, textarea, select, checkbox, toggle switch, range',
        title: 'Inputs',
        blurb: 'Every control computes <code>appearance: none</code> — an invariant sweeps the app for any that slipped back to OS chrome, and a second checks each select kept a drawn chevron after giving up the native one. The textarea was the last holdout: a resizable field keeps the platform&rsquo;s grabber whatever the stylesheet says, so the drag stays (these are long-form fields and people do pull them open) and the handle is redrawn as a grip in the app&rsquo;s own idiom — painted with a background gradient, the same technique the corner ticks use. Focus is a visible ring in both themes and under forced-colors.',
        body: `
<div class="ds-set">
  <div class="ds-stage ds-col">
    <div class="form-group"><label for="p-name">Conversation Name</label><input id="p-name" class="form-input" type="text" value="Sample Conversation"></div>
    <div class="form-group"><label for="p-about">About You</label><textarea id="p-about" class="setting-textarea" rows="3" placeholder="Tell AI about yourself (hobbies, work, interests…)"></textarea></div>
    <div class="form-group"><label for="p-sel">AI Provider</label><select id="p-sel" class="setting-select"><option>Gemini</option><option>Claude</option></select></div>
  </div>
  <div class="ds-stage ds-col">
    <label class="option-row"><span><svg class="ic" aria-hidden="true"><use href="#i-bolt"/></svg> Enable thinking mode</span><input type="checkbox" checked></label>
    <label class="option-row"><span>Compact density</span><span class="toggle-switch"><input type="checkbox" checked><span class="toggle-slider"></span></span></label>
  </div>
</div>`,
    },
    {
        path: 'components/settings-row.html', group: 'Forms', name: 'Settings row',
        subtitle: 'Caption beside field, until the measure runs out',
        title: 'Settings row',
        blurb: 'A caption column beside its field is a good shape while there is room for both. Below ~860px it stops paying for itself: at the 800&times;600 window minimum a fixed 200px caption is most of a 660px measure spent on a word, and &ldquo;Display Name&rdquo; was the label being squeezed by it. The row stacks there instead — what every form does when the measure runs out — and hands the 224px back to the control. The commit button sits at the fields&rsquo; right edge, which is where a form&rsquo;s commit belongs.',
        body: `
<div class="settings-card">
  <h2>Profile</h2>
  <div class="setting-row"><label class="setting-label" for="ds-dn">Display Name</label><input id="ds-dn" class="setting-input" type="text" value="TestUser"></div>
  <div class="setting-row"><label class="setting-label" for="ds-ab">About You</label><textarea id="ds-ab" class="setting-textarea" rows="3" placeholder="Tell AI about yourself (hobbies, work, interests…)"></textarea></div>
  <div class="setting-row"><label class="setting-label" for="ds-rf">Auto-refresh</label><select id="ds-rf" class="setting-select"><option>Every 5 seconds</option><option>Off</option></select></div>
  <div class="setting-row"><button class="btn btn-primary">Save Profile</button></div>
</div>`,
    },
    {
        path: 'components/role-card.html', group: 'Forms', name: 'Role cards',
        subtitle: 'A radiogroup rendered as cards — selected vs available',
        title: 'Role cards',
        blurb: 'Selection is a border and a bloom, and nothing else. These used to carry corner brackets in every state, brightening when chosen — but the chosen card&rsquo;s own glow washed its brackets out, so on screen the <i>unselected</i> card was the one visibly wearing them, and the app&rsquo;s &ldquo;this is the instrument&rdquo; device read as &ldquo;this is not chosen&rdquo;.',
        body: `
<div class="ds-stage">
  <p id="ds-role-label" class="ds-note">AI Role</p>
  <div class="role-cards" role="radiogroup" aria-labelledby="ds-role-label">
    <div class="role-card selected" role="radio" tabindex="0" aria-checked="true" aria-label="General Assistant">
      <div class="role-card-emoji"><svg class="ic" aria-hidden="true"><use href="#i-bot"/></svg></div>
      <div class="role-card-name">General Assistant</div><div class="role-card-desc">Helpful AI for general tasks</div>
    </div>
    <div class="role-card" role="radio" tabindex="-1" aria-checked="false" aria-label="Faust">
      <div class="role-card-emoji"><svg class="ic" aria-hidden="true"><use href="#i-ghost"/></svg></div>
      <div class="role-card-name">Faust</div><div class="role-card-desc">Sinner #2 from Limbus Company</div>
    </div>
  </div>
</div>`,
    },

    // ---- Feedback ----------------------------------------------------------
    {
        path: 'components/status-badge.html', group: 'Feedback', name: 'Badges & chips',
        subtitle: 'Status pill, live indicator, shortcut chips, tags',
        title: 'Badges &amp; chips',
        blurb: 'The LIVE indicator pulses its glow, never its opacity — a text element flickering to transparent fails non-text contrast at the trough, and a guard scans the keyframes for it.',
        body: `
<div class="ds-set">
  <div class="ds-row">
    <span class="status-badge online"><svg class="ic" aria-hidden="true"><use href="#i-pulse"/></svg> Online</span>
    <span class="status-badge"><svg class="ic" aria-hidden="true"><use href="#i-pulse"/></svg> Offline</span>
    <span class="live-indicator"><svg class="ic" aria-hidden="true"><use href="#i-pulse"/></svg> Live</span>
  </div>
  <div class="ds-row"><span class="shortcut">Ctrl+1</span><span class="shortcut">Ctrl+Enter</span><span class="shortcut">?</span></div>
</div>`,
    },
    {
        path: 'components/toast.html', group: 'Feedback', name: 'Toasts',
        subtitle: 'Four severities, each with its own left rail',
        title: 'Toasts',
        blurb: 'Every variant carries a distinct <code>border-left-color</code> at a non-zero width — asserted, because colour alone is not a signal and two severities resolving to the same rail is a silent failure. Toasts also sit above modals in the z-order, so a message raised by a dialog is never hidden behind it.',
        body: `
<div class="ds-col" style="max-width: 460px">
  <div class="toast toast-success"><svg class="ic" aria-hidden="true"><use href="#i-check"/></svg><span>Conversation renamed.</span></div>
  <div class="toast toast-info"><svg class="ic" aria-hidden="true"><use href="#i-info"/></svg><span>Reconnecting to the bot…</span></div>
  <div class="toast toast-warning"><svg class="ic" aria-hidden="true"><use href="#i-alert"/></svg><span>The bot is not running. Start it to use AI Chat.</span></div>
  <div class="toast toast-error"><svg class="ic" aria-hidden="true"><use href="#i-alert"/></svg><span>Could not save the avatar. The file is larger than 8 MB.</span></div>
</div>`,
    },
    {
        path: 'components/empty-state.html', group: 'Feedback', name: 'Empty states',
        subtitle: 'One language, two scales — panel and in-list',
        title: 'Empty states',
        blurb: 'Panel scale gets the icon chip; in-list scale keeps the petal and drops it. They used to be different <i>devices</i> — a dashed, tinted frame versus an illustrated block — and on the chat page both are on screen at once, rail beside main pane, which is where that read as two products. The panel state also fills the panel it reports on rather than its own padding box, so it centres in a tall container instead of sitting at the top of it.',
        body: `
<div class="ds-set">
  <div><p class="ds-note">Panel scale</p><div class="ds-stage" style="min-height: 260px; display: flex">
    <div class="empty-state">
      <svg class="ic" aria-hidden="true"><use href="#i-logs"/></svg>
      <h3>No logs found</h3><p>Logs will appear here once the bot starts running.</p>
    </div>
  </div></div>
  <div><p class="ds-note">In-list scale</p><div class="ds-stage" style="max-width: 280px">
    <div class="no-conversations"><p>No conversations yet</p><p>Use New above to start one.</p></div>
  </div></div>
</div>`,
    },
    {
        path: 'components/skeleton.html', group: 'Feedback', name: 'Loading states',
        subtitle: 'Skeleton rows and the spinner',
        title: 'Loading states',
        blurb: 'A panel mid-load centres its spinner the same way a panel standing empty centres its placeholder — both are asserted, because a spinner pinned to the top-left of a 600px pane reads as a broken layout rather than as work in progress.',
        body: `
<div class="ds-set">
  <div class="ds-stage ds-col">
    <div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>
  </div>
  <div class="ds-stage" style="min-height: 140px; display: grid; place-items: center">
    <div class="loading-spinner"></div>
  </div>
</div>`,
    },

    // ---- Surfaces ----------------------------------------------------------
    {
        path: 'components/modal.html', group: 'Surfaces', name: 'Modal',
        subtitle: 'Header, body, footer — and when a close button appears',
        title: 'Modal',
        blurb: 'The title is the card-title tier one step down (<code>--step-1</code>), Title Case — not a heading style of its own. Small confirm dialogs dismiss from the footer; larger content modals also carry a <code>×</code>. Opening one marks the app <code>inert</code>, moves focus inside, and restores it to the opener on close.',
        body: `
<div class="ds-stage" style="display: grid; place-items: center; min-height: 320px">
  <div class="modal-content" style="position: static; max-width: 420px; width: 100%">
    <div class="modal-header"><h2><svg class="ic" aria-hidden="true"><use href="#i-pencil"/></svg> Rename Conversation</h2></div>
    <div class="modal-body"><div class="form-group"><label for="ds-rename">Conversation Name</label><input id="ds-rename" class="form-input" type="text" value="Sample Conversation"></div></div>
    <div class="modal-footer"><button class="btn">Cancel</button><button class="btn btn-primary">Rename</button></div>
  </div>
</div>`,
    },
    {
        path: 'components/log-viewer.html', group: 'Surfaces', name: 'Log viewer',
        subtitle: 'Severity rails, hanging indent, scanline surface',
        title: 'Log viewer',
        blurb: 'Severity is signalled once — a left rail, plus a faint row wash on the three that matter. The body text stays neutral: colouring whole lines made the levels easier to spot and the <i>messages</i> harder to read, which is backwards for a log viewer. CRITICAL is the deliberate exception. The panel keeps its scanline texture but is cut from the same <code>--tile</code> as every other surface, rather than the green phosphor it used to be.',
        body: `
<div class="log-container" style="height: 260px; overflow: auto">
  <pre id="log-content"><div class="log-line info">2026-07-25 09:00:12,345 - discord.client - INFO - Heartbeat ack, latency 42.1ms shard=0 guild=1234567890123456789</div><div class="log-line warning">2026-07-25 09:01:12,345 - discord.client - WARNING - Rate limit bucket exhausted, retrying in 1.2s</div><div class="log-line error">2026-07-25 09:02:12,345 - discord.client - ERROR - Gateway closed unexpectedly (code 4008)</div><div class="log-line critical">2026-07-25 09:03:12,345 - bot - CRITICAL - Unrecoverable: database file is locked, shutting down</div><div class="log-line debug">2026-07-25 09:04:12,345 - discord.gateway - DEBUG - Keeping shard 0 alive with sequence 91422</div></pre>
</div>`,
    },

    // ---- Chat --------------------------------------------------------------
    {
        path: 'components/chat-bubbles.html', group: 'Chat', name: 'Messages',
        subtitle: 'User and assistant turns, with markdown and code',
        title: 'Messages',
        blurb: 'Bubbles size to their content rather than to a fixed column. Code fences share one surface in both themes — Prism&rsquo;s stylesheet loads after the theme and its own <code>#2d2d2d</code> background used to win, so an invariant checks both fences in one message resolve to <code>--code-bg</code>.',
        body: `
<div class="ds-stage ds-col">
  <div class="chat-message user"><div class="message-avatar"><svg class="ic" aria-hidden="true"><use href="#i-user"/></svg></div>
    <div class="message-wrapper"><div class="message-header"><span class="message-name">User</span><span class="message-time">12:34</span></div>
      <div class="message-content">What changed in the deploy last night?</div></div></div>
  <div class="chat-message assistant"><div class="message-avatar"><svg class="ic" aria-hidden="true"><use href="#i-bot"/></svg></div>
    <div class="message-wrapper"><div class="message-header"><span class="message-name">Faust</span><span class="message-time">12:34</span></div>
      <div class="message-content"><p>Three things landed:</p><ul><li>the retry budget moved to the client</li><li>the log shipper switched to batched writes</li><li>the health probe now fails closed</li></ul><pre><code class="language-python">def probe():
    return db.ping()</code></pre></div></div></div>
</div>`,
    },
    {
        path: 'components/chat-input-bar.html', group: 'Chat', name: 'Composer',
        subtitle: 'Options row and textarea reading as one object',
        title: 'Composer',
        blurb: 'The option toggles and the textarea share a single rounded surface. Split across two bands by a full-width rule, the toggles read as page chrome rather than as part of the message you are about to send. The Stop button takes the Send slot exactly — same box, so the composer does not reflow mid-turn.',
        body: `
<div class="ds-stage" style="padding: 0">
  <div class="chat-input-area">
    <div class="chat-input-options">
      <label class="option-row"><input type="checkbox"> <span>Search</span></label>
      <label class="option-row"><input type="checkbox"> <span>Write</span></label>
    </div>
    <div class="chat-input-container">
      <button class="btn btn-attach" aria-label="Attach"><svg class="ic" aria-hidden="true"><use href="#i-paperclip"/></svg></button>
      <textarea id="ds-chat-input" class="chat-input" rows="1" placeholder="Message the AI…"></textarea>
      <button class="btn btn-send" aria-label="Send"><svg class="ic" aria-hidden="true"><use href="#i-bolt"/></svg></button>
    </div>
  </div>
</div>`,
    },
    {
        path: 'components/conversation-row.html', group: 'Chat', name: 'Conversation rail',
        subtitle: 'Panel header, filter, rows with tags and meta',
        title: 'Conversation rail',
        blurb: 'This rail and the AI-History rail are the same object — a titled list with one action — and they wear the same panel header, on the same baseline, at a shared min-height. They sit side by side across a page seam the eye follows, so a few pixels of disagreement between them is legible as a defect.',
        body: `
<div class="ds-stage" style="max-width: 300px; padding: 0">
  <div class="chat-sidebar-header"><h2>Conversations</h2><button class="btn btn-primary btn-sm"><svg class="ic" aria-hidden="true"><use href="#i-plus"/></svg> New</button></div>
  <div style="padding: 12px"><input class="form-input" type="search" placeholder="Filter conversations…"></div>
  <div class="conversation-list">
    <div class="conversation-item active"><div class="conv-title">Deploy postmortem</div><div class="conv-meta">12 messages · 2h ago</div></div>
    <div class="conversation-item"><div class="conv-title">RAG index rebuild</div><div class="conv-meta">4 messages · yesterday</div></div>
  </div>
</div>`,
    },
];

// ---------------------------------------------------------------------------
// Emit.
// ---------------------------------------------------------------------------
// Dawn (light) counterparts. `[data-theme]` is a root-only selector in this
// codebase, so a theme cannot be scoped to a <div> — the only honest way to
// show both is a second page per card. Only the three where the two themes
// genuinely differ in DESIGN rather than in hue get one.
const LIGHT_OF = ['foundations/colors.html', 'components/buttons.html', 'components/hud-panel-card.html'];
for (const src of LIGHT_OF) {
    const base = CARDS.find((c) => c.path === src);
    CARDS.push({
        ...base,
        path: base.path.replace(/\.html$/, '-light.html'),
        theme: 'light',
        name: `${base.name} — dawn`,
        title: `${base.title} <span style="opacity:.55">· dawn</span>`,
        subtitle: `${base.subtitle} · light theme`,
    });
}

// ---------------------------------------------------------------------------
// PROPOSALS — the one place a card is allowed its own stylesheet.
//
// Every card above links the app's real CSS and nothing else, which is what
// stops the system drifting from the app. The cost of that rule is that a spec
// card can only ever show what already ships, so there is nowhere to look at an
// idea before committing to it.
//
// A proposal card links the real CSS AND one override file, and every override
// is scoped under `.p-<variant>` so the SAME page can show what ships directly
// above what is being suggested. The override file is therefore not a mockup —
// it is the patch. Approve a variant and its rules move into orbital.css
// unchanged; reject it and one file is deleted and nothing else was touched.
//
// These live in their own `Proposals` group so nobody mistakes one for the spec.
// ---------------------------------------------------------------------------
const PROPOSALS = [];

const page = (card) => `<!-- @dsCard group="${card.group}" -->
<!doctype html>
<html lang="en" data-theme="${card.theme || 'dark'}">
<head>
<meta charset="utf-8">
<title>${card.title}</title>
<link rel="stylesheet" href="../assets/styles.css">
<link rel="stylesheet" href="../assets/orbital.css">
<link rel="stylesheet" href="../assets/preview.css">${card.css ? `
<link rel="stylesheet" href="${card.path.replace(/^proposals\/(.+)\.html$/, '$1.css')}">` : ''}
</head>
<body>
${SPRITE}
<header class="ds-head"><h1>${card.title}</h1><p>${card.blurb}</p></header>
${card.body}
</body>
</html>
`;

rmSync(OUT, { recursive: true, force: true });
mkdirSync(join(OUT, 'components'), { recursive: true });
mkdirSync(join(OUT, 'foundations'), { recursive: true });
mkdirSync(join(OUT, 'assets/vendor/fonts'), { recursive: true });
mkdirSync(join(OUT, 'proposals'), { recursive: true });
writeFileSync(join(OUT, 'assets/preview.css'), PREVIEW_CSS, 'utf8');

CARDS.push(...PROPOSALS);
for (const card of CARDS) {
    writeFileSync(join(OUT, card.path), page(card), 'utf8');
    // A proposal's stylesheet IS the patch it is proposing — written beside the
    // page it demonstrates, so approving one is a copy-paste into orbital.css.
    if (card.css) {
        writeFileSync(join(OUT, card.path.replace(/\.html$/, '.css')), card.css, 'utf8');
    }
}

// Stage the app's own CSS and typefaces next to the previews. Copies, not
// edits: the build regenerates them from ui/ every run, so out/ is a working
// standalone preview (serve it and click through) AND the whole upload reads
// from one directory. @font-face in orbital.css asks for 'vendor/fonts/…'
// relative to itself, which is why the fonts land under assets/.
const FONTS = ['bricolage-grotesque', 'chakra-petch-400', 'chakra-petch-500',
    'chakra-petch-600', 'chakra-petch-700', 'jetbrains-mono'];
copyFileSync(join(ROOT, 'ui/styles.css'), join(OUT, 'assets/styles.css'));
copyFileSync(join(ROOT, 'ui/orbital.css'), join(OUT, 'assets/orbital.css'));
for (const f of FONTS) {
    copyFileSync(join(ROOT, `ui/vendor/fonts/${f}.woff2`), join(OUT, `assets/vendor/fonts/${f}.woff2`));
}

// The DesignSync step reads this: project path -> path on disk, relative to
// design-system/out (the localDir the plan is finalized against).
const upload = [
    { path: 'assets/styles.css', localPath: 'assets/styles.css' },
    { path: 'assets/orbital.css', localPath: 'assets/orbital.css' },
    { path: 'assets/preview.css', localPath: 'assets/preview.css' },
    ...FONTS.map((f) => ({ path: `assets/vendor/fonts/${f}.woff2`, localPath: `assets/vendor/fonts/${f}.woff2` })),
    ...CARDS.map((c) => ({ path: c.path, localPath: c.path })),
    ...CARDS.filter((c) => c.css).map((c) => {
        const p = c.path.replace(/\.html$/, '.css');
        return { path: p, localPath: p };
    }),
];
writeFileSync(join(OUT, '_upload.json'), JSON.stringify({ upload, cards: CARDS.map(({ path, group, name, subtitle }) => ({ path, group, name, subtitle })) }, null, 2), 'utf8');

console.log(`wrote ${CARDS.length} previews + assets -> design-system/out/`);
console.log(`upload map: ${upload.length} files`);
