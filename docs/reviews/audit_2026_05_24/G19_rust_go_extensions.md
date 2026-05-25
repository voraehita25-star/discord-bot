# G19: Rust Extensions + Go Services — Re-Audit Report

Audit date: 2026-05-24
Auditor: Claude (Opus 4.7, 1M context) — senior code auditor, READ-ONLY
Scope: PyO3-bound Rust extensions (`media_processor`, `rag_engine`) and Go microservices
(`url_fetcher` = SSRF-sensitive, `health_api`). Re-audit of prior pass under
`docs/reviews/audit_2026_05/` (G13_rust_go_services.md, MASTER_TABLE H48/H49).

## Files reviewed (every line, working-tree content)

| File | Lines | Notes |
|---|---|---|
| `rust_extensions/Cargo.toml` | 24 | Workspace manifest (pyo3 0.28, rayon 1.11, bytemuck declared) |
| `rust_extensions/README.md` | 202 | Build doc |
| `rust_extensions/media_processor/Cargo.toml` | 26 | image 0.25 (jpeg/png/gif/webp), base64 0.22 |
| `rust_extensions/media_processor/media_processor.pyi` | 42 | Type stub |
| `rust_extensions/media_processor/src/lib.rs` | 302 | PyO3 entry, MediaProcessor + ImageData, bomb check |
| `rust_extensions/media_processor/src/encode.rs` | 57 | base64 |
| `rust_extensions/media_processor/src/errors.rs` | 21 | MediaError |
| `rust_extensions/media_processor/src/gif.rs` | 205 | GIF animation detection / frame count |
| `rust_extensions/media_processor/src/resize.rs` | 195 | Resize (Fit/Fill/Stretch) |
| `rust_extensions/rag_engine/Cargo.toml` | 35 | simsimd 6.5, memmap2; fs2 dropped |
| `rust_extensions/rag_engine/rag_check.txt` | ~10 | `cargo check` output transcript (Finished, builds clean) |
| `rust_extensions/rag_engine/rag_engine.pyi` | 39 | Type stub |
| `rust_extensions/rag_engine/src/cosine.rs` | 159 | SIMD/scalar cosine |
| `rust_extensions/rag_engine/src/errors.rs` | 21 | RagError |
| `rust_extensions/rag_engine/src/index.rs` | 212 | Keyword inverted index (VectorIndex) |
| `rust_extensions/rag_engine/src/lib.rs` | 482 | PyO3 entry, RagEngine, save/load (fsync) |
| `rust_extensions/rag_engine/src/storage.rs` | 444 | Memory-mapped binary vector storage |
| `go_services/go.mod` | 27 | Go 1.25.0; chi 5.2.5; prometheus 1.23.2; x/net 0.53.0 |
| `go_services/go.sum` | 93 | Checksums |
| `go_services/README.md` | 299 | Service doc |
| `go_services/health_api/main.go` | 626 | Prometheus + health, bearer auth |
| `go_services/url_fetcher/main.go` | 640 | URL fetcher with SSRF guards |

Cross-referenced: `rust_extensions/Cargo.lock` (resolved versions), benches
(`rag_bench.rs`, `media_bench.rs`), and the Python wrapper
`cogs/ai_core/memory/rag_rust.py` to confirm which Rust symbols are reachable
from production.

## Severity-count summary

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 6 |
| LOW | 17 |
| INFO | 12 |
| **Total** | **35** |

Prior HIGHs H48 (rag save fsync) and H49 (health_api bind/auth) are both
substantially fixed — see Prior column. No new CRITICAL/HIGH found. The
remaining items are robustness, dead-code, dependency-hygiene, and
defense-in-depth gaps.

## Findings

| File | Line(s) | Severity | Category | Issue | Prior | Suggested fix |
|---|---|---|---|---|---|---|
| `rag_engine/src/lib.rs` | 311-325, 328-360 | INFO | Durability (fsync) | **H48 FIXED-VERIFIED.** Temp file is now created via `File::create`, `write_all`, then `f.sync_all()` (line 323) before rename; the copy-fallback path also re-opens the destination and `sync_all()`s it (line 338). The data-durability hole is closed. Residual: the *directory* entry created by `rename` is not itself fsynced, so on a hard power loss the rename can be lost (file reverts to old content) — but never truncated/empty. This is a strictly weaker failure than H48 described. | H48 (G13 lib.rs:283-329) | Optional: open the parent dir and `sync_all()` it after rename for full rename durability. |
| `health_api/main.go` | 238-262, 380-381, 384-561 | INFO | AuthN | **H49 (auth half) FIXED-VERIFIED.** All write endpoints (`/health/service`, `/metrics/push`, `/metrics/batch`) are now wrapped in `r.Group` with `requireBearerToken`. Auth fails CLOSED when `HEALTH_API_TOKEN` is unset (line 241-244, returns 503), uses constant-time compare with length guard (line 255). Strong fix. | H49 (G13 254-260) | None for writes. See next row for the read-endpoint residual. |
| `health_api/main.go` | 289-295, 337, 564-571 | MEDIUM | Info leak / bind | **H49 (bind half) PARTIALLY-FIXED.** Default bind is still `127.0.0.1`, but `GO_HEALTH_API_HOST=0.0.0.0` env override still exists (lines 289-295) and `/metrics` (337) + `/stats` (564) are read-only handlers OUTSIDE the auth Group. Bound to 0.0.0.0 they expose Go runtime internals (goroutine count, `go_memstats_*`, GC, MemStats via `/stats`) with no auth. Writes are protected now, but process-internal info still leaks if an operator flips the host knob. | H49 (G13 290) | Either gate `/metrics` + `/stats` behind the same bearer token, or hard-bind to 127.0.0.1 and remove the `*_HOST` env vars, or document loudly that 0.0.0.0 is unsupported. |
| `rust_extensions/Cargo.toml` | 22 | LOW | Dependency hygiene | `bytemuck = { version = "1.14", features=["derive"] }` is declared as a workspace dep and pulled into `rag_engine` (rag_engine/Cargo.toml:19), but **no code uses `bytemuck::`** — storage.rs was rewritten to explicit `to_le_bytes`/`from_le_bytes` (the only `bytemuck` mentions are in comments at storage.rs:147,389 describing the *removed* code). It is still pulled transitively by `simsimd` (Cargo.lock), so removing the direct decl is free. | G13 Cargo.toml:15 (STILL-PRESENT) | Remove `bytemuck` from `[workspace.dependencies]` and from `rag_engine/Cargo.toml`. |
| `rag_engine/src/storage.rs` | whole file (esp. 113) | MEDIUM | Dead code / unsafe surface | `VectorStorage` (incl. the `unsafe { MmapOptions::new().map_mut(&file) }` at line 113) is only `pub use`'d at lib.rs:20 and **never instantiated** by `RagEngine` (which stores `HashMap<String,MemoryEntry>`). The Python wrapper `rag_rust.py` calls only `add/add_batch/search/save/load` — never `open()`. Benches use only `cosine_similarity`. So the entire memory-mapped store, the `unsafe` mmap, and the SIGBUS-on-truncation risk are **unreachable from production and tests**. Carrying an unexercised `unsafe` block is a latent footgun if a future caller wires it up without re-review. | G13 storage.rs:98 (mmap UB) — now effectively unreachable; STILL-PRESENT as dead code | Delete `storage.rs` (and the `pub use`), or add a `#[cfg(feature=...)]` gate + tests if it is intended for future use. |
| `rag_engine/src/index.rs` | whole file | MEDIUM | Dead code | `VectorIndex` is `pub use`'d at lib.rs:21 but never instantiated in `RagEngine`; no Python path or bench reaches keyword search. ~212 lines of untested logic (free-slot reuse, reverse-keyword map) with no callers. The code quality is improved vs the prior pass, but it remains dead. | G13 index.rs n/a (STILL-PRESENT) | Wire into `RagEngine` (expose keyword filtering) or delete the module. |
| `rag_engine/src/lib.rs` | 25, 52 | INFO | PyO3 attr (prior false alarm) | `#[pyclass(from_py_object)]` on `MemoryEntry`/`SearchResult` (and ImageData at media_processor lib.rs:25). The prior audit suspected this was "not a real PyO3 attribute / a typo." It **is** a valid PyO3 0.28 option (opt into a generated `FromPyObject` for the pyclass; see PyO3 issue #4337) and `rag_check.txt` shows the crate compiles. It is load-bearing here: `RagEngine::add(entry: MemoryEntry)` and `batch_resize(images: Vec<...>)` take pyclass values by `FromPyObject`. | G13 lib.rs:25,52 + media lib.rs:25 (RESOLVED — prior concern was incorrect) | No action. Optionally add a code comment explaining the attribute so it isn't "cleaned up" later. |
| `rag_engine/src/lib.rs` | 145-160 | MEDIUM | Silent skip | `add_batch` still silently drops entries that fail validation (wrong dim, non-finite importance/embedding) and returns only the success count. A caller passing 1000 entries that all mismatch dim gets `Ok(0)` with no indication of *why*. Memory-management code should fail loud or report failures. | G13 lib.rs:145-160 (STILL-PRESENT) | Return a `(added, skipped)` tuple or log skipped IDs; the single-entry `add` (line 118) already raises, so the batch path is inconsistent. |
| `rag_engine/src/lib.rs` | 455-459 | LOW | Telemetry | `load()` rejects only the all-invalid case ("no entries matched dimension"). A file with 1 valid + N invalid entries silently drops the N with no count. `loaded` is returned but `skipped` is not. | G13 lib.rs:421-425 (PARTIALLY-FIXED — refusal logic present, telemetry still missing) | Return `(loaded, skipped)` or log a warning when `skipped > 0`. |
| `rag_engine/src/lib.rs` | 366-410 | INFO | TOCTOU (improved) | `load()` now uses `symlink_metadata` + explicit symlink rejection (line 380), a byte-capped `take(MAX+1)` read (line 400-410) catching mid-read growth, and UTF-8 validation. The classic open-then-fstat race is largely mitigated; a same-size real-file swap between stat and open remains theoretically possible but is moot for a single-user bot. | G13 lib.rs:332-432 (PARTIALLY-FIXED) | For multi-tenant use, open first then `fstat` the open fd. Fine as-is for this deployment. |
| `rag_engine/src/lib.rs` | 71-95, 276-282, 366-368 | INFO | Path traversal (improved) | `validate_relative_path` now rejects absolute paths (73), `..` (80), AND `Component::Prefix` (85) — closing the prior Windows drive-prefix gap (`C:foo`). Applied to both save and load. | G13 (drive-prefix gap) — FIXED-VERIFIED | None. |
| `rag_engine/src/lib.rs` | 213-218 | LOW | Decay semantics | Time-decay clamps `time_decay_factor` to [0,1] and ages to ≥0. `0.5` → half-life ≈ 1.4 h (aggressive). Score = base×decay×importance, so threshold filtering interacts with decay/importance. Behaviour is intentional but undocumented re: units. | G13 lib.rs:215-217, 230 (STILL-PRESENT) | Document that `time_decay_factor` is a per-hour exponential rate and that the threshold applies post-decay. |
| `rag_engine/src/lib.rs` | 190-193, 206-231 | LOW | Memory at scale | `search()` clones every entry (`entries.values().cloned()`) under the read lock so the GIL can be released during rayon work. For a 100k-entry × 384-dim corpus that is ~150 MB cloned per query. Correct (the borrow can't cross `py.detach`), but wasteful. | G13 lib.rs:197-238 (STILL-PRESENT) | Store entries as `Arc<MemoryEntry>` and clone the Arc, not the embedding. |
| `rag_engine/src/lib.rs` | 276-363, 366-466 | LOW | GIL not released | `save()` (JSON encode + fsync I/O) and `load()` (read + JSON decode) run under the held GIL. For large corpora the JSON work + fsync can block other Python threads for hundreds of ms. `search`/`batch_resize` already use `py.detach`. | G13 GIL table (STILL-PRESENT) | Wrap the serialize/IO body in `py.detach` (the entries snapshot/the file ops don't need the GIL). |
| `rag_engine/src/cosine.rs` | 5-9 | MEDIUM | Silent failure | `cosine_similarity` still returns `0.0` on dimension mismatch (`a.len() != b.len()`). `search()` validates the *query* dim, but a stored entry whose embedding got corrupted to a different length would silently score 0.0 instead of erroring. The PyO3 `compute_similarity` wrapper guards separately (lib.rs:269). | G13 cosine.rs:7-13 (STILL-PRESENT) | Return `Option<f32>` (None on mismatch) and have callers treat None as "skip/err" rather than a 0.0 score. |
| `rag_engine/src/cosine.rs` | 45-48 | LOW | Float precision | `1.0 - v as f32` casts the simsimd f64 distance to f32 *before* the subtraction. `(1.0 - v) as f32` would keep the subtraction in f64 and lose less precision (last-bit). | G13 cosine.rs:33-36 (STILL-PRESENT) | Change to `(1.0 - v) as f32`. |
| `rag_engine/src/cosine.rs` | 23-25 | INFO | Correctness (improved) | Zero-vector handling added: both SIMD and scalar paths now return 0.0 for a zero-norm input (prevents simsimd reporting distance 0 → similarity 1.0 "perfect match" for junk vectors). Regression test present (lines 119-128). | G13 (SIMD/scalar disagreement) — FIXED-VERIFIED | None. |
| `rag_engine/src/cosine.rs` | 89 | LOW | Magic number | Scalar denom guard `if denom > 1e-10` — reasonable for f32 but the constant is unexplained vs `f32::EPSILON`. | G13 cosine.rs:76-81 (STILL-PRESENT) | Add a one-line rationale comment. |
| `rag_engine/src/storage.rs` | 251 | LOW | Integer truncation | `(dimension as u32)` in `write_header` truncates silently if `dimension > u32::MAX`. `RagEngine::new` and `VectorStorage::new/open` accept `dimension: usize` with no upper bound. Only reachable if storage were wired up (it isn't — see dead-code finding), but latent. | G13 storage.rs:178-179 (STILL-PRESENT) | `if dimension > u32::MAX as usize { return Err(...) }` in `open`/`new`. |
| `rag_engine/src/storage.rs` | 119-143 | INFO | Robustness (improved) | Pre-existing file with wrong magic now returns an explicit error instead of clobbering the header (prevents silent data destruction on a corrupted/partial file). Fresh-file path writes a valid header. Good. | G13 (new) | None. |
| `rag_engine/src/storage.rs` | 361-366 | INFO | Crash-safety (improved) | `push()` now writes vector bytes, bumps in-memory count, writes header, `mmap.flush()`, then `file.sync_all()` — ordering documented. Per-push double durability cost noted in-code as a future batch-flush opportunity. (Dead code, but correctly written.) | G13 storage.rs:251-261 (improved) | None (would matter only if wired up). |
| `rag_engine/src/storage.rs` | 6-13, 88-94 | INFO | Locking (improved) | Migrated from `fs2` (unmaintained, per-process fcntl) to stdlib `File::lock`/`unlock` (per-fd flock on Linux, LockFileEx on Windows). Closes the prior fs2 staleness finding and the "two opens in same process both lock" footgun. | G13 rag Cargo.toml:20 fs2 (FIXED-VERIFIED) | None. |
| `media_processor/src/lib.rs` | 75-96 | LOW | API footgun | `load()` returns `data: bytes.to_vec()` — the *raw input*, not a re-encoded canonical image — while `width/height/format` describe the decoded view. Callers may assume `.data` is normalized. | G13 lib.rs:75-114 (STILL-PRESENT) | Document that `.data` is the original bytes, or rename. |
| `media_processor/src/lib.rs` | 84-87, 252; resize.rs:23,51 | INFO | DoS cap (improved) | The 100 MP decompression-bomb cap is now enforced via `check_bomb_dimensions` on **every** decode entry point — `load`, `resize`, `resize_exact`, `thumbnail`, AND each item in `batch_resize` (lib.rs:197-199), using header dims before alloc with `u64::checked_mul` overflow guard. Prior gap (batch path bypassed the cap) is closed. | G13 lib.rs:84 (FIXED-VERIFIED for the batch bypass; cap still hard-coded) | The 100 MP cap is still a hard-coded literal not tied to the constructor's `max_dimension`. Optionally plumb it through. |
| `media_processor/src/lib.rs` | 99-131 | LOW | GIL not released | `resize`, `resize_exact`, `thumbnail` (single-image) still run image decode + Lanczos3 + encode under the held GIL (`_py` unused, no `py.detach`). 50-300 ms on large JPEGs blocks other Python threads. `batch_resize` correctly detaches (line 200). | G13 lib.rs:117-146 (STILL-PRESENT) | Wrap each `resize_image(...)` in `py.detach(|| ...)` after `bytes.to_vec()`. |
| `media_processor/src/lib.rs` | 78-101, 240-265; resize.rs:45-67 | INFO | Double decode (perf) | For `resize`/`resize_exact`/`thumbnail`, the image header is parsed twice: once in `check_bomb_dimensions` (lib.rs) via `ImageReader::into_dimensions`, then again inside `resize_image` (resize.rs:46-65), then `load_from_memory`. The dimension cap is therefore validated 2× and the full decode runs once. Correct but redundant header parsing. | — (new) | Pass the already-decoded dims into `resize_image`, or skip the resize.rs re-check when the lib.rs caller already validated. |
| `media_processor/src/lib.rs` | 220-232 | LOW | Format detection | `detect_format` matches PNG/JPEG/GIF/WebP magic and returns `None` for anything else (BMP/TIFF/HEIC/AVIF/SVG). The `.pyi` correctly types this as `str | None` (matches `Option<String>`). `load()` maps None → `"unknown"` (line 87). Callers trusting `format` for routing get a silent `"unknown"` rather than an error. | G13 lib.rs:217-223 (STILL-PRESENT; .pyi now accurate) | Acceptable; document that `"unknown"`/`None` is possible. |
| `media_processor/src/resize.rs` | 39-40, 76-80 | MEDIUM | Silent clamp | `Fill`/`Stretch` modes use `(max_width, max_height)` as the exact output, but those values were silently clamped to `MAX_ALLOWED_DIMENSION` (16384) at lines 39-40. A caller requesting an exact 20000-px output gets a 16384-px image with no error — a silent contract violation for exact-size modes. (Fit mode clamping is harmless.) | G13 resize.rs:39-40 (STILL-PRESENT) | For `Fill`/`Stretch`, error when the requested dimension exceeds `MAX_ALLOWED_DIMENSION` instead of clamping. |
| `media_processor/src/resize.rs` | 51 | INFO | Overflow consistency | `(w as u64) * (h as u64)` here is a plain multiply (not `checked_mul` like lib.rs:246). It cannot overflow u64 (max `(2^32-1)^2 < 2^64`), so it is safe, but it is inconsistent with the `checked_mul` used in `check_bomb_dimensions`. | — (new) | Optional: use `checked_mul` for symmetry, or comment why the plain multiply is sound. |
| `media_processor/src/resize.rs` | 128, 137-141 | LOW | Allocator | Output `Vec::new()` with no capacity hint; a multi-MB encode grows/reallocs repeatedly. Trivial perf. | G13 resize.rs:137-141 (STILL-PRESENT) | `Vec::with_capacity(estimate)`. |
| `media_processor/src/errors.rs` | 7-8 | LOW | Error mapping | `#[from] image::ImageError` → `MediaError::Image`, then surfaced to Python uniformly as `PyValueError` (lib.rs `map_err`). `Limits`-exceeded and IO errors lose their structured distinction (no `MemoryError`/`IOError` mapping). | G13 errors.rs:6 (STILL-PRESENT) | Map specific image-crate error kinds to specific PyErr types. |
| `media_processor/src/encode.rs` | 26-34 | LOW | Data-URI parse | `from_data_uri` splits at the first `,` and base64-decodes the rest; a non-base64 data URI (`data:text/plain,Hello,World`) would mis-decode. `#[allow(dead_code)]` — currently unused. | G13 encode.rs:27 (STILL-PRESENT, dead) | Check for `;base64` segment, or delete the unused helper. |
| `media_processor/src/gif.rs` | 18, 67, 119, 158 | INFO | Math correctness | Color-table size `3 * (1 << ((flags & 0x07) + 1))` — shift max 8 → 256 × 3 = 768. No overflow on usize. All sub-block walks are bounds-checked with `saturating_add`/`> data.len()` breaks. Sound. | G13 gif.rs:17,62,113,153 (STILL-PRESENT, sound) | None. |
| `media_processor/src/gif.rs` | 108-189 | LOW | Partial parse | `get_gif_frame_count` (`#[allow(dead_code)]`, used only in benches) returns the partial count on a malformed/unterminated GIF without surfacing "malformed". `is_animated_gif` early-returns true on frame 2 so it is robust. | G13 gif.rs:35,76,133,163 (STILL-PRESENT) | Document partial-count behaviour, or return `Option`/`Result`. |
| `url_fetcher/main.go` | 46-64 | MEDIUM | SSRF blocklist gaps | `privateNetworks` covers loopback/private/link-local/CGNAT/broadcast + IPv4-mapped IPv6 forms. **Still missing:** `224.0.0.0/4` (multicast), `240.0.0.0/4` (reserved), `198.18.0.0/15` (benchmark), `192.0.0.0/24` (IETF), TEST-NET (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`), `2001:db8::/32` (IPv6 doc), and notably `64:ff9b::/96` (NAT64 — can map an embedded private IPv4 and, on a NAT64-enabled host, reach internal v4 services bypassing the v4 checks). | G13 url_fetcher:45-71 (STILL-PRESENT) | Append the listed CIDRs to the `ranges` slice in `init`. Prioritize `64:ff9b::/96`, multicast, and reserved. |
| `url_fetcher/main.go` | 158-205, 226-233, 245-254 | INFO | SSRF core (verified) | DNS-rebinding defense is correct: `ssrfSafeDialContext` resolves via context-aware `LookupIPAddr`, rejects if ANY resolved IP is private (178-182), then dials the validated IP literal (194) — no second resolution, so the check/dial TOCTOU window is closed. Redirects reuse the same dialer (each hop re-checked); redirect cap = 5 (227). `isPrivateURL` is informational/defense-in-depth. SNI/Host derive from the request URL, so HTTPS-by-IP works. | G13 (verified) — STILL-CORRECT | None. Confirm TLS-vhost behaviour with a live test before prod (low risk). |
| `url_fetcher/main.go` | 307-317 | INFO | Memory cap (improved) | Charset transcoding output is now capped with `io.LimitReader(utf8Reader, maxContentLength)` (line 314), preventing UTF-16/GBK→UTF-8 expansion from exceeding the 10 MB raw-body cap. New hardening not present in the prior audit. | — (new) | None. |
| `url_fetcher/main.go` | 477-484 | LOW | Truncate alloc | `truncateString` does `[]rune(s)` (O(n) allocation, ~4× heap) before slicing. For a 10 MB string that is ~40 MB transient. | G13 url_fetcher:470-477 (STILL-PRESENT) | Stream with `utf8.DecodeRuneInString` and slice the original by byte offset. |
| `url_fetcher/main.go` | 610-618 | INFO | Bind (verified) | Server hard-binds `127.0.0.1` with no host env override; all four server timeouts set; graceful shutdown logs errors. Safer than health_api (which has a host knob). | G13 url_fetcher:604-611 — STILL-CORRECT | None. |
| `url_fetcher/main.go` | 320-329 | LOW | Content types | Only `text/html` / `text/plain` are extracted; `application/json`, `text/xml`, etc. return `"[Binary content]"`. Reasonable for summarization. | G13 url_fetcher:300-309 (STILL-PRESENT) | Optionally extract JSON/XML text. |
| `url_fetcher/main.go` | 272 | LOW | UA fingerprint | `User-Agent: Mozilla/5.0 (compatible; DiscordBot/1.0)` — the "DiscordBot" token may trip some WAFs/bot filters. | G13 url_fetcher:255-257 (STILL-PRESENT) | Make UA configurable. |
| `url_fetcher/main.go` | 257-261 | LOW | Error message | `f.limiter.Wait(ctx)` failure is reported as `"rate limited"` even when the real cause is context cancellation/timeout. Misleading. | G13 url_fetcher:240-244 (STILL-PRESENT) | Distinguish `ctx.Err()` from limiter saturation. |
| `url_fetcher/main.go` | n/a | LOW | http allowed | Both `http://` and `https://` accepted. `file://`/`gopher://` correctly blocked by the scheme prefix check (546, 585). `http` permits cleartext but no secrets are sent. | G13 (STILL-PRESENT) | Optional `require-https` mode. |
| `url_fetcher/main.go` | 503-521 | INFO | Headers | Sets `X-Content-Type-Options: nosniff` + `X-Frame-Options: DENY`; no CORS headers (browser blocks cross-origin by default). Trace-ID pass-through uses a typed context key. | G13 (STILL-PRESENT) | Optional: explicit `Referrer-Policy`, CSP, deny-CORS. |
| `health_api/main.go` | 322-326 | LOW | Middleware note | `middleware.Timeout` was intentionally removed (only signals via ctx, can cause "superfluous WriteHeader"); relies on `http.Server.WriteTimeout` instead. Documented in-code. Sound choice. | G13 277-286 (changed) | None. |
| `health_api/main.go` | 384-560 | LOW | Readability | Handlers registered inside the auth `r.Group` (380) are not indented under it; Go ignores indentation and the shadowed `r chi.Router` is correct, but the flat indentation obscures that these routes ARE auth-gated. Pure readability. | — (new) | Indent the group body for clarity. |
| `health_api/main.go` | 498-560 | LOW | Telemetry | `/metrics/batch` returns `{"processed": N}` but not a `skipped` count; invalid items `continue` silently. | G13 451-499 (STILL-PRESENT) | Add `skipped` to the response. |
| `health_api/main.go` | 278-286 | LOW | Env precedence | Port resolution silently drops legacy `HEALTH_API_PORT=8080` (reserved for the Python health server). Documented in README. | G13 242-251 (STILL-PRESENT, documented) | None. |
| `health_api/main.go` | n/a | LOW | Rate limit | No rate limiter on any endpoint. Bearer auth + 127.0.0.1 default + label allowlist bound the blast radius; a buggy authed client loop could still spam. | G13 (STILL-PRESENT) | Optional `x/time/rate` limiter on write endpoints. |
| `go_services/go.mod` | 9, 24, 23 | INFO | Dep CVE check | `golang.org/x/net v0.53.0`, `x/text v0.36.0`, `x/sys v0.43.0` — current; no known CVE applies. The 2026 Prometheus CVEs (CVE-2026-42154 remote-read DoS, CVE-2026-40179 stored XSS) affect `prometheus/prometheus` (the server), NOT `prometheus/client_golang v1.23.2` used here. `chi v5.2.5`, `goquery v1.9.2`, `cascadia v1.3.2` — no known CVEs. | G13 go.mod (re-verified clean) | Run `govulncheck ./...` in CI to stay current. |
| `rust_extensions/Cargo.lock` | — | INFO | Dep CVE check | Resolved: `pyo3 0.28.2`, `image 0.25.9` (latest 0.25.x; earlier decompression-bomb advisories already patched), `simsimd 6.5.12`, `memmap2 0.9.9`, `gif 0.14.1`, `png 0.18.0`, `image-webp 0.2.4`, `serde 1.0.228`, `thiserror 2.0.18`. No RUSTSEC advisory matches this set as of 2026-05-24 (2026 advisories like RUSTSEC-2026-0041 lz4_flex and Cargo CVE-2026-33056 do not apply). | G13 (re-verified) | Run `cargo audit` in CI. |
| `rag_engine/rag_check.txt` | 1-10 | INFO | Build artifact | A committed transcript of a `cargo check` run (UTF-16, PowerShell `Tee-Object` capture showing "Finished `dev` profile ... in 0.04s"). Confirms the crate compiles (validates the `from_py_object` attribute is accepted), but it is a stray build-log file checked into source. | — (new) | Remove `rag_check.txt` from the repo (build logs are not source). |
| `rag_rust.py` ↔ `rag_engine/src/lib.rs` | 215-217, 250-252 ↔ 71-95 | INFO | Integration / needs verification | The Python wrapper calls `self._engine.save(str(path))` / `load(str(path))` with `path = Path(path)`. The Rust side **rejects absolute paths** (lib.rs:73-77). If any caller passes an absolute path (common for a data dir), the Rust backend raises `PyValueError` and the save/load fails. storage.rs:182-187 documents the expectation that the wrapper `cwd`s into the project root. This cross-file contract was not verifiable within the assigned scope. | — (new) | Verify callers pass relative paths (or that the process cwd is the project root) when the Rust backend is active; otherwise persistence silently fails on the Rust path. |

## Cross-cutting notes

### PyO3 boundary — panics / error conversion / GIL
- Production (non-test, non-bench) Rust code contains **zero** `unwrap()`/`expect()`/`panic!`/
  `unreachable!`/`assert!` on attacker-controlled paths. `unwrap_or` appears only on
  `partial_cmp` (NaN-safe sort, lib.rs:234) and `SystemTime::duration_since` (clock-skew, lib.rs:200-203,
  305-308). `expect(`/`assert!` exist only in `#[cfg(test)]` modules.
- `panic=unwind` (default; no `panic = "abort"` in any Cargo.toml). PyO3 0.28 catches Rust
  unwinds at the FFI boundary and converts them to `PanicException`, so a panic does not abort
  the process — but the only realistic panic sources (slice OOB, integer overflow in debug) are
  guarded by explicit bounds/`checked_*` math. Note benches/`storage.rs`/`index.rs` are not
  exercised, so their (already careful) bounds logic is untested in CI.
- Single `unsafe` block: `storage.rs:113` (`MmapOptions::map_mut`). **Unreachable from Python and
  benches** (see dead-code finding) — the production attack surface has no `unsafe`.
- GIL release: `search` (lib.rs:197) and `batch_resize` (lib.rs:200) detach correctly.
  `resize`/`resize_exact`/`thumbnail`/`save`/`load` still hold the GIL during CPU/IO work (LOW findings).

### SSRF surface (url_fetcher) — verified multi-layer
Scheme allowlist (546,585) → 8 KiB URL cap (540,581) → informational `isPrivateURL` (84-124) →
authoritative connect-time `ssrfSafeDialContext` that validates all resolved IPs and dials the IP
literal (158-205) → per-redirect re-validation (cap 5) → 10 MB body cap + capped charset transcode
(297,314) → 50 RPS/100-burst limiter → hard 127.0.0.1 bind. **The rebinding TOCTOU window is closed.**
Only residual gap: the missing CIDR ranges (MEDIUM), most importantly NAT64 `64:ff9b::/96`.

### Storage atomicity (rag_engine)
- `RagEngine::save` (the production path): temp-file create → write → **`sync_all()`** → rename, with
  an fsync-after-copy fallback for Windows lock contention. **H48 closed.** Residual: no parent-dir
  fsync (rename durability, INFO).
- `VectorStorage::push` (dead code): correctly orders data-flush before count-bump with double fsync.

### Dependencies
All current; no applicable CVEs (Rust set via Cargo.lock; Go set via go.mod). `bytemuck` direct
declaration is unused (LOW). `fs2` successfully removed in favor of stdlib locking (FIXED).
Recommend `cargo audit` + `govulncheck` in CI.

## Prior-finding disposition (G13 / MASTER_TABLE)

| Prior | Subject | Disposition (current lines) |
|---|---|---|
| H48 | rag save() missing fsync before rename | **FIXED-VERIFIED** — lib.rs:323 (`sync_all` temp) + 338 (fsync after copy). Residual: no dir fsync (INFO). |
| H49 (auth) | health_api write endpoints unauthenticated | **FIXED-VERIFIED** — bearer-token Group, fail-closed (main.go:238-262, 380-561). |
| H49 (bind) | `GO_HEALTH_API_HOST=0.0.0.0` opens endpoints | **PARTIALLY-FIXED** — writes now authed, but `/metrics` + `/stats` read endpoints still leak runtime internals if bound public; host env knob remains (MEDIUM). |
| G13 fs2 unmaintained | rag_engine Cargo.toml | **FIXED-VERIFIED** — migrated to stdlib `File::lock` (storage.rs:6-13,88-94). |
| G13 `from_py_object` "typo" | pyclass attribute | **RESOLVED (prior concern incorrect)** — valid PyO3 0.28 option; compiles; load-bearing. |
| G13 bytemuck unused | workspace dep | **STILL-PRESENT** — declared, no `bytemuck::` calls (LOW). |
| G13 add_batch silent skip | rag lib.rs | **STILL-PRESENT** — lib.rs:145-160 (MEDIUM). |
| G13 cosine silent 0.0 on dim mismatch | cosine.rs | **STILL-PRESENT** — cosine.rs:5-9 (MEDIUM). |
| G13 cosine SIMD/scalar zero-vec disagreement | cosine.rs | **FIXED-VERIFIED** — cosine.rs:23-25 + test. |
| G13 cosine f64→f32 precision | cosine.rs | **STILL-PRESENT** — cosine.rs:45-48 (LOW). |
| G13 VectorIndex dead code | index.rs | **STILL-PRESENT** — improved but still uninstantiated (MEDIUM). |
| G13 storage mmap UB | storage.rs:98 | **STILL-PRESENT as dead code** — now unreachable from Python+benches (MEDIUM dead-code). |
| G13 storage dimension u32 truncation | storage.rs | **STILL-PRESENT** — storage.rs:251 (LOW). |
| G13 batch-resize bypasses bomb cap | media lib.rs | **FIXED-VERIFIED** — lib.rs:197-199 checks each item. |
| G13 single-image resize holds GIL | media lib.rs | **STILL-PRESENT** — lib.rs:99-131 (LOW). |
| G13 resize Fill/Stretch silent clamp | resize.rs | **STILL-PRESENT** — resize.rs:39-40,76-80 (MEDIUM). |
| G13 load TOCTOU / drive-prefix path | rag lib.rs | **FIXED/PARTIALLY-FIXED** — symlink reject + capped read + Prefix check added. |
| G13 SSRF missing CIDRs | url_fetcher init | **STILL-PRESENT** — main.go:46-64 (MEDIUM). |
| G13 SSRF dial-by-IP rebinding defense | url_fetcher | **STILL-CORRECT (verified)**. |
| G13 detect_format .pyi mismatch | media | **FIXED** — `.pyi` now `str | None`. |

## Confirmation
- All 22 assigned files read in full, line by line, from working-tree content (not diffs).
- Verified reachability via `Cargo.lock`, bench sources, and `rag_rust.py`: `VectorStorage` and
  `VectorIndex` (and the sole `unsafe` block) are dead from both Python and tests.
- Web-verified: PyO3 0.28 `from_py_object` is valid (issue #4337); no applicable CVEs for
  x/net 0.53.0, prometheus client_golang 1.23.2, chi 5.2.5, goquery 1.9.2, cascadia 1.3.2,
  image 0.25.9, simsimd 6.5.12, memmap2 0.9.9.
- No secrets, credentials, or hardcoded tokens found in any in-scope file.

Sources:
- PyO3 `from_py_object` pyclass option — https://github.com/PyO3/pyo3/issues/4337
- Prometheus 2026 CVEs (server, not client_golang) — https://advisories.gitlab.com/golang/github.com/prometheus/prometheus/CVE-2026-42154/
- RustSec Advisory Database — https://rustsec.org/advisories/
- Go vulnerability database — https://pkg.go.dev/vuln/list
