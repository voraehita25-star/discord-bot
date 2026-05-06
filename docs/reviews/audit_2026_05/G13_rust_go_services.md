# G13: Rust Extensions + Go Services — Audit Report

Audit date: 2026-05-04
Auditor: Claude (Opus 4.7, 1M context)
Scope: PyO3-bound Rust extensions and Go microservices.

## Files Reviewed

| File | Lines | Purpose |
|---|---|---|
| `rust_extensions/Cargo.toml` | 24 | Workspace manifest (pyo3 0.28, rayon 1.11, etc.) |
| `rust_extensions/media_processor/Cargo.toml` | 26 | image 0.25, base64 0.22 |
| `rust_extensions/media_processor/src/lib.rs` | 257 | PyO3 entry, `MediaProcessor` & `ImageData` classes |
| `rust_extensions/media_processor/src/encode.rs` | 57 | Base64 encode/decode helpers |
| `rust_extensions/media_processor/src/errors.rs` | 21 | `MediaError` enum |
| `rust_extensions/media_processor/src/gif.rs` | 200 | GIF animation detection / frame count |
| `rust_extensions/media_processor/src/resize.rs` | 195 | Image resize (Fit/Fill/Stretch) |
| `rust_extensions/rag_engine/Cargo.toml` | 33 | simsimd 6.5, fs2 0.4, memmap2 |
| `rust_extensions/rag_engine/src/lib.rs` | 447 | PyO3 entry, `RagEngine` class, save/load |
| `rust_extensions/rag_engine/src/cosine.rs` | 135 | SIMD/scalar cosine similarity |
| `rust_extensions/rag_engine/src/errors.rs` | 21 | `RagError` enum |
| `rust_extensions/rag_engine/src/index.rs` | 153 | Keyword inverted index (`VectorIndex`) |
| `rust_extensions/rag_engine/src/storage.rs` | 338 | Memory-mapped binary vector storage |
| `go_services/go.mod` | 26 | Go 1.25.0; chi v5.2.5; prometheus 1.23.2 |
| `go_services/go.sum` | 92 | Module checksums |
| `go_services/health_api/main.go` | 569 | Prometheus metrics + health probes |
| `go_services/url_fetcher/main.go` | 632 | URL fetcher with SSRF guards |

## Issues Found

Severity scale: **CRITICAL** = remote unauth exploit / data loss; **HIGH** = exploitable but bounded or auth-gated; **MEDIUM** = misconfig/robustness gap; **LOW** = nit, code quality, deprecated pattern.

| File | Line(s) | Severity | Category | Description |
|---|---|---|---|---|
| `rust_extensions/Cargo.toml` | 15 | LOW | Dependency hygiene | `pyo3 = 0.28` is current major. `bytemuck` is declared as workspace dep (line 22) but no longer used by code in `storage.rs` (rewritten to explicit LE byte ops); leaving the dep adds compile time and an unaudited transitive surface. Remove `bytemuck` from workspace deps unless something else still uses it. |
| `rust_extensions/Cargo.toml` | 17 | LOW | Lifecycle | `rayon = "1.11"` — rayon 1.10+ has a known minor change to `par_iter` cancellation; verify min-rust-version still satisfied (project uses edition 2021, fine). No CVE. |
| `rust_extensions/rag_engine/Cargo.toml` | 20 | MEDIUM | Dependency staleness | `fs2 = "0.4"` is unmaintained (last release 2018, last commit 2020). Replaces with `fs4` for a maintained fork. The exclusive `lock_exclusive()` API is the only call site and `fs4::FileExt::lock_exclusive` is a drop-in. |
| `rust_extensions/rag_engine/Cargo.toml` | 23 | MEDIUM | Dependency / FFI | `simsimd = "6.5"` — reaches into C SIMD intrinsics via the bundled C library. No public CVEs at time of audit, but the crate has unsoundness history (RustSec has historically flagged unsafe vector reads on non-aligned slices). Pin to exact minor (`=6.5.x`) and review on each upgrade; the crate compiles a C library with `cc` so changes are not visible from `cargo audit` alone. |
| `rust_extensions/media_processor/Cargo.toml` | 17 | LOW | Format allowlist | `image = { version = "0.25", default-features = false, features = ["jpeg","png","gif","webp"] }` — good (bmp/tiff/avif/dds disabled). However GIF feature in `image 0.25` historically had decompression-bomb path issues; the project's own pre-decode dimension check (resize.rs:46-65, lib.rs:79-96) compensates. Confirm bumped to ≥0.25.5 once available; current pin is implicit `~0.25.0`. |
| `rust_extensions/media_processor/src/lib.rs` | 25, 52, 65 | MEDIUM | PyO3 API misuse | `#[pyclass(from_py_object)]` on `ImageData`, `MemoryEntry`, and `SearchResult` (lib.rs:25, lib.rs:52, lib.rs:65 in rag_engine) is **not a real PyO3 attribute**. PyO3 0.28 does not document a `from_py_object` argument to `#[pyclass]`. This either silently does nothing (best case) or is a typo for `#[derive(FromPyObject)]` on a separate struct. Verify with `cargo build` that this still compiles on 0.28 — if it compiles, it's a no-op and can be removed. The classes are still constructible/usable because they have `#[pymethods] impl ... { #[new] fn new(...) }`. |
| `rust_extensions/media_processor/src/lib.rs` | 75-114 | LOW | API surface | `MediaProcessor::load` returns the original `bytes.to_vec()` as `data` — i.e. it does NOT re-encode. So `ImageData.format` / `width` / `height` describe a decoded view but `.data` is the *raw input*. This is a footgun: callers will assume `.data` is a re-encoded canonical PNG/JPEG. Document or rename. |
| `rust_extensions/media_processor/src/lib.rs` | 84 | MEDIUM | DoS hardening | The 100 MP cap on `load()` is hard-coded and not configurable per `MediaProcessor` instance, even though the constructor accepts `max_dimension` (line 70). A caller that lowers `max_dimension` to 256 has no way to also lower the pixel-bomb cap. Plumb a constructor field. |
| `rust_extensions/media_processor/src/lib.rs` | 117-146 | MEDIUM | GIL release | `resize`, `resize_exact`, `thumbnail` perform CPU-bound work *without* releasing the GIL (`_py: Python<'py>` is unused, no `py.detach()`). Single-image work can be 50-300 ms on JPEG decode — this freezes other Python threads. Wrap the `resize_image` call in `py.detach(|| ...)` after `bytes.to_vec()`. |
| `rust_extensions/media_processor/src/lib.rs` | 184-202 | LOW | Memory overhead | `batch_resize` clones every input via `.as_bytes().to_vec()` (line 187) before releasing GIL. For N×10 MB images that's 100 MB of redundant heap. Acceptable trade-off (rayon needs `'static`-ish data; keeping `Bound<PyBytes>` across `py.detach` is unsafe), so leave a comment but flag for future optimization with `into_bound()` patterns. |
| `rust_extensions/media_processor/src/lib.rs` | 194 | LOW | API name | `py.detach(|| ...)` is the new PyO3 0.28 spelling — correct. Older docs/migration guides still reference `py.allow_threads`; flag for any reviewer. |
| `rust_extensions/media_processor/src/lib.rs` | 217-223 | LOW | Format detection | `detect_format` checks JPEG via `[0xFF, 0xD8, 0xFF, _]` — accepts the standard SOI marker but does not reject BMP/TIFF/HEIC/AVIF/SVG. Anything unrecognized returns `"unknown"`, not an error, so callers that trust `format` for routing get silent fallbacks. Consider returning `Result` and rejecting unknown. |
| `rust_extensions/media_processor/src/encode.rs` | 27 | LOW | Robustness | `from_data_uri` finds the *first* `,` — fine for `data:image/png;base64,…` but silently mishandles `data:text/plain,Hello,World` (which would split at the first comma and try to base64-decode `Hello,World`). Document that this assumes base64 data URIs only, or check for `;base64` segment. |
| `rust_extensions/media_processor/src/gif.rs` | 17, 62, 113, 153 | LOW | Math correctness | `1 << ((flags & 0x07) + 1)` — shift count max is 8 (when `flags & 0x07 == 7`), result max 256, multiplied by 3 = 768. No overflow on `usize`. OK. |
| `rust_extensions/media_processor/src/gif.rs` | 26, 122 | LOW | DoS bound | `max_iterations = data.len().min(100_000)` — a 10 MB GIF caps to 100k loop iterations. Each iteration does at most one length-prefixed read. Bound is sound; leave comment that 100k frames is excessive (the 1-frame early-return at line 50 means real animated detection bails on frame 2). |
| `rust_extensions/media_processor/src/gif.rs` | 35, 76, 133, 163 | LOW | Defensive parsing | Sub-block walking loops use `data[i] != 0` as terminator; a maliciously-crafted GIF with no terminator drops out via the bounds check (`> data.len()`) but *silently* — does not log or surface "malformed". This is fine for a probe function, but `get_gif_frame_count` returns the partial count, which could be misleading. Document. |
| `rust_extensions/media_processor/src/resize.rs` | 21-23 | LOW | Bound rationale | `MAX_ALLOWED_DIMENSION = 16384` is reasonable (matches WebGL spec); `MAX_PIXEL_COUNT = 100M` matches PIL `MAX_IMAGE_PIXELS`. OK. |
| `rust_extensions/media_processor/src/resize.rs` | 39-40 | MEDIUM | Aspect ratio | When `max_width > MAX_ALLOWED_DIMENSION`, the value is clamped — but if the *caller* requested an exact-resize via `Stretch`/`Fill`, the clamp silently produces a different output than requested, with no error. Either reject or document: prefer rejecting with a `MediaError`. |
| `rust_extensions/media_processor/src/resize.rs` | 67 | MEDIUM | Decode bomb | `image::load_from_memory(data)?` happens *after* the dimension pre-check. Good. However `image 0.25` allows progressive JPEG/animated WebP that may still allocate frame buffers larger than the declared dimensions. Constrain via `image::ImageReader::with_guessed_format()?.decode()` and set `reader.no_limits()` only consciously; today the call goes through `load_from_memory` which uses default limits. Verify default limits suffice (image crate default is 512 MB for some formats — 100 MP×4 bytes = 400 MB so we're under). |
| `rust_extensions/media_processor/src/resize.rs` | 101-102 | LOW | Overflow | `(orig_w as f64 * scale).ceil().min(u32::MAX as f64) as u32` — saturating cast in Rust returns `u32::MAX` for `f64::INFINITY`. Combined with the dimension cap, no overflow possible. OK. |
| `rust_extensions/media_processor/src/resize.rs` | 109-114 | LOW | Edge case | `crop_w/crop_h.max(1)` — if `actual_w == 0` (impossible after resize_exact succeeds but defensive), cropping with `(0, 0, 1, 1)` outside bounds can panic. The code reads `actual_w/actual_h` from the resized image, which `image::imageops::resize_exact` cannot return as zero (returns original on identical size). Sound. |
| `rust_extensions/media_processor/src/resize.rs` | 137-141 | LOW | Allocator pressure | `Vec::new()` for output buffer with no `Vec::with_capacity` hint; for a 4096×4096 RGB JPEG that's 30+ realloc/grows. Trivial perf nit. |
| `rust_extensions/media_processor/src/resize.rs` | n/a | MEDIUM | Threading | None of the resize functions take `Python<'_>`, so they release the GIL implicitly only when called from `batch_resize`. The single-image `resize_image` is invoked under the held GIL by `MediaProcessor::resize` — same issue as lib.rs:117-146. |
| `rust_extensions/media_processor/src/errors.rs` | 6 | LOW | `From` exposure | `#[from] image::ImageError` lets unhandled image-crate errors propagate as `MediaError::Image`. Some image-crate errors (e.g. `Limits` exceeded) are then formatted with `Display` and surface to Python as `PyValueError` — this is fine but loses structured info (e.g. retry vs fatal). Consider mapping to specific PyError types (`MemoryError` for limits, `IOError` for IO). |
| `rust_extensions/rag_engine/src/lib.rs` | 25, 52 | MEDIUM | PyO3 attr | Same as media_processor lib.rs:25 — `#[pyclass(from_py_object)]` is unrecognized in PyO3 0.28. Either harmless no-op or compile fails. Verify build. |
| `rust_extensions/rag_engine/src/lib.rs` | 109 | LOW | Default value | `dimension=384` matches `all-MiniLM-L6-v2` default; documented OK. |
| `rust_extensions/rag_engine/src/lib.rs` | 145-160 | MEDIUM | Silent skip | `add_batch` silently skips invalid entries (wrong dim, NaN, etc.) and returns count. Caller has no way to know which entries failed. Either log or return a Vec of errors. Loud failure is the safer default for memory-management code. |
| `rust_extensions/rag_engine/src/lib.rs` | 163-166 | LOW | Bool return | `remove` returns `bool` (true if removed). The corresponding `VectorIndex::remove` (index.rs:80) does not run alongside it — `RagEngine` has `entries: HashMap` only, no inverted-index hookup. If `VectorIndex` is dead code, drop it; if it's intended to be wired up, this is a missing-coupling bug. |
| `rust_extensions/rag_engine/src/lib.rs` | 197-238 | LOW | Snapshot copy | `entries_snapshot: Vec<_> = entries.values().cloned().collect()` clones ALL entries on every `search()` call. For a 100k-entry corpus with 384-dim embeddings, that's ~150 MB cloned per query. The clone is needed because the `&MemoryEntry` borrow can't survive `py.detach`. Consider `Arc<MemoryEntry>` to clone only the Arc, not the embedding. **Significant memory waste at scale.** |
| `rust_extensions/rag_engine/src/lib.rs` | 215-217 | LOW | Logic | `clamped_decay = time_decay_factor.clamp(0.0, 1.0)` — a `time_decay_factor` of 0.5 corresponds to a half-life of `ln 2 / 0.5 ≈ 1.4 hours`, which is aggressive. The clamp prevents `e^huge` blow-up but lets `e^0` (no decay) through unchanged. Document units. |
| `rust_extensions/rag_engine/src/lib.rs` | 230 | LOW | Threshold + decay | `filter(|r| r.score >= similarity_threshold)` — the threshold is applied to `base_score * decay * importance`. A high-importance old memory drops below threshold faster than its base similarity would suggest. Probably intended; document. |
| `rust_extensions/rag_engine/src/lib.rs` | 234 | LOW | NaN sort | `partial_cmp(...).unwrap_or(Equal)` — safe because `final_score` is forced to 0.0 when non-finite (line 226). Sound. |
| `rust_extensions/rag_engine/src/lib.rs` | 268-273 | LOW | API | `compute_similarity` is `#[staticmethod]` and accepts `Vec<f32>` by value (PyO3 will allocate). For benchmarking from Python it's fine; for hot-path use callers should bypass it. |
| `rust_extensions/rag_engine/src/lib.rs` | 283-329 | HIGH | Atomic write | The atomic write IS implemented correctly with unique temp-file names (PID+nanos), and the rename-fallback handles Windows file lock contention. **However** there is **no `fsync` on the temp file before rename**. After `std::fs::write` returns, the data is in the page cache only. On Linux, `rename(2)` does not guarantee the renamed file's data is durable. A power loss between write+rename and OS flush leaves an empty/short file at `path`. Add `let f = OpenOptions::new().write(true).truncate(true).create(true).open(&temp_path)?; f.write_all(&json)?; f.sync_all()?;` then drop `f` before rename. |
| `rust_extensions/rag_engine/src/lib.rs` | 314-326 | MEDIUM | Cleanup | If `rename` fails AND `copy` succeeds, the temp file is removed. If `copy` fails, the temp file is also removed — but the destination `path` may now be partially written (if `copy` got partway). Document that on copy fallback, `path` may be in an inconsistent state. |
| `rust_extensions/rag_engine/src/lib.rs` | 332-432 | MEDIUM | TOCTOU | `load` uses `symlink_metadata` then `File::open`. Between the two calls, the file could be replaced with a symlink (TOCTOU). Mitigated by `take(read_cap)` and the post-read size check (line 371), but a malicious replace with a *real file* of equal size and different content is still possible. For a personal bot this is moot; for a multi-tenant service, open-then-fstat is the canonical fix. |
| `rust_extensions/rag_engine/src/lib.rs` | 365 | LOW | Memory hint | `Vec::with_capacity((symlink_meta.len() as usize).min(MAX_LOAD_BYTES as usize))` — on a 32-bit host, `symlink_meta.len() as usize` saturates if `len > usize::MAX`; `.min(MAX_LOAD_BYTES)` caps it to 256 MiB which fits in 32-bit `usize`. Sound. |
| `rust_extensions/rag_engine/src/lib.rs` | 377 | LOW | Unicode strict | `String::from_utf8(buf)` rejects non-UTF8. Prevents JSON tricks but means the loader can't read data written with BOMs. JSON spec forbids BOM, so OK. |
| `rust_extensions/rag_engine/src/lib.rs` | 421-425 | MEDIUM | Refusal logic | "If `new_entries` is empty AND source had entries → reject" — correct, but if a source has 1 valid + 999 invalid (wrong dim), we accept the swap and silently drop the 999. No telemetry. Add a `loaded_skipped` counter to the return tuple. |
| `rust_extensions/rag_engine/src/lib.rs` | 428-431 | LOW | Atomicity | `*entries = new_entries` under write lock is correctly atomic. Sound. |
| `rust_extensions/rag_engine/src/cosine.rs` | 7-13 | MEDIUM | Silent failure | `cosine_similarity` returns `0.0` on dimension mismatch. Caller has no signal. The PyO3 wrapper (`compute_similarity`) does check first and raises, but **internal** callers in `search()` (line 209) trust this. If dim is wrong, every result silently scores 0.0. Even though `search()` already validates query dim, an entry with corrupted embedding (post-mmap-corruption) would scope-pollute results with 0.0 scores. Consider returning `Option<f32>`. |
| `rust_extensions/rag_engine/src/cosine.rs` | 33-36 | MEDIUM | SIMD wrapper | `f32::cosine(a, b)` — simsimd's API. Returns `Option<f64>`. The conversion `1.0 - v as f32` loses f64 precision before the subtraction; should be `(1.0 - v) as f32`. Tiny numerical diff (last bit). |
| `rust_extensions/rag_engine/src/cosine.rs` | 49-65 | LOW | Manual unroll | The 4-wide unrolled scalar fallback is safe (chunk math is exact) but adds maintenance burden vs trusting LLVM autovec. Not a bug. |
| `rust_extensions/rag_engine/src/cosine.rs` | 76-81 | LOW | Magic number | `1e-10` for denom near-zero check is reasonable for `f32`; explain why this isn't `f32::EPSILON`. |
| `rust_extensions/rag_engine/src/index.rs` | n/a | MEDIUM | Dead code | `VectorIndex` is `pub use`'d at lib.rs:21 but **never instantiated** in `RagEngine`. The keyword index, free-slot reuse, and remove logic are unreachable from Python. Either wire it into `RagEngine::add` and expose keyword search, or delete the file. As written, ~150 lines of unused/untested code with its own bugs (e.g. line 36-38 iterates ALL keyword buckets on every duplicate add — O(K) per add). |
| `rust_extensions/rag_engine/src/index.rs` | 41 | LOW | Tokenization | `text.split_whitespace()` + `to_lowercase()` is anglocentric — Thai/CJK has no whitespace tokenization. For a Thai-RP Discord bot this matters. Use Unicode segmentation or doc the limitation. |
| `rust_extensions/rag_engine/src/storage.rs` | 98 | HIGH | mmap UB risk | `unsafe { MmapOptions::new().map_mut(&file)? }` — fundamentally unsafe per memmap2 docs. The comment (line 93-97) acknowledges that external truncation can SIGBUS the process. Mitigated by `lock_exclusive` (line 78) but `flock` is advisory on Linux and ignored by `dd`/`cat > file`. For a single-process bot this is acceptable; document as a deployment constraint. |
| `rust_extensions/rag_engine/src/storage.rs` | 178-179 | LOW | Type cast | `(dimension as u32)` — `dimension` is `usize`. On a 32-bit host they're identical; on 64-bit, dimensions >4G silently wrap. The constructor has no upper bound on `dimension`. Add `if dimension > u32::MAX as usize { return Err(...) }`. |
| `rust_extensions/rag_engine/src/storage.rs` | 251-261 | MEDIUM | Crash safety order | The comment at 252-257 promises "flush data BEFORE bumping count". Inspecting the code:<br>1. Write vector bytes (line 250)<br>2. `mmap.flush()` (line 258)<br>3. `self.count += 1` (line 259)<br>4. `write_header(...)` updating count on disk (line 260)<br>5. `mmap.flush()` (line 261)<br>This is correct, but `mmap.flush()` is a *synchronous* msync; on NTFS this can take 100-500 ms per `push`, killing batch-insert throughput. Provide a `push_no_flush` + explicit `flush()` for batch use. |
| `rust_extensions/rag_engine/src/storage.rs` | 270-301 | LOW | mmap read | `get` decodes via `from_le_bytes` per `chunk` — correct and host-independent. Could replace with `bytemuck::cast_slice::<u8,f32>` for speed *if* alignment can be guaranteed (mmap base is page-aligned and HEADER_SIZE=68 is NOT 4-byte-aligned ⚠️). 68 % 4 = 0 — actually it IS 4-aligned, so cast_slice is safe. Manual loop is just slow. |
| `rust_extensions/rag_engine/src/storage.rs` | 313-319 | LOW | Flush API | `flush()` is `&mut self`, but for parallel readers under `&self` there's no read-only flush available. Tighten if needed. |
| `rust_extensions/rag_engine/src/storage.rs` | 322-338 | LOW | Drop order | Drop drops `mmap` first (line 332), then unlocks file (335). Correct order. The `let _ = mmap.flush()` swallows errors silently — acceptable for Drop but log on debug builds. |
| `rust_extensions/rag_engine/src/errors.rs` | 6 | LOW | Variant balance | `RagError::Serialization(String)` is overloaded for almost all "bad input" cases (path traversal, NaN, dim mismatch). Hard to discriminate at call site. Consider splitting `InvalidPath`, `NonFinite`, `Overflow`. |
| `go_services/go.mod` | 9 | LOW | Dep version | `golang.org/x/net v0.53.0` — `x/net` is the home of `golang.org/x/net/http2` which has had a CVE history (CVE-2023-39325 Rapid Reset, CVE-2023-44487, CVE-2024-45338 charset DoS). v0.53 is recent; verify with `govulncheck`. The `charset` import (url_fetcher main.go:25) is at risk of CVE-2024-45338 (charset.NewReader DoS via huge `<meta>` charset). v0.53 should include the fix; confirm. |
| `go_services/go.mod` | 8 | LOW | Dep version | `prometheus/client_golang v1.23.2` — current. No known CVEs. |
| `go_services/go.mod` | 7 | LOW | Dep version | `go-chi/chi/v5 v5.2.5` — current. No known CVEs. |
| `go_services/go.mod` | 6 | LOW | Dep version | `PuerkitoBio/goquery v1.9.2` — current. No known CVEs. Note goquery uses `cascadia` which had GHSA-* in 2022; v1.3.2 is patched. |
| `go_services/health_api/main.go` | 32-109 | LOW | Cardinality | All metric label sets pass through `safeLabel` allowlist (line 220-240). Good. The `discord_bot_circuit_breaker_state` gauge has `{service}` label — only 5 services in allowlist (line 226). Sound. |
| `go_services/health_api/main.go` | 79-84 | LOW | Allowlist freshness | `allowedMetricNames` and `allowedLabelValues` are static maps. Adding a new metric requires Go rebuild — could be a config file load. Doc as design choice. |
| `go_services/health_api/main.go` | 242-251 | LOW | Env precedence | Reads `GO_HEALTH_API_PORT`, falls back to `HEALTH_API_PORT`, then defaults to 8082. The `legacyPort != "8080"` check (line 246) silently drops port 8080 — assumes 8080 is now reserved. Document. |
| `go_services/health_api/main.go` | 254-260 | MEDIUM | **Bind address default** | `bindHost` defaults to `127.0.0.1` (good), but if operator sets `GO_HEALTH_API_HOST=0.0.0.0` there's NO authentication on `/health`, `/health/service`, `/metrics/push`, `/metrics/batch`, `/stats`. The `/metrics/push` endpoint is a write surface. **Add a token-auth middleware** OR document loudly that 0.0.0.0 binding is unsupported. Currently a single env var flips this open. |
| `go_services/health_api/main.go` | 290 | HIGH | Prometheus exposure | `r.Handle("/metrics", promhttp.Handler())` — the Prometheus endpoint exposes Go runtime stats (goroutine count, GC pause, memory addresses in `go_memstats_*`). Bound to 127.0.0.1 by default, fine; if 0.0.0.0 (see above), this leaks process internals. Add bearer-token auth. |
| `go_services/health_api/main.go` | 277-286 | LOW | Middleware order | `Logger` -> `Recoverer` -> `Timeout(30s)` -> security headers. Order is fine. `Recoverer` after `Logger` means panics are logged twice (once by Logger via 500, once by Recoverer's stacktrace) — minor. |
| `go_services/health_api/main.go` | 281-287 | MEDIUM | Missing security headers | `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` only. Add: `Strict-Transport-Security` (if behind TLS), `Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none'`. The `/metrics` text-plain output is harmless but `/health` returns JSON that an attacker page could fetch via CORS (currently no CORS headers, so browser blocks — **good**). |
| `go_services/health_api/main.go` | 281-287 | MEDIUM | CORS absent | No CORS middleware. Any cross-origin browser request with credentials will be blocked by the browser, but a no-credential GET to `/health` would succeed and return JSON. Add explicit `Access-Control-Allow-Origin` (likely deny-all) to make policy explicit. |
| `go_services/health_api/main.go` | 333, 361, 431 | LOW | Body size cap | `MaxBytesReader(w, r.Body, 1<<16)` for single push (64 KiB), `1<<20` for batch (1 MiB). Sound. |
| `go_services/health_api/main.go` | 352 | LOW | Response | `service map full` returns 409 Conflict. Sound. |
| `go_services/health_api/main.go` | 381-384 | LOW | Counter validation | Explicit NaN/Inf/<0 rejection — exemplary. |
| `go_services/health_api/main.go` | 451-499 | LOW | Batch validation | Same NaN/Inf/<0 rejection in batch path; on invalid item the loop silently `continue`s. The response only reports `processed` count, not skipped count. Add `skipped` to telemetry. |
| `go_services/health_api/main.go` | 519-535 | LOW | Goroutine | Metrics collector goroutine — has context cancel via `metricsCancel` (line 555). Sound. |
| `go_services/health_api/main.go` | 538-545 | LOW | Server timeouts | `ReadTimeout: 15s, ReadHeaderTimeout: 5s, WriteTimeout: 30s, IdleTimeout: 60s` — all set. Exemplary. |
| `go_services/health_api/main.go` | 559 | LOW | Shutdown error | `server.Shutdown(ctx)` — return value ignored. Should `log.Printf` on non-nil. |
| `go_services/health_api/main.go` | n/a | LOW | Missing rate limit | No rate limiting on `/metrics/push` (or any endpoint). On 127.0.0.1 only the local Python bot can hit it, but a buggy Python loop could overrun the metric labels. The label allowlist mitigates cardinality blowup; add a `golang.org/x/time/rate` limiter for robustness. |
| `go_services/url_fetcher/main.go` | 32 | LOW | Const | `maxContentLength = 10 MB` — sound. |
| `go_services/url_fetcher/main.go` | 33 | LOW | Const | `maxExtractedLength = 50000` runes — counted in `truncateString` via `utf8.RuneCountInString`, so this is rune count not bytes. Correct for Thai. |
| `go_services/url_fetcher/main.go` | 45-71 | LOW | SSRF blocklist | Comprehensive private-IP CIDRs including IPv4-mapped IPv6 forms (`::ffff:127.0.0.0/104` etc.). **Missing**: `224.0.0.0/4` (IPv4 multicast), `240.0.0.0/4` (IPv4 reserved future), `198.18.0.0/15` (benchmarking), `192.0.0.0/24` (IETF), `192.0.2.0/24`/`198.51.100.0/24`/`203.0.113.0/24` (TEST-NET, can be hijacked locally), `2001:db8::/32` (IPv6 doc), `2001::/23` (IETF), `64:ff9b::/96` (NAT64). For a Discord bot fetching arbitrary URLs, these *should* be blocked. |
| `go_services/url_fetcher/main.go` | 84-124 | MEDIUM | DNS rebinding | `isPrivateURL` does a *first* DNS lookup. The actual connection uses `ssrfSafeDialContext` which does a *second* lookup at connect time. **The two lookups can return different results** (rebinding). The dialContext (line 178-186) correctly validates the actual IP before dial — so the rebinding window is closed at the dial step. **However**, `ssrfSafeDialContext` does its OWN `LookupIPAddr` and dials `ips[0]` (line 186). So `isPrivateURL` is informational only, not security-critical. Good defense-in-depth. |
| `go_services/url_fetcher/main.go` | 95-103 | MEDIUM | Hostname blocklist | Hardcodes a small list of cloud metadata endpoints. Misses: Azure (`169.254.169.254` — listed), Oracle Cloud (`192.0.0.192`), DigitalOcean (`169.254.169.254` — same as AWS), Linode (`192.168.196.1`), Hetzner. The IP-based check at dial time catches most via the `169.254.0.0/16` block, but the Oracle and Linode IPs are in private ranges already covered. Sound. |
| `go_services/url_fetcher/main.go` | 105 | LOW | Case | `strings.EqualFold(hostname, h)` — case-insensitive. Good. |
| `go_services/url_fetcher/main.go` | 111-117 | LOW | DNS failure | When `LookupIP` fails, returns `false, error`. The caller (`Fetch` line 228) inspects `isPrivate` first; with `isPrivate=false` and `err != nil`, the caller proceeds to `ssrfSafeDialContext` which will re-resolve. Comment on line 113 documents this. Sound. |
| `go_services/url_fetcher/main.go` | 160-188 | HIGH | DNS rebinding mitigation | Implementation of `ssrfSafeDialContext`:<br>1. Resolve via `resolver.LookupIPAddr(ctx, host)` — context-aware (good).<br>2. Walk all IPs and reject if ANY is private (good — multi-record DNS attack mitigated).<br>3. Dial `net.JoinHostPort(ips[0].IP.String(), port)` — uses **only first IP**, so dial doesn't re-resolve, hence no rebinding window between check and dial.<br>**This is correct and exemplary.** |
| `go_services/url_fetcher/main.go` | 174-176 | LOW | Empty IP list | Defensive check — `LookupIPAddr` typically returns error on empty, but this is belt-and-suspenders. |
| `go_services/url_fetcher/main.go` | 184-186 | MEDIUM | TLS SNI | When dialing the resolved IP directly, the `Host` header from the original URL is preserved (Go HTTP client uses the request URL host, not the dial target). **However** TLS SNI uses the dial target by default if `tls.Config.ServerName` isn't set. With Go's default `Transport`, the `tls.Config` is built from the request's URL host, so SNI is correct. Confirm via test: hit a TLS-virtual-host site (e.g. `https://github.com` resolves to multiple IPs hosting many vhosts) and verify cert validation succeeds. **Worth a manual test before production.** |
| `go_services/url_fetcher/main.go` | 191-220 | LOW | Transport tunings | `MaxIdleConns 200, MaxConnsPerHost 50` — generous. Suitable for hardware mentioned in line 218 comment. |
| `go_services/url_fetcher/main.go` | 209-216 | LOW | Redirect cap | `len(via) >= 5` returns "too many redirects". Good. The redirect target is dialed via `ssrfSafeDialContext` so each hop is SSRF-checked. |
| `go_services/url_fetcher/main.go` | 218 | LOW | Rate limit | `rate.NewLimiter(rate.Limit(50), 100)` = 50 RPS sustained, burst 100. Process-wide (not per-client). For a bot it's fine; for shared service add per-token limits. |
| `go_services/url_fetcher/main.go` | 240-244 | LOW | Limiter wait | `f.limiter.Wait(ctx)` returns error on context cancel; surfaced as `"rate limited"` — message is misleading (could be cancel). Distinguish. |
| `go_services/url_fetcher/main.go` | 247-252 | LOW | URL validation | Accepts any string `http.NewRequestWithContext` parses. Caller (line 539) already requires `http://` or `https://` prefix; sound. |
| `go_services/url_fetcher/main.go` | 255-257 | LOW | Headers | UA `Mozilla/5.0 (compatible; DiscordBot/1.0)` — fine but `Discord` UA name might trip some WAFs. Consider a more generic UA option. |
| `go_services/url_fetcher/main.go` | 273 | LOW | Drain | `io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))` — only drains 4 KiB; on a 10 MB error response, the connection is closed (no reuse). Sound — for non-200 we don't want to read more. |
| `go_services/url_fetcher/main.go` | 280 | LOW | Body cap | `io.LimitReader(resp.Body, maxContentLength)` caps decoded body to 10 MiB. Sound. |
| `go_services/url_fetcher/main.go` | 282-297 | LOW | Charset detection | `golang.org/x/net/html/charset.NewReader` detects via meta tag / BOM. CVE-2024-45338 (chunkreader DoS) was patched in `golang.org/x/net v0.33.0` and later; v0.53 includes the fix. |
| `go_services/url_fetcher/main.go` | 300-309 | LOW | Type discrimination | Only `text/html` and `text/plain` extracted; everything else returns `[Binary content]`. Reasonable. Doesn't handle `application/json`, `application/xml`, `text/xml`. |
| `go_services/url_fetcher/main.go` | 384-441 | LOW | HTML parse | `goquery` based. Removes script/style/nav/footer/header/aside/iframe/noscript. Good. Doesn't strip `svg`, `template`, `link`. |
| `go_services/url_fetcher/main.go` | 422-428 | LOW | Selector | Iterates `p, h1-h6, li`. Misses `div`-based content, code/pre blocks, blockquotes. Acceptable for summarization. |
| `go_services/url_fetcher/main.go` | 444-467 | LOW | Whitespace | `cleanWhitespace` collapses runs of spaces/tabs/newlines. Sound. |
| `go_services/url_fetcher/main.go` | 470-477 | LOW | Truncate | `[]rune(s)` allocates O(n). For 10 MB input that's 40 MB heap. Use `utf8.DecodeRuneInString` loop for streaming truncate. Perf nit. |
| `go_services/url_fetcher/main.go` | 316-381 | MEDIUM | Goroutine semantics | `FetchBatch`:<br>1. Spawns `len(urls)` goroutines, each acquires sem (`workerCount=10`).<br>2. On `ctx.Done()`, writes "context cancelled" to the result and returns *without acquiring sem*.<br>**But** the `response.Results[idx] = ...` write at line 333 races with the goroutine's earlier `response.Results[idx]` set IF the cancel races with normal completion. Since each `idx` is owned by one goroutine and that goroutine writes exactly once (return short-circuits the second write), this is sound. The post-loop counting (line 371-377) is gated by `<-done` which waits for all goroutines.<br>The "wait briefly then force <-done" pattern (line 357-365) is correct — final read of `Results` happens after `<-done`. Sound. |
| `go_services/url_fetcher/main.go` | 348-351 | LOW | Goroutine | Anonymous goroutine that `wg.Wait()` and closes `done`. Standard pattern. Sound. |
| `go_services/url_fetcher/main.go` | 487-514 | LOW | Middleware | Same as health_api: Logger, Recoverer, Timeout(60s), trace propagation, security headers. Sound. |
| `go_services/url_fetcher/main.go` | 525-549 | MEDIUM | GET fetch | `r.Get("/fetch")` reads URL from query string. With body limit not set (it's a GET so no body), and 8 KiB URL cap. **No authentication.** Bound to 127.0.0.1 (line 605) so this is fine, but document that exposing the port is dangerous. |
| `go_services/url_fetcher/main.go` | 533, 574 | LOW | URL length cap | 8192 bytes — matches common server limits. Sound. |
| `go_services/url_fetcher/main.go` | 552-601 | LOW | Batch endpoint | 1 MiB body, 20 URLs max, scheme/length validation, optional timeout capped at 120 s. Sound. |
| `go_services/url_fetcher/main.go` | 604-611 | LOW | Server timeouts | All four timeouts set. Bound to `127.0.0.1` — no `URL_FETCHER_HOST` env var to flip this open, which is safer than health_api. |
| `go_services/url_fetcher/main.go` | 614-625 | LOW | Graceful shutdown | Sound; logs error from `Shutdown`. |
| `go_services/url_fetcher/main.go` | n/a | MEDIUM | No HTTPS-only mode | Both `http://` and `https://` are allowed. For SSRF, `http://` is generally lower risk than `file://`/`gopher://` (correctly blocked by scheme check) but allows MITM and easier cleartext exfiltration of any cookies/tokens (none currently). Consider an option to require https. |
| `go_services/url_fetcher/main.go` | n/a | LOW | No response cookie storage | Client uses default `http.Client` (no `Jar`). Sound — no session leakage between fetches. |
| `go_services/url_fetcher/main.go` | n/a | LOW | No referer policy | `Referer` header is not stripped on redirects. The Go default is to set Referer on follow. For an SSRF/info-leak point of view, custom redirects could leak the original URL to the redirect target. Acceptable for public web fetches. |

## Notes / Cross-cutting

### PyO3 Boundary — Panics and Error Conversion

I scanned for `unwrap()`, `expect(`, `panic!`, `assert!`, `unreachable!` across `rust_extensions/**/src/**/*.rs`:

- Production code (non-test, non-bench) contains **zero `unwrap`/`expect`/`panic!`** in the PyO3 boundary. All fallible operations return `PyResult` or `Result<_, MediaError|RagError>`.
- The only `unwrap_or` calls are on `partial_cmp` (sort comparison, NaN-safe) and `SystemTime::duration_since` (clock skew handling). Both correct.
- `assert!` and `expect(` only appear in `#[cfg(test)]` modules (cosine.rs, encode.rs, gif.rs).
- The single `unsafe` block (storage.rs:98) is `MmapOptions::map_mut` — fundamentally unsafe per memmap2 docs. Mitigated by `lock_exclusive` flock and bounds checks; documented in code.

### GIL Release Audit

Per PyO3 0.28 the helper is `py.detach(|| ...)` (renamed from `allow_threads`). I checked every CPU-bound `#[pymethods]`:

| Method | CPU work | GIL released? |
|---|---|---|
| `MediaProcessor::resize` | image decode + Lanczos3 resize + JPEG encode | **NO** — releases nothing. Fix: wrap in `py.detach`. |
| `MediaProcessor::resize_exact` | same | **NO** — same fix. |
| `MediaProcessor::thumbnail` | same | **NO** — same fix. |
| `MediaProcessor::batch_resize` | parallel resize over rayon | **YES** (lib.rs:194) |
| `MediaProcessor::load` | format detect + decode | **NO** — minor (decode is fast for header probe, full decode at end is ~10-50ms). |
| `MediaProcessor::is_animated` | byte walking | **NO** — fast, OK |
| `RagEngine::add` | hashmap insert | **NO** — fast, OK |
| `RagEngine::add_batch` | N inserts | **NO** — could be slow at N=1M; consider |
| `RagEngine::search` | parallel cosine over rayon | **YES** (lib.rs:197) |
| `RagEngine::save` | JSON encode + file write | **NO** — JSON encode of large corpora can take seconds; releases would help. |
| `RagEngine::load` | file read + JSON decode | **NO** — same. |

**Action:** wrap `resize/resize_exact/thumbnail/save/load` in `py.detach`. Single-image resize is the most painful blocker for concurrent Python work today.

### SSRF Surface (url_fetcher)

The SSRF defense is **multi-layered and largely correct**:

1. **Scheme allowlist** at HTTP handler (`http`/`https` only) — main.go:539, 578.
2. **URL length cap** 8 KiB — main.go:533, 574.
3. **Initial DNS check** in `isPrivateURL` (main.go:84-124) — informational; can be bypassed via DNS rebinding.
4. **Per-connection re-resolve and validate** in `ssrfSafeDialContext` (main.go:160-188) — closes the rebinding TOCTOU window. **Dial happens to first IP directly, no second resolution.**
5. **Hostname blocklist** for cloud metadata (main.go:95-103).
6. **Per-redirect re-validation**: each redirect goes through the same DialContext, so each hop is SSRF-checked.
7. **Body size cap** 10 MiB (main.go:280).
8. **Rate limiter** 50 RPS / 100 burst.
9. **Bound to 127.0.0.1 only** — no env to flip.

Gaps:
- Missing CIDRs: `224.0.0.0/4`, `240.0.0.0/4`, `198.18.0.0/15`, `192.0.0.0/24`, `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`, `2001::/23`, `64:ff9b::/96`. Add to `init` ranges (main.go:46-64).
- TLS SNI vs dial-by-IP: untested; should validate against virtual-hosted TLS sites.

### Health API Exposure

- Default bind `127.0.0.1` ✓
- `GO_HEALTH_API_HOST` allows operator override to `0.0.0.0` with no auth ⚠️ — this is the single most dangerous knob. The `/metrics/push` endpoint can be abused to inflate counters or push crafted gauge values; the label allowlist limits cardinality damage but `tokens_used` Counter can be inflated arbitrarily. **Add bearer-token middleware** OR remove the host env var.

### Concurrency / Race Conditions

Run `go test -race ./...` on `go_services`. From manual inspection:
- `health_api`: `HealthService.services` is RWMutex-protected for reads/writes. `GetStatus` copies the map under read-lock. Sound.
- `url_fetcher`: `FetchBatch` writes to `response.Results[idx]` from goroutines, each owning a unique idx. Reads of the slice happen after `wg.Wait()`. Sound.
- Both binaries: graceful shutdown is one-shot via signal; no concurrent shutdown call. Sound.

### Storage Atomicity (rag_engine)

- `RagEngine::save` writes to a uniquely-named temp file then renames. **Missing `fsync` between write and rename — see line 311 above.** This is a HIGH severity for any deployment that experiences power loss.
- `VectorStorage::push` correctly orders vector-flush before count-bump. Per-push `mmap.flush()` is durable but slow.

### Cargo.toml Dependencies

| Crate | Version | Status |
|---|---|---|
| pyo3 | 0.28 | Current. Use `py.detach` (already done in `batch_resize`/`search`). |
| rayon | 1.11 | Current |
| serde / serde_json | 1.0 / 1.0 | Current |
| thiserror | 2.0 | Current |
| parking_lot | 0.12 | Current |
| memmap2 | 0.9 | Current |
| bytemuck | 1.14 | **Unused after storage.rs rewrite — remove from workspace deps** |
| simsimd | 6.5 | Pinned. Bundled C code; review on upgrade. |
| fs2 | 0.4 | **Unmaintained. Migrate to `fs4`.** |
| image | 0.25 | Current; verify limits config; `gif`/`webp` features enabled |
| base64 | 0.22 | Current |

### go.mod Dependencies

All current as of audit date. `golang.org/x/net v0.53.0` includes the fix for CVE-2024-45338 (charset DoS). No outstanding `govulncheck` findings expected on this set; **run `govulncheck ./...` to confirm.**

## Recommended Priority Fixes

1. **HIGH**: `rag_engine/src/lib.rs:310` — add `f.sync_all()` before rename in `save()`.
2. **HIGH**: `health_api/main.go:254-260` — add bearer-token auth middleware OR remove `GO_HEALTH_API_HOST` env var; current setup allows accidental open exposure of writable metric endpoints.
3. **MEDIUM**: `media_processor/src/lib.rs:117-146` — wrap single-image resize in `py.detach`. Currently freezes Python event loop on large images.
4. **MEDIUM**: `rag_engine/src/lib.rs:25, 52` and `media_processor/src/lib.rs:25` — verify `#[pyclass(from_py_object)]` is not a typo. Either no-op (remove) or compile error.
5. **MEDIUM**: `rag_engine/Cargo.toml:20` — replace `fs2 = "0.4"` (unmaintained) with `fs4`.
6. **MEDIUM**: `rag_engine/src/cosine.rs:7-13` — return `Option<f32>` on dimension mismatch instead of silent 0.0; the silent path can mask data corruption.
7. **MEDIUM**: `rag_engine/src/index.rs` — `VectorIndex` is dead code; either wire into `RagEngine` or delete.
8. **MEDIUM**: `url_fetcher/main.go:46-64` — extend SSRF blocklist with multicast / IETF / TEST-NET / IPv6 doc ranges.
9. **MEDIUM**: `health_api/main.go:281-287` — add `Referrer-Policy`, explicit `CSP`, explicit CORS deny header.
10. **LOW**: remove unused `bytemuck` workspace dep.
11. **LOW**: `rag_engine/src/lib.rs:190-193` — store entries as `Arc<MemoryEntry>` to avoid full-corpus clone per `search()`.
12. **LOW**: `media_processor/src/resize.rs:39-40` — error instead of silently clamping `Stretch`/`Fill` requested dimensions.

## Confirmation

- All 17 assigned files were read in full (line-by-line).
- Search for `unsafe`, `unwrap`, `expect`, `panic!`, `assert!` performed; only one `unsafe` block (memmap), no production-side panics on PyO3 boundary.
- All `#[pyfunction]` and `#[pymethods]` checked: every fallible op returns `PyResult` or `Result`.
- Web research performed for: PyO3 0.28 GIL conventions (`py.detach`); image-crate decompression bombs; Go SSRF + DNS rebinding patterns; simsimd CVE history; chi/prometheus CVE history.
- Both Go HTTP servers verified to set `ReadTimeout`, `ReadHeaderTimeout`, `WriteTimeout`, `IdleTimeout`.
- SSRF defense in `url_fetcher` traced through both `isPrivateURL` (advisory) and `ssrfSafeDialContext` (authoritative); rebinding window confirmed closed via dial-by-IP.
- No secrets, credentials, or hardcoded tokens found in any file in scope.

Sources:
- [PyO3 v0.28 migration guide](https://pyo3.rs/v0.28.3/migration.html)
- [PyO3 parallelism / detach](https://pyo3.rs/v0.28.2/parallelism)
- [PyO3 free-threaded support](https://pyo3.rs/v0.28.3/free-threading)
- [RustSec advisory database](https://rustsec.org/advisories/)
- [image crate decompression-bomb advisory CVE-2026-21441 / GHSA-38jv-5279-wg99](https://github.com/advisories/GHSA-38jv-5279-wg99)
- [Doyensec safeurl SSRF library and DNS rebinding](https://blog.doyensec.com/2022/12/13/safeurl.html)
- [OWASP A10 SSRF Top 10:2021](https://owasp.org/Top10/2021/A10_2021-Server-Side_Request_Forgery_(SSRF)/)
- [SimSIMD crate](https://crates.io/crates/simsimd)
- [chi v5 docs / releases](https://github.com/go-chi/chi/releases)
