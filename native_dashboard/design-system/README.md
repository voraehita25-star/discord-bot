# Sakura Midnight — design system bundle

The Claude Design project at claude.ai/design that mirrors this dashboard's
component library, and the generator that builds it.

**Project:** `Sakura Midnight — Dashboard Design System`
(`74873e7d-2ce9-4965-8075-ecafd9f9da35`, type `PROJECT_TYPE_DESIGN_SYSTEM`)

## The one rule

**No preview restates the design.** Every card links the app's real
`ui/styles.css` and `ui/orbital.css` and inlines the app's real icon sprite, so
a card renders through the same cascade the dashboard does. Change a token and
the previews change with it.

That is not a nicety. The previous upload was made before the v5/v6/v7/v8
layers landed and its source was never checked in, so by the time anyone looked
at it, it documented a dashboard that no longer existed and there was nothing to
diff it against. Hand-authored previews drift silently; linked ones cannot.

What a spec in `build.mjs` actually owns is the **markup** a component is made
of, plus a sentence about why it is shaped that way. Both are short, and the
markup is the one thing a preview genuinely has to assert.

## Build

```powershell
node design-system/build.mjs      # from native_dashboard/
```

Writes `design-system/out/` (gitignored — **this repo's source of truth is
`build.mjs`, not its output**):

```
out/
  assets/         styles.css, orbital.css, preview.css, vendor/fonts/*.woff2
  components/     18 component cards + 2 dawn counterparts
  foundations/    4 foundation cards + 1 dawn counterpart
  _upload.json    project path -> local path, for the sync step
```

`out/` is also a working standalone preview. To click through it locally:

```powershell
python scripts/serve-ui.py 5199 design-system/out
```

## Sync

`DesignSync` requires `list_files` → `finalize_plan` → `write_files`, with
`localDir` set to `design-system/out` and every written path inside the plan.

```
finalize_plan  writes: assets/**, components/*.html, foundations/*.html
write_files    34 files, each { path, localPath } straight out of _upload.json
```

Upload `localPath` rather than inline data: the tool reads and encodes from disk
so 350 KB of CSS never passes through the model's context.

## Notes for whoever edits this next

- **Cards are indexed from the first line** of each preview:
  `<!-- @dsCard group="…" -->`. It must be line 1, before the doctype.
  `register_assets` is legacy and is not used here.
- **`@font-face` in `orbital.css` asks for `vendor/fonts/…` relative to
  itself**, which is why the typefaces are staged under `assets/vendor/fonts/`
  rather than at the project root.
- **`[data-theme]` is a root-only selector** in this codebase, so a theme cannot
  be scoped to a `<div>`. The only honest way to show dawn is a second page —
  hence the three `*-light.html` cards. They exist for the three places the two
  themes differ in *design* (colour, buttons, panel edges), not merely in hue.
- **Harness chrome is namespaced `.ds-`** and is deliberately thin. It also
  forces `h1` back to plain ink, because the app paints `h1` with the brand
  gradient and doc chrome must never wear a specimen colour.
- Every file is under the 256 KiB per-file cap — `orbital.css` is the largest at
  ~215 KB, so there is room but not a lot of it.
