//! Vector index for fast lookup

use std::collections::HashMap;

/// Simple inverted index for text-based filtering
pub struct VectorIndex {
    /// Keyword to vector IDs
    keyword_index: HashMap<String, Vec<usize>>,
    /// ID to index mapping
    id_to_idx: HashMap<String, usize>,
    /// Index to ID mapping
    idx_to_id: Vec<String>,
}

impl VectorIndex {
    pub fn new() -> Self {
        Self {
            keyword_index: HashMap::new(),
            id_to_idx: HashMap::new(),
            idx_to_id: Vec::new(),
        }
    }

    /// Add an entry to the index
    pub fn add(&mut self, id: &str, text: &str) -> usize {
        // If this ID already exists, update keywords for the new text
        if let Some(&existing_idx) = self.id_to_idx.get(id) {
            // Remove old keyword associations for this index
            for indices in self.keyword_index.values_mut() {
                indices.retain(|&i| i != existing_idx);
            }
            // Re-index with new text
            for word in text.split_whitespace() {
                let word_lower = word.to_lowercase();
                if word_lower.len() >= 3 {
                    self.keyword_index
                        .entry(word_lower)
                        .or_insert_with(Vec::new)
                        .push(existing_idx);
                }
            }
            return existing_idx;
        }

        let idx = self.idx_to_id.len();
        self.idx_to_id.push(id.to_string());
        self.id_to_idx.insert(id.to_string(), idx);

        // Index keywords (simple tokenization)
        for word in text.split_whitespace() {
            let word_lower = word.to_lowercase();
            if word_lower.len() >= 3 {
                self.keyword_index
                    .entry(word_lower)
                    .or_insert_with(Vec::new)
                    .push(idx);
            }
        }

        idx
    }

    /// Remove an entry from the index
    pub fn remove(&mut self, id: &str) -> Option<usize> {
        let idx = self.id_to_idx.remove(id)?;
        
        // Mark as removed in idx_to_id to avoid stale references
        // Note: We don't actually remove from idx_to_id or keyword_index
        // to avoid O(n) operations. Mark as empty instead.
        // For full cleanup, rebuild the index periodically.
        if idx < self.idx_to_id.len() {
            self.idx_to_id[idx] = String::new();
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
    }
}

impl Default for VectorIndex {
    fn default() -> Self {
        Self::new()
    }
}
