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
        // Embedding values must also be finite — a single NaN/Inf in the
        // vector would later make save() fail (serde_json refuses non-finite
        // floats) and silently degrades cosine similarity at query time.
        if entry.embedding.iter().any(|v| !v.is_finite()) {
            return Err(PyValueError::new_err(
                "embedding contains non-finite values (NaN/Inf)",
            ));
        }

        let mut entries = self.entries.write();
        entries.insert(entry.id.clone(), entry);
        Ok(())
    }

    /// Add multiple entries in batch
    fn add_batch(&self, entries_list: Vec<MemoryEntry>) -> PyResult<usize> {
        let mut entries = self.entries.write();
        let mut added = 0;

        for entry in entries_list {
            if entry.embedding.len() == self.dimension
                && entry.importance.is_finite()
                && entry.embedding.iter().all(|v| v.is_finite())
            {
                entries.insert(entry.id.clone(), entry);
                added += 1;
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
        // mid-write, producing a corrupt JSON. We append the OS PID and the
        // process-startup-relative nanos so two concurrent savers — even on
        // the same process — never share a temp name.
        let pid = std::process::id();
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let temp_path = format!("{}.tmp.{}.{}", path, pid, nanos);

        // Write + fsync the temp file before renaming. Without sync_all(),
        // the bytes may live only in the OS page cache; a power loss after
        // the rename leaves the live file truncated/empty because the
        // rename was atomic on the directory entry but the data pages were
        // never flushed to stable storage. Use the explicit File API so we
        // can call sync_all() on the handle.
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
                                    return Err(PyValueError::new_err(format!(
                                        "fsync after copy failed: {}",
                                        e
                                    )));
                                }
                            }
                            Err(e) => {
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
