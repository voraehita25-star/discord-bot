//! Vector index for fast lookup

use std::collections::{HashMap, HashSet};

/// Simple inverted index for text-based filtering
pub struct VectorIndex {
    /// Keyword to vector IDs
    keyword_index: HashMap<String, Vec<usize>>,
    /// Reverse lookup: index → set of keywords pointing at it. Without
    /// this, ``add()`` and ``remove()`` previously walked the ENTIRE
    /// ``keyword_index`` (one ``retain`` over every word in the index)
    /// on every churn event, producing O(total_keywords) work per op.
    /// With it, both paths touch only the keywords that actually map to
    /// the affected slot — bounded by the number of unique tokens in
    /// that document.
    idx_to_keywords: HashMap<usize, HashSet<String>>,
    /// ID to index mapping
    id_to_idx: HashMap<String, usize>,
    /// Index to ID mapping
    idx_to_id: Vec<String>,
    /// Indices freed by `remove()` that are available for reuse on the next
    /// `add()`. Without this, the previous implementation marked deleted
    /// slots empty but never reclaimed them — `idx_to_id` grew monotonically
    /// and a long-running engine that added/removed many entries leaked memory
    /// proportional to total churn.
    free_slots: Vec<usize>,
}

impl VectorIndex {
    pub fn new() -> Self {
        Self {
            keyword_index: HashMap::new(),
            idx_to_keywords: HashMap::new(),
            id_to_idx: HashMap::new(),
            idx_to_id: Vec::new(),
            free_slots: Vec::new(),
        }
    }

    /// Add an entry to the index
    pub fn add(&mut self, id: &str, text: &str) -> usize {
        // Dedup tokens up front so a text like "foo foo bar" only pushes
        // its idx into keyword_index["foo"] once. Without this, repeated
        // tokens grew the per-word vec linearly with every duplicate
        // occurrence across all indexed docs.
        // Filter by *character* count, not byte count. ``str::len`` returns
        // the UTF-8 byte length, so a 1-char Thai word (3 bytes) passed
        // the ``>= 3`` byte filter while a 2-char ASCII English word
        // ("of", "to") was rejected — inconsistent across scripts.
        // ``chars().count()`` makes the threshold uniform per glyph.
        //
        // NOTE: ``split_whitespace`` + ``to_lowercase`` is a best-effort
        // tokenizer for Latin scripts only. Thai prose is written without
        // spaces between words, so the keyword index produced here covers
        // little of a Thai document. The semantic/embedding path (FAISS)
        // handles Thai correctly; this keyword fallback is intentionally
        // left as a Latin-script-only fast filter to keep the hot path
        // free of a heavyweight word-segmentation dependency.
        let unique_words: std::collections::HashSet<String> = text
            .split_whitespace()
            .map(|w| w.to_lowercase())
            // Use ``nth(2).is_some()`` so the early-termination check
            // short-circuits at 3 characters instead of counting the
            // full string. ``chars().count()`` is O(n) per token and on
            // a multi-megabyte document this added meaningful cost
            // versus the early-stop variant.
            .filter(|w| w.chars().nth(2).is_some())
            .collect();

        // If this ID already exists, update keywords for the new text
        if let Some(&existing_idx) = self.id_to_idx.get(id) {
            // Remove old keyword associations for this index in O(k)
            // where k = unique keywords this doc was indexed under,
            // using the reverse lookup. The previous ``retain`` scanned
            // the entire ``keyword_index`` on every update.
            if let Some(old_keywords) = self.idx_to_keywords.remove(&existing_idx) {
                for word in &old_keywords {
                    if let Some(indices) = self.keyword_index.get_mut(word) {
                        indices.retain(|&i| i != existing_idx);
                        if indices.is_empty() {
                            self.keyword_index.remove(word);
                        }
                    }
                }
            }
            // Re-index with new text
            for word in &unique_words {
                self.keyword_index
                    .entry(word.clone())
                    .or_default()
                    .push(existing_idx);
            }
            self.idx_to_keywords
                .insert(existing_idx, unique_words.iter().cloned().collect());
            return existing_idx;
        }

        // Reuse a previously-removed slot when one is available; only fall
        // back to growing `idx_to_id` when there are no free slots. This
        // keeps memory proportional to live entries instead of total churn.
        let idx = if let Some(slot) = self.free_slots.pop() {
            self.idx_to_id[slot] = id.to_string();
            slot
        } else {
            let idx = self.idx_to_id.len();
            self.idx_to_id.push(id.to_string());
            idx
        };
        self.id_to_idx.insert(id.to_string(), idx);

        // Index keywords (simple tokenization)
        for word in &unique_words {
            self.keyword_index
                .entry(word.clone())
                .or_default()
                .push(idx);
        }
        self.idx_to_keywords
            .insert(idx, unique_words.iter().cloned().collect());

        idx
    }

    /// Remove an entry from the index
    pub fn remove(&mut self, id: &str) -> Option<usize> {
        let idx = self.id_to_idx.remove(id)?;

        // Mark as removed in idx_to_id and clean keyword references.
        // SAFETY: The ``idx < self.idx_to_id.len()`` bound check is defensive
        // and unreachable in practice — ``id_to_idx`` is only populated by
        // ``add()`` which always pushes/overwrites a valid slot in
        // ``idx_to_id`` (see invariant near ``free_slots`` reuse above). We
        // keep the guard to avoid any chance of a panic if the invariant is
        // ever broken by a future refactor.
        if idx < self.idx_to_id.len() {
            self.idx_to_id[idx] = String::new();
            // Make the slot available for the next add() so we don't leak
            // unbounded growth on add/remove churn.
            self.free_slots.push(idx);
        }

        // Remove stale keyword references for this index using the
        // reverse lookup — O(keywords-for-this-doc) instead of the
        // previous O(total-keywords-in-index) full-map walk.
        if let Some(keywords) = self.idx_to_keywords.remove(&idx) {
            for word in &keywords {
                if let Some(indices) = self.keyword_index.get_mut(word) {
                    indices.retain(|&i| i != idx);
                    if indices.is_empty() {
                        self.keyword_index.remove(word);
                    }
                }
            }
        }

        Some(idx)
    }

    /// Get index by ID
    pub fn get_idx(&self, id: &str) -> Option<usize> {
        self.id_to_idx.get(id).copied()
    }

    /// Get ID by index
    pub fn get_id(&self, idx: usize) -> Option<&str> {
        self.idx_to_id.get(idx)
            .filter(|s| !s.is_empty()) // Skip removed entries
            .map(|s| s.as_str())
    }

    /// Search by keyword (filters out stale/removed entries)
    pub fn search_keyword(&self, keyword: &str) -> Vec<usize> {
        self.keyword_index
            .get(&keyword.to_lowercase())
            .map(|indices| {
                indices.iter()
                    .copied()
                    .filter(|&idx| {
                        // Filter out removed entries (marked as empty string)
                        self.idx_to_id.get(idx)
                            .map(|s| !s.is_empty())
                            .unwrap_or(false)
                    })
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Get number of entries
    pub fn len(&self) -> usize {
        self.id_to_idx.len()
    }

    /// Check if empty
    pub fn is_empty(&self) -> bool {
        self.id_to_idx.is_empty()
    }

    /// Clear the index
    pub fn clear(&mut self) {
        self.keyword_index.clear();
        self.id_to_idx.clear();
        self.idx_to_id.clear();
        self.free_slots.clear();
    }
}

impl Default for VectorIndex {
    fn default() -> Self {
        Self::new()
    }
}
