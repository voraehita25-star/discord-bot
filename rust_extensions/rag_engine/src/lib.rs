//! RAG Engine - High-performance vector similarity search
//!
//! A Rust-based RAG (Retrieval-Augmented Generation) engine with:
//! - SIMD-optimized cosine similarity
//! - Memory-mapped vector storage
//! - Parallel search with Rayon

mod cosine;
mod storage;
mod index;
mod errors;

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use parking_lot::RwLock;
use std::collections::HashMap;
use std::sync::Arc;

pub use cosine::cosine_similarity;
pub use storage::VectorStorage;
pub use index::VectorIndex;
pub use errors::RagError;

/// A single memory entry with embedding and metadata
#[pyclass]
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
        Self { id, text, embedding, timestamp, importance }
    }

    fn get_embedding(&self) -> Vec<f32> {
        self.embedding.clone()
    }
}

/// Search result with score
#[pyclass]
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
        
        let mut entries = self.entries.write();
        entries.insert(entry.id.clone(), entry);
        Ok(())
    }

    /// Add multiple entries in batch
    fn add_batch(&self, entries_list: Vec<MemoryEntry>) -> PyResult<usize> {
        let mut entries = self.entries.write();
        let mut added = 0;
        
        for entry in entries_list {
            if entry.embedding.len() == self.dimension {
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
    fn search(&self, py: Python<'_>, query_embedding: Vec<f32>, top_k: usize, time_decay_factor: f64) -> PyResult<Vec<SearchResult>> {
        if query_embedding.len() != self.dimension {
            return Err(PyValueError::new_err(format!(
                "Query dimension mismatch: expected {}, got {}",
                self.dimension,
                query_embedding.len()
            )));
        }

        // Clone data under read lock so we can release GIL during computation
        let entries_snapshot: Vec<_> = {
            let entries = self.entries.read();
            entries.values().cloned().collect()
        };
        let similarity_threshold = self.similarity_threshold;

        // Release GIL during CPU-intensive parallel computation
        py.allow_threads(|| {
            use rayon::prelude::*;

            let current_time = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0);

            // Parallel similarity computation
            let mut results: Vec<SearchResult> = entries_snapshot
                .par_iter()
                .map(|entry| {
                    let base_score = cosine_similarity(&query_embedding, &entry.embedding);
                    
                    // Apply time decay if factor > 0
                    let final_score = if time_decay_factor > 0.0 {
                        // Clamp age to >= 0 to prevent score inflation for future timestamps
                        let age_hours = ((current_time - entry.timestamp) / 3600.0).max(0.0);
                        let decay = (-time_decay_factor * age_hours).exp() as f32;
                        base_score * decay * entry.importance
                    } else {
                        base_score * entry.importance
                    };

                    SearchResult {
                        id: entry.id.clone(),
                        text: entry.text.clone(),
                        score: final_score,
                        timestamp: entry.timestamp,
                    }
                })
                .filter(|r| r.score >= similarity_threshold)
                .collect();

            // Sort by score descending
            results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
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
        let entries = self.entries.read();
        let data: Vec<_> = entries.values().map(|e| {
            serde_json::json!({
                "id": e.id,
                "text": e.text,
                "embedding": e.embedding,
                "timestamp": e.timestamp,
                "importance": e.importance,
            })
        }).collect();

        let json = serde_json::to_string_pretty(&data)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        
        // Atomic write: write to temp file, then rename
        let temp_path = format!("{}.tmp", path);
        std::fs::write(&temp_path, &json)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        
        // rename may fail on Windows if file is locked; fall back to copy+delete
        if let Err(rename_err) = std::fs::rename(&temp_path, path) {
            match std::fs::copy(&temp_path, path) {
                Ok(_) => {
                    let _ = std::fs::remove_file(&temp_path);
                }
                Err(copy_err) => {
                    let _ = std::fs::remove_file(&temp_path);
                    return Err(PyValueError::new_err(format!(
                        "rename failed: {}, copy fallback failed: {}", rename_err, copy_err
                    )));
                }
            }
        }
        
        Ok(())
    }

    /// Load from JSON file (replaces all existing entries)
    fn load(&self, path: &str) -> PyResult<usize> {
        let data = std::fs::read_to_string(path)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        
        let entries_data: Vec<serde_json::Value> = serde_json::from_str(&data)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;

        // Build new entries in a temporary map first to avoid data loss on bad files
        let mut new_entries = HashMap::new();
        let mut loaded = 0;

        for item in &entries_data {
            if let (Some(id), Some(text), Some(embedding), Some(timestamp), Some(importance)) = (
                item["id"].as_str(),
                item["text"].as_str(),
                item["embedding"].as_array(),
                item["timestamp"].as_f64(),
                item["importance"].as_f64(),
            ) {
                let emb: Vec<f32> = embedding.iter()
                    .filter_map(|v| v.as_f64().map(|f| f as f32))
                    .collect();
                
                if emb.len() == self.dimension {
                    new_entries.insert(id.to_string(), MemoryEntry {
                        id: id.to_string(),
                        text: text.to_string(),
                        embedding: emb,
                        timestamp,
                        importance: importance as f32,
                    });
                    loaded += 1;
                }
            }
        }

        // Only replace existing data if we loaded at least some entries,
        // or if the source file was intentionally empty
        if new_entries.is_empty() && !entries_data.is_empty() {
            return Err(PyValueError::new_err(
                "No entries matched the expected dimension; refusing to replace existing data"
            ));
        }

        // Swap in the new entries atomically
        let mut entries = self.entries.write();
        *entries = new_entries;

        Ok(loaded)
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
