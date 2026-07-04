Self-hosted UI typefaces (all woff2, loaded via @font-face in ui/orbital.css;
Content-Security-Policy is font-src 'self', so nothing may come from a CDN).

bricolage-grotesque.woff2  — Bricolage Grotesque (variable 200–800, Latin subset)
    The display typeface of the "Sakura Midnight v4 — Night-Blossom Deck" skin
    (--font-display: page titles, card/modal headings, hero metrics, logo).
    History: shipped originally as 'SakuraDisplay', was dark for one release
    (the ORBITAL v3 skin used Chakra Petch for display), revived in v4.
    License: SIL Open Font License v1.1 (OFL).
    Source:  https://github.com/ateliertriay/bricolage
    Vendored: cdn.jsdelivr.net/fontsource/fonts/bricolage-grotesque:vf@latest

chakra-petch-{400,500,600,700}.woff2 — Chakra Petch (static weights, Latin subset)
    The UI text face (--font-ui: buttons, nav, body chrome). Korean text falls
    back to Malgun Gothic / Noto Sans KR from the OS.
    License: OFL. Source: https://fonts.google.com/specimen/Chakra+Petch

jetbrains-mono.woff2 — JetBrains Mono (variable 100–800)
    The telemetry/mono face (--font-mono: stat numerals, eyebrows, timestamps,
    code, kbd chips).
    License: OFL. Source: https://github.com/JetBrains/JetBrainsMono

All faces fail gracefully to the system stack if a file is missing.
