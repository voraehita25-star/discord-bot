//! RAG Engine - High-performance vector similarity search
//!
//! A Rust-based RAG (Retrieval-Augmented Generation) engine with:
//! - SIMD-optimized cosine similarity
//! - Parallel search with Rayon

mod cosine;
mod errors;

use parking_lot::RwLock;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::sync::Arc;

pub use cosine::cosine_similarity;
pub use errors::RagError;

/// A single memory entry with embedding and metadata
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct MemoryEntry {
    #[pyo3(get)]
    pub id: String,
    #[pyo3(get)]
    pub text: String,
    #[pyo3(get)]
    pub timestamp: f64,
    #[pyo3(get)]
    pub importance: f32,
    pub embedding: Vec<f32>,
}

#[pymethods]
impl MemoryEntry {
    #[new]
    fn new(id: String, text: String, embedding: Vec<f32>, timestamp: f64, importance: f32) -> Self {
        Self {
            id,
            text,
            embedding,
            timestamp,
            importance,
        }
    }

    fn get_embedding(&self) -> Vec<f32> {
        self.embedding.clone()
    }
}

/// Search result with score
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct SearchResult {
    #[pyo3(get)]
    pub id: String,
    #[pyo3(get)]
    pub text: String,
    #[pyo3(get)]
    pub score: f32,
    #[pyo3(get)]
    pub timestamp: f64,
}

/// Reject path-traversal attempts on user-supplied save/load paths.
///
/// Kept as a free function rather than a method because pyo3's `#[pymethods]`
/// can't expose `&Path`-taking methods, but we still want the Path-based
/// component walk for correctness on Windows drive prefixes (`C:foo`) which
/// `Path::is_absolute()` reports as relative.
fn validate_relative_path(p: &std::path::Path) -> PyResult<()> {
    use std::path::Component;
    if p.is_absolute() {
        return Err(PyValueError::new_err(
            "Path traversal blocked: absolute paths not allowed",
        ));
    }
    for component in p.components() {
        match component {
            Component::ParentDir => {
                return Err(PyValueError::new_err(
                    "Path traversal blocked: '..' not allowed",
                ));
            }
            Component::Prefix(_) => {
                // Windows drive letter / UNC prefix — disallowed on relative paths
                return Err(PyValueError::new_err(
                    "Path traversal blocked: drive prefix not allowed",
                ));
            }
            Component::RootDir => {
                // A rooted-but-driveless path ("\\foo" / "/foo") — on Windows
                // Path::is_absolute() reports these as relative, but they resolve
                // against the current drive's root and escape the project base.
                return Err(PyValueError::new_err(
                    "Path traversal blocked: rooted path not allowed",
                ));
            }
            _ => {}
        }
    }
    Ok(())
}

/// Reject a path whose any *intermediate directory* component is a symlink.
///
/// `validate_relative_path` is purely lexical and the leaf-only
/// `symlink_metadata` check used by save()/load() stats only the final
/// component, so a relative path like `subdir/x.json` where `subdir` is a
/// directory symlink pointing outside the project root would slip through
/// (no `..`, no Prefix/RootDir, and the leaf `x.json` is a regular file).
/// This walks every ancestor directory of `p` and refuses if any *existing*
/// component is a symlink. Non-existent components are skipped — for save()
/// the leaf does not exist yet, and a missing intermediate dir will surface
/// as the real File::create/open error downstream; we only fail-closed on a
/// *confirmed* symlink. Callers must still apply the leaf symlink check
/// separately (load() does; save() does so guarded on existence).
fn reject_symlinked_components(p: &std::path::Path) -> PyResult<()> {
    // Walk ancestor prefixes excluding the full path itself (the leaf is
    // handled by the callers' own symlink_metadata check). `ancestors()`
    // yields the path then each parent; skip(1) drops the leaf.
    for ancestor in p.ancestors().skip(1) {
        if ancestor.as_os_str().is_empty() {
            continue;
        }
        match std::fs::symlink_metadata(ancestor) {
            Ok(meta) => {
                if meta.file_type().is_symlink() {
                    return Err(PyValueError::new_err(
                        "Path traversal blocked: symlinked directory component not allowed",
                    ));
                }
            }
            // A component that does not exist (NotFound) is fine here — the
            // later open/create will produce the authoritative error. Any
            // other stat error (e.g. permission) is also non-fatal for this
            // guard; the real I/O below will surface it.
            Err(_) => continue,
        }
    }
    Ok(())
}

/// Main RAG Engine class
#[pyclass]
pub struct RagEngine {
    entries: Arc<RwLock<HashMap<String, MemoryEntry>>>,
    dimension: usize,
    similarity_threshold: f32,
}

#[pymethods]
impl RagEngine {
    #[new]
    #[pyo3(signature = (dimension=384, similarity_threshold=0.7))]
    fn new(dimension: usize, similarity_threshold: f32) -> Self {
        Self {
            entries: Arc::new(RwLock::new(HashMap::new())),
            dimension,
            similarity_threshold,
        }
    }

    /// Add a memory entry
    fn add(&self, entry: MemoryEntry) -> PyResult<()> {
        if entry.embedding.len() != self.dimension {
            return Err(PyValueError::new_err(format!(
                "Embedding dimension mismatch: expected {}, got {}",
                self.dimension,
                entry.embedding.len()
            )));
        }
        // Validate importance is finite to prevent NaN/Infinity score corruption
        if !entry.importance.is_finite() {
            return Err(PyValueError::new_err("importance must be a finite number"));
        }
        // Importance is a non-negative weight (calculate_importance clamps to
        // [0.0, 2.0]). A negative importance flips the sign of final_score in
        // search() (final_score = base_score * decay * importance); since the
        // cosine base_score is in [-1, 1], a negative weight on an OPPOSITE-meaning
        // memory (base_score < 0) yields a POSITIVE score that can pass the
        // threshold and surface a maximally-irrelevant hit. Enforce the invariant
        // at the trust boundary.
        if entry.importance < 0.0 {
            return Err(PyValueError::new_err("importance must be non-negative"));
        }
        // Embedding values must also be finite — a single NaN/Inf in the
        // vector would later make save() fail (serde_json refuses non-finite
        // floats) and silently degrades cosine similarity at query time.
        if entry.embedding.iter().any(|v| !v.is_finite()) {
            return Err(PyValueError::new_err(
                "embedding contains non-finite values (NaN/Inf)",
            ));
        }
        // Timestamp must be finite too — a non-finite value serializes to JSON
        // null in save() and is silently dropped on the next load(), so guard it
        // here to keep the stored-data invariant consistent with importance/embedding.
        if !entry.timestamp.is_finite() {
            return Err(PyValueError::new_err("timestamp must be a finite number"));
        }

        let mut entries = self.entries.write();
        entries.insert(entry.id.clone(), entry);
        Ok(())
    }

    /// Add multiple entries in batch
    ///
    /// Silent-skip contract: unlike single-entry `add()` (which raises
    /// PyValueError on a bad entry), this method silently drops any entry that
    /// fails dimension / finite-importance / finite-embedding validation and
    /// returns only the count actually inserted. The returned count can
    /// therefore be less than `entries_list.len()` for a malformed batch.
    fn add_batch(&self, entries_list: Vec<MemoryEntry>) -> PyResult<usize> {
        let mut entries = self.entries.write();
        let mut added = 0;

        for entry in entries_list {
            if entry.embedding.len() == self.dimension
                && entry.importance.is_finite()
                && entry.importance >= 0.0
                && entry.embedding.iter().all(|v| v.is_finite())
                && entry.timestamp.is_finite()
            {
                // Count only newly inserted ids — HashMap::insert returns
                // Some(old) when the id already existed (de-dupe replace), so a
                // batch with duplicate ids must not over-report. Keeps the
                // returned count == net growth in engine size (parity with load()).
                if entries.insert(entry.id.clone(), entry).is_none() {
                    added += 1;
                }
            }
        }

        Ok(added)
    }

    /// Remove an entry by ID
    fn remove(&self, id: &str) -> bool {
        let mut entries = self.entries.write();
        entries.remove(id).is_some()
    }

    /// Search for similar entries (parallel SIMD-optimized)
    #[pyo3(signature = (query_embedding, top_k=5, time_decay_factor=0.0))]
    fn search(
        &self,
        py: Python<'_>,
        query_embedding: Vec<f32>,
        top_k: usize,
        time_decay_factor: f64,
    ) -> PyResult<Vec<SearchResult>> {
        if query_embedding.len() != self.dimension {
            return Err(PyValueError::new_err(format!(
                "Query dimension mismatch: expected {}, got {}",
                self.dimension,
                query_embedding.len()
            )));
        }
        // Validate query is finite — match add()'s guarantees so we never
        // silently let a NaN slip into cosine_similarity. The threshold filter
        // below would catch NaN scores by accident (NaN >= x is false), but
        // an Inf in the query produces an Inf score that passes the filter
        // and torpedoes the rank order.
        if query_embedding.iter().any(|v| !v.is_finite()) {
            return Err(PyValueError::new_err(
                "query_embedding contains non-finite values (NaN/Inf)",
            ));
        }

        // Clone data under read lock so we can release GIL during computation
        let entries_snapshot: Vec<_> = {
            let entries = self.entries.read();
            entries.values().cloned().collect()
        };
        let similarity_threshold = self.similarity_threshold;

        // Release GIL during CPU-intensive parallel computation
        py.detach(|| {
            use rayon::prelude::*;

            let current_time = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0);

            // Filter out NaN scores and below-threshold results
            let mut results: Vec<SearchResult> = entries_snapshot
                .par_iter()
                .map(|entry| {
                    let base_score = cosine_similarity(&query_embedding, &entry.embedding);

                    // Apply time decay if factor > 0
                    let final_score = if time_decay_factor > 0.0 {
                        // Clamp age to >= 0 to prevent score inflation for future timestamps
                        // Clamp time_decay_factor to sane range to prevent overflow
                        let clamped_decay = time_decay_factor.clamp(0.0, 1.0);
                        let age_hours = ((current_time - entry.timestamp) / 3600.0).max(0.0);
                        let decay = (-clamped_decay * age_hours).exp() as f32;
                        base_score * decay * entry.importance
                    } else {
                        base_score * entry.importance
                    };

                    SearchResult {
                        id: entry.id.clone(),
                        text: entry.text.clone(),
                        score: if final_score.is_finite() {
                            final_score
                        } else {
                            0.0
                        },
                        timestamp: entry.timestamp,
                    }
                })
                .filter(|r| r.score >= similarity_threshold)
                .collect();

            // Sort by score descending
            results.sort_by(|a, b| {
                b.score
                    .partial_cmp(&a.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            results.truncate(top_k);

            Ok(results)
        })
    }

    /// Get entry count
    fn len(&self) -> usize {
        self.entries.read().len()
    }

    /// Check if empty
    fn is_empty(&self) -> bool {
        self.entries.read().is_empty()
    }

    /// Clear all entries
    fn clear(&self) {
        self.entries.write().clear();
    }

    /// Get all entry IDs
    fn get_ids(&self) -> Vec<String> {
        self.entries.read().keys().cloned().collect()
    }

    /// Get entry by ID
    fn get(&self, id: &str) -> Option<MemoryEntry> {
        self.entries.read().get(id).cloned()
    }

    /// Compute cosine similarity between two vectors
    #[staticmethod]
    fn compute_similarity(a: Vec<f32>, b: Vec<f32>) -> PyResult<f32> {
        if a.len() != b.len() {
            return Err(PyValueError::new_err("Vector dimensions must match"));
        }
        // Match the finite-value guarantee enforced by add()/search()/load() —
        // an Inf/NaN here would otherwise leak a non-finite/misleading score
        // (Inf norm -> denom=Inf -> dot/denom = 0.0 or NaN) back to Python.
        if a.iter().chain(b.iter()).any(|v| !v.is_finite()) {
            return Err(PyValueError::new_err(
                "vectors contain non-finite values (NaN/Inf)",
            ));
        }
        Ok(cosine_similarity(&a, &b))
    }

    /// Save to JSON file (atomic write via temp file + rename)
    fn save(&self, path: &str) -> PyResult<()> {
        // Path traversal protection: reject ".." components, absolute paths,
        // and Windows drive prefixes (Component::Prefix) — the previous check
        // missed Prefix, so on Windows a relative path starting with a drive
        // letter (e.g. "C:foo") could escape the project root.
        let save_path = std::path::Path::new(path);
        validate_relative_path(save_path)?;
        // Defense-in-depth: refuse a symlinked intermediate directory (a
        // lexically-clean relative path can still point outside the project
        // root through a directory symlink), and refuse to write THROUGH an
        // existing leaf symlink (File::create follows symlinks). load() has
        // had the leaf check; save() previously had none, so even a final-
        // component symlink was followed on write.
        reject_symlinked_components(save_path)?;
        if let Ok(meta) = std::fs::symlink_metadata(save_path) {
            if meta.file_type().is_symlink() {
                return Err(PyValueError::new_err(
                    "Path traversal blocked: symlinked save path not allowed",
                ));
            }
        }

        let entries = self.entries.read();
        let data: Vec<_> = entries
            .values()
            .map(|e| {
                serde_json::json!({
                    "id": e.id,
                    "text": e.text,
                    "embedding": e.embedding,
                    "timestamp": e.timestamp,
                    "importance": e.importance,
                })
            })
            .collect();

        let json = serde_json::to_string_pretty(&data)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;

        // Atomic write: write to a *unique* temp file, then rename. The
        // previous implementation always used `<path>.tmp`, so two save()
        // calls racing on the same path would clobber each other's temp file
        // mid-write, producing a corrupt JSON. We append the OS PID, the wall
        // clock nanos, AND a process-wide atomic counter. The counter is the
        // load-bearing part: SystemTime::now().as_nanos() does NOT advance on
        // every read on Windows (coarse clock — consecutive reads can return
        // identical nanos), so two same-process threads saving the same path
        // within one clock tick would otherwise get an identical pid+nanos and
        // thus the SAME temp name. fetch_add guarantees each save() in this
        // process gets a distinct suffix regardless of clock resolution.
        static TEMP_COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let pid = std::process::id();
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let seq = TEMP_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let temp_path = format!("{}.tmp.{}.{}.{}", path, pid, nanos, seq);

        // Write + fsync the temp file before renaming. Without sync_all(),
        // the bytes may live only in the OS page cache; a power loss after
        // the rename leaves the live file truncated/empty because the
        // rename was atomic on the directory entry but the data pages were
        // never flushed to stable storage. Use the explicit File API so we
        // can call sync_all() on the handle.
        //
        // Durability caveat: we fsync the file *data* (temp here, and the
        // destination on the copy fallback below) but do NOT fsync the
        // containing directory after the rename/create. On POSIX the
        // rename's directory entry can therefore still be lost on power
        // loss even though the data pages are durable, leaving either the
        // old file or no file. This gap is acceptable here: the target
        // platform is Windows (different ReplaceFile/rename durability
        // semantics) and RAG dumps are cheaply regenerable.
        {
            use std::io::Write;
            let mut f = std::fs::File::create(&temp_path)
                .map_err(|e| PyValueError::new_err(format!("create temp: {}", e)))?;
            f.write_all(json.as_bytes())
                .map_err(|e| PyValueError::new_err(format!("write temp: {}", e)))?;
            f.sync_all()
                .map_err(|e| PyValueError::new_err(format!("fsync temp: {}", e)))?;
        }

        // rename may fail on Windows if file is locked; fall back to copy+delete.
        if let Err(rename_err) = std::fs::rename(&temp_path, path) {
            match std::fs::copy(&temp_path, path) {
                Ok(_) => {
                    // copy() does NOT fsync the destination. fsync the
                    // destination file before deleting the temp so the new
                    // bytes are durable; otherwise a crash here can leave
                    // both copies present but the destination empty.
                    {
                        match std::fs::OpenOptions::new().write(true).open(path) {
                            Ok(f) => {
                                if let Err(e) = f.sync_all() {
                                    // Clean up the temp before bailing, matching
                                    // every other save() exit path; the temp name
                                    // is unique per call, so leaving it here piles
                                    // up orphaned `.tmp.*` files on repeat failures.
                                    let _ = std::fs::remove_file(&temp_path);
                                    return Err(PyValueError::new_err(format!(
                                        "fsync after copy failed: {}",
                                        e
                                    )));
                                }
                            }
                            Err(e) => {
                                let _ = std::fs::remove_file(&temp_path);
                                return Err(PyValueError::new_err(format!(
                                    "open dest for fsync failed: {}",
                                    e
                                )));
                            }
                        }
                    }
                    let _ = std::fs::remove_file(&temp_path);
                }
                Err(copy_err) => {
                    let _ = std::fs::remove_file(&temp_path);
                    return Err(PyValueError::new_err(format!(
                        "rename failed: {}, copy fallback failed: {}",
                        rename_err, copy_err
                    )));
                }
            }
        }

        Ok(())
    }

    /// Load from JSON file (replaces all existing entries)
    fn load(&self, path: &str) -> PyResult<usize> {
        let load_path = std::path::Path::new(path);
        validate_relative_path(load_path)?;
        // Defense-in-depth: the leaf symlink_metadata check below only stats
        // the final component, so a symlinked intermediate directory would let
        // a lexically-clean relative path resolve outside the project root.
        // Refuse any symlinked ancestor directory before the leaf check.
        reject_symlinked_components(load_path)?;

        // Size limit (256 MiB) to prevent OOM from malicious/corrupt files.
        // RAG dumps are expected to be small (few MB); 256 MiB is a generous cap.
        const MAX_LOAD_BYTES: u64 = 256 * 1024 * 1024;

        // Use ``symlink_metadata`` rather than ``metadata`` so we can refuse
        // to follow symlinks — combined with the path-component check above,
        // a relative ``subdir/symlink_to_outside`` would otherwise pass the
        // traversal check and resolve to anywhere on disk via stat.
        let symlink_meta = std::fs::symlink_metadata(path)
            .map_err(|e| PyValueError::new_err(format!("stat failed: {}", e)))?;
        if symlink_meta.file_type().is_symlink() {
            return Err(PyValueError::new_err(
                "Path traversal blocked: symlinked load path not allowed",
            ));
        }
        if symlink_meta.len() > MAX_LOAD_BYTES {
            return Err(PyValueError::new_err(format!(
                "File too large to load: {} bytes (max {})",
                symlink_meta.len(),
                MAX_LOAD_BYTES
            )));
        }

        // Read with an explicit byte cap rather than ``read_to_string``, so a
        // file that grows between the size check above and this read can't
        // silently exceed our cap (a TOCTOU window). Reading one extra byte
        // beyond the cap lets us detect attempted overflow and reject it.
        use std::io::Read;
        let mut file = std::fs::File::open(path)
            .map_err(|e| PyValueError::new_err(format!("open failed: {}", e)))?;
        let mut buf =
            Vec::with_capacity((symlink_meta.len() as usize).min(MAX_LOAD_BYTES as usize));
        let read_cap = MAX_LOAD_BYTES.saturating_add(1);
        file.by_ref()
            .take(read_cap)
            .read_to_end(&mut buf)
            .map_err(|e| PyValueError::new_err(format!("read failed: {}", e)))?;
        if buf.len() as u64 > MAX_LOAD_BYTES {
            return Err(PyValueError::new_err(format!(
                "File grew past size cap mid-read (max {} bytes)",
                MAX_LOAD_BYTES
            )));
        }
        let data = String::from_utf8(buf)
            .map_err(|e| PyValueError::new_err(format!("file is not UTF-8: {}", e)))?;

        let entries_data: Vec<serde_json::Value> =
            serde_json::from_str(&data).map_err(|e| PyValueError::new_err(e.to_string()))?;

        // Build new entries in a temporary map first to avoid data loss on bad files
        let mut new_entries = HashMap::new();

        for item in &entries_data {
            if let (Some(id), Some(text), Some(embedding), Some(timestamp), Some(importance)) = (
                item["id"].as_str(),
                item["text"].as_str(),
                item["embedding"].as_array(),
                item["timestamp"].as_f64(),
                item["importance"].as_f64(),
            ) {
                let emb: Vec<f32> = embedding
                    .iter()
                    .filter_map(|v| {
                        v.as_f64().and_then(|f| {
                            let val = f as f32;
                            if val.is_finite() {
                                Some(val)
                            } else {
                                None
                            }
                        })
                    })
                    .collect();

                if emb.len() == self.dimension {
                    let imp = importance as f32;
                    if !imp.is_finite() {
                        continue; // Skip entries with NaN/Infinity importance
                    }
                    if imp < 0.0 {
                        continue; // Skip negative importance — a negative weight
                                  // flips final_score's sign in search() and can
                                  // rank an opposite-meaning memory above threshold.
                    }
                    if !timestamp.is_finite() {
                        continue; // Skip entries with NaN/Infinity timestamp — keep
                                  // the stored-data invariant consistent with importance/embedding
                    }
                    new_entries.insert(
                        id.to_string(),
                        MemoryEntry {
                            id: id.to_string(),
                            text: text.to_string(),
                            embedding: emb,
                            timestamp,
                            importance: imp,
                        },
                    );
                }
            }
        }

        // Only replace existing data if we loaded at least some entries,
        // or if the source file was intentionally empty
        if new_entries.is_empty() && !entries_data.is_empty() {
            return Err(PyValueError::new_err(
                "No entries matched the expected dimension; refusing to replace existing data",
            ));
        }

        // Swap in the new entries atomically. Report the ACTUAL stored count —
        // HashMap de-dupes by id, so a file with duplicate ids stores fewer than
        // the iteration count; len() keeps the reported count == engine size.
        let count = new_entries.len();
        let mut entries = self.entries.write();
        *entries = new_entries;

        Ok(count)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;
    use std::sync::Mutex;

    // ---- Lexical path-traversal guard (interpreter-free) ----------------

    #[test]
    fn validate_relative_path_accepts_clean_relative() {
        assert!(validate_relative_path(Path::new("data.json")).is_ok());
        assert!(validate_relative_path(Path::new("subdir/data.json")).is_ok());
        assert!(validate_relative_path(Path::new("a/b/c.json")).is_ok());
    }

    #[test]
    fn validate_relative_path_rejects_absolute() {
        // POSIX-style absolute.
        assert!(validate_relative_path(Path::new("/etc/passwd")).is_err());
        // Windows absolute drive path.
        #[cfg(windows)]
        assert!(validate_relative_path(Path::new("C:\\Windows\\system32")).is_err());
    }

    #[test]
    fn validate_relative_path_rejects_parent_dir() {
        assert!(validate_relative_path(Path::new("../secret")).is_err());
        assert!(validate_relative_path(Path::new("subdir/../../secret")).is_err());
    }

    #[test]
    fn validate_relative_path_rejects_rootdir() {
        // A rooted-but-driveless path. On Windows Path::is_absolute() reports
        // these as relative, so the RootDir arm is what actually rejects them.
        assert!(validate_relative_path(Path::new("/foo")).is_err());
        #[cfg(windows)]
        assert!(validate_relative_path(Path::new("\\foo")).is_err());
    }

    #[cfg(windows)]
    #[test]
    fn validate_relative_path_rejects_drive_prefix() {
        // "C:foo" is a drive-relative path that Path::is_absolute() reports as
        // RELATIVE on Windows — only the Component::Prefix arm catches it. This
        // arm is unreachable from non-Windows hosts, so it MUST be exercised by
        // a Windows Rust test (the audit's rs-rag-1 point).
        assert!(validate_relative_path(Path::new("C:foo")).is_err());
        assert!(validate_relative_path(Path::new("c:bar\\baz.json")).is_err());
    }

    // ---- Filesystem-dependent tests ------------------------------------
    //
    // RagEngine::save/load/add are plain Rust methods (no Python<'_> arg) so
    // they are callable from cargo test without a Python interpreter. They use
    // RELATIVE paths, which validate_relative_path requires, so every test here
    // chdir's into a throwaway tempdir first. chdir is process-global and cargo
    // runs tests on parallel threads, so all CWD-mutating tests share one lock
    // to avoid racing on the working directory.
    static CWD_LOCK: Mutex<()> = Mutex::new(());

    fn unique_tempdir(tag: &str) -> std::path::PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let dir = std::env::temp_dir().join(format!(
            "rag_engine_test_{}_{}_{}",
            tag,
            std::process::id(),
            nanos
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn sample_entry(id: &str, dim: usize) -> MemoryEntry {
        MemoryEntry {
            id: id.to_string(),
            text: format!("text-{id}"),
            embedding: vec![0.1_f32; dim],
            timestamp: 1.0,
            importance: 0.5,
        }
    }

    #[test]
    fn save_load_round_trip_relative_path() {
        let _g = CWD_LOCK.lock().unwrap();
        let dir = unique_tempdir("roundtrip");
        let prev = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();

        let result = std::panic::catch_unwind(|| {
            let engine = RagEngine::new(4, 0.0);
            engine.add(sample_entry("a", 4)).unwrap();
            engine.add(sample_entry("b", 4)).unwrap();
            engine.save("dump.json").unwrap();

            let loaded = RagEngine::new(4, 0.0);
            let count = loaded.load("dump.json").unwrap();
            assert_eq!(count, 2);
            assert_eq!(loaded.len(), 2);
        });

        std::env::set_current_dir(prev).unwrap();
        let _ = std::fs::remove_dir_all(&dir);
        result.unwrap();
    }

    #[test]
    fn add_rejects_non_finite_embedding_and_importance() {
        // Interpreter-free: add() is a plain method. Finite-value rejection is a
        // security/robustness guard (a NaN/Inf in storage breaks save()/search).
        let engine = RagEngine::new(3, 0.0);
        let mut bad_emb = sample_entry("x", 3);
        bad_emb.embedding = vec![1.0, f32::NAN, 2.0];
        assert!(engine.add(bad_emb).is_err());

        let mut bad_inf = sample_entry("y", 3);
        bad_inf.embedding = vec![1.0, f32::INFINITY, 2.0];
        assert!(engine.add(bad_inf).is_err());

        let mut bad_imp = sample_entry("z", 3);
        bad_imp.importance = f32::NAN;
        assert!(engine.add(bad_imp).is_err());

        // Dimension mismatch is also rejected.
        assert!(engine.add(sample_entry("w", 2)).is_err());

        assert_eq!(engine.len(), 0);
    }

    #[test]
    fn add_batch_dedups_and_counts_net_growth() {
        let engine = RagEngine::new(3, 0.0);
        // Two distinct ids + one duplicate id + one malformed (wrong dim) entry.
        let mut malformed = sample_entry("bad", 2);
        malformed.text = "wrong-dim".to_string();
        let added = engine
            .add_batch(vec![
                sample_entry("a", 3),
                sample_entry("b", 3),
                sample_entry("a", 3), // duplicate id -> replace, not +1
                malformed,            // dropped silently
            ])
            .unwrap();
        // Net growth is 2 (a, b); duplicate replaces, malformed dropped.
        assert_eq!(added, 2);
        assert_eq!(engine.len(), 2);
    }

    #[test]
    fn add_rejects_negative_importance() {
        // A negative importance is finite but flips final_score's sign — reject it
        // at the trust boundary (rust-rag-M2). Distinct from the NaN/Inf check.
        let engine = RagEngine::new(3, 0.0);
        let mut neg = sample_entry("neg", 3);
        neg.importance = -0.5;
        assert!(engine.add(neg).is_err(), "negative importance must be rejected");
        // Zero is a valid weight (clamp lower bound) and must still be accepted.
        let mut zero = sample_entry("zero", 3);
        zero.importance = 0.0;
        assert!(engine.add(zero).is_ok(), "zero importance must be accepted");
        assert_eq!(engine.len(), 1);
    }

    #[test]
    fn add_batch_drops_negative_importance() {
        // Silent-skip contract: a negative-importance entry is dropped, not raised.
        let engine = RagEngine::new(3, 0.0);
        let mut neg = sample_entry("neg", 3);
        neg.importance = -1.0;
        let added = engine
            .add_batch(vec![sample_entry("ok", 3), neg])
            .unwrap();
        assert_eq!(added, 1, "only the non-negative entry should be inserted");
        assert_eq!(engine.len(), 1);
    }

    #[test]
    fn load_drops_negative_importance_entries() {
        let _g = CWD_LOCK.lock().unwrap();
        let dir = unique_tempdir("negimp");
        let prev = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();

        let result = std::panic::catch_unwind(|| {
            // Two entries, one with a negative importance which load() must skip.
            let json = r#"[
              {"id":"good","text":"g","embedding":[0.1,0.2,0.3,0.4],"timestamp":1.0,"importance":0.5},
              {"id":"neg","text":"n","embedding":[0.1,0.2,0.3,0.4],"timestamp":1.0,"importance":-0.5}
            ]"#;
            std::fs::write("neg.json", json).unwrap();

            let engine = RagEngine::new(4, 0.0);
            let count = engine.load("neg.json").unwrap();
            assert_eq!(count, 1, "only the non-negative-importance entry should load");
        });

        std::env::set_current_dir(prev).unwrap();
        let _ = std::fs::remove_dir_all(&dir);
        result.unwrap();
    }

    #[test]
    fn load_rejects_oversized_file_and_toctou() {
        let _g = CWD_LOCK.lock().unwrap();
        let dir = unique_tempdir("oversize");
        let prev = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();

        let result = std::panic::catch_unwind(|| {
            // 256 MiB is the cap; writing a file just over it must be rejected by
            // the symlink_metadata().len() check (the up-front size guard).
            const MAX_LOAD_BYTES: u64 = 256 * 1024 * 1024;
            use std::io::Write;
            let mut f = std::fs::File::create("big.json").unwrap();
            f.set_len(MAX_LOAD_BYTES + 16).unwrap();
            f.flush().unwrap();
            drop(f);

            let engine = RagEngine::new(4, 0.0);
            let err = engine.load("big.json");
            assert!(err.is_err(), "oversized file must be rejected");
        });

        std::env::set_current_dir(prev).unwrap();
        let _ = std::fs::remove_dir_all(&dir);
        result.unwrap();
    }

    #[test]
    fn load_refuses_to_replace_when_nothing_matches_dimension() {
        let _g = CWD_LOCK.lock().unwrap();
        let dir = unique_tempdir("nodim");
        let prev = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();

        let result = std::panic::catch_unwind(|| {
            // File has one entry but with the WRONG embedding dimension (2 vs 4),
            // so nothing matches and load() must refuse rather than wipe data.
            let json = r#"[{"id":"a","text":"t","embedding":[0.1,0.2],"timestamp":1.0,"importance":0.5}]"#;
            std::fs::write("mismatch.json", json).unwrap();

            let engine = RagEngine::new(4, 0.0);
            engine.add(sample_entry("existing", 4)).unwrap();
            let res = engine.load("mismatch.json");
            assert!(res.is_err(), "must refuse to replace when nothing matched");
            // Existing data must be untouched.
            assert_eq!(engine.len(), 1);
        });

        std::env::set_current_dir(prev).unwrap();
        let _ = std::fs::remove_dir_all(&dir);
        result.unwrap();
    }

    #[test]
    fn load_drops_non_finite_embedding_values_from_file() {
        let _g = CWD_LOCK.lock().unwrap();
        let dir = unique_tempdir("nonfinite");
        let prev = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();

        let result = std::panic::catch_unwind(|| {
            // null is JSON's way to smuggle a non-numeric — as_f64() returns
            // None and the value is filtered, so the embedding ends up shorter
            // than `dimension` and the whole entry is dropped (dim mismatch).
            let json = r#"[
              {"id":"good","text":"g","embedding":[0.1,0.2,0.3,0.4],"timestamp":1.0,"importance":0.5},
              {"id":"bad","text":"b","embedding":[0.1,null,0.3,0.4],"timestamp":1.0,"importance":0.5}
            ]"#;
            std::fs::write("mixed.json", json).unwrap();

            let engine = RagEngine::new(4, 0.0);
            let count = engine.load("mixed.json").unwrap();
            assert_eq!(count, 1, "only the all-finite entry should load");
        });

        std::env::set_current_dir(prev).unwrap();
        let _ = std::fs::remove_dir_all(&dir);
        result.unwrap();
    }

    // ---- Symlink refusal (Unix only — needs symlink syscall) -----------

    #[cfg(unix)]
    #[test]
    fn load_refuses_leaf_symlink() {
        use std::os::unix::fs::symlink;
        let _g = CWD_LOCK.lock().unwrap();
        let dir = unique_tempdir("leafsym");
        let prev = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();

        let result = std::panic::catch_unwind(|| {
            std::fs::write("real.json", "[]").unwrap();
            symlink("real.json", "link.json").unwrap();
            let engine = RagEngine::new(4, 0.0);
            assert!(engine.load("link.json").is_err(), "leaf symlink must be refused");
        });

        std::env::set_current_dir(prev).unwrap();
        let _ = std::fs::remove_dir_all(&dir);
        result.unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn save_and_load_refuse_symlinked_parent_directory() {
        use std::os::unix::fs::symlink;
        let _g = CWD_LOCK.lock().unwrap();
        let dir = unique_tempdir("parentsym");
        let prev = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();

        let result = std::panic::catch_unwind(|| {
            // `outside` is a real dir; `link_dir` is a symlink to it. A path
            // through link_dir is lexically clean and its leaf is a regular
            // file, so only the intermediate-symlink guard catches it.
            std::fs::create_dir("outside").unwrap();
            symlink("outside", "link_dir").unwrap();

            let engine = RagEngine::new(4, 0.0);
            engine.add(sample_entry("a", 4)).unwrap();
            // save() must refuse to write THROUGH the symlinked dir.
            assert!(
                engine.save("link_dir/dump.json").is_err(),
                "save through symlinked parent dir must be refused"
            );

            // And load() must refuse to read through it.
            std::fs::write("outside/dump.json", "[]").unwrap();
            let loader = RagEngine::new(4, 0.0);
            assert!(
                loader.load("link_dir/dump.json").is_err(),
                "load through symlinked parent dir must be refused"
            );
        });

        std::env::set_current_dir(prev).unwrap();
        let _ = std::fs::remove_dir_all(&dir);
        result.unwrap();
    }

    #[test]
    fn reject_symlinked_components_passes_for_real_dirs() {
        // A path through only-real directories must pass the intermediate guard.
        let _g = CWD_LOCK.lock().unwrap();
        let dir = unique_tempdir("realdirs");
        let prev = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();

        let result = std::panic::catch_unwind(|| {
            std::fs::create_dir_all("a/b").unwrap();
            assert!(reject_symlinked_components(Path::new("a/b/file.json")).is_ok());
            // Non-existent intermediates are skipped (not an error here).
            assert!(reject_symlinked_components(Path::new("does/not/exist.json")).is_ok());
        });

        std::env::set_current_dir(prev).unwrap();
        let _ = std::fs::remove_dir_all(&dir);
        result.unwrap();
    }
}

/// Python module
#[pymodule]
fn rag_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RagEngine>()?;
    m.add_class::<MemoryEntry>()?;
    m.add_class::<SearchResult>()?;

    // Version info
    m.add("__version__", "0.1.0")?;
    m.add("__author__", "voraehita25-star")?;

    Ok(())
}
