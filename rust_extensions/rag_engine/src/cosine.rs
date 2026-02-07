//! SIMD-optimized cosine similarity computation

/// Compute cosine similarity between two vectors using SIMD when available
#[inline]
pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    // Validate vector lengths match - return 0.0 for invalid input
    if a.len() != b.len() {
        return 0.0;
    }
    
    if a.is_empty() {
        return 0.0;
    }

    // Try SIMD-accelerated computation first
    #[cfg(any(target_arch = "x86_64", target_arch = "aarch64"))]
    {
        if let Some(score) = simd_cosine(a, b) {
            return score;
        }
    }

    // Fallback to scalar
    scalar_cosine(a, b)
}

/// SIMD-accelerated cosine similarity
#[cfg(any(target_arch = "x86_64", target_arch = "aarch64"))]
fn simd_cosine(a: &[f32], b: &[f32]) -> Option<f32> {
    use simsimd::SpatialSimilarity;
    
    // simsimd provides hardware-accelerated similarity
    f32::cosine(a, b).map(|v| v as f32)
}

/// Scalar fallback for cosine similarity
fn scalar_cosine(a: &[f32], b: &[f32]) -> f32 {
    let mut dot = 0.0f32;
    let mut norm_a = 0.0f32;
    let mut norm_b = 0.0f32;

    // Process in chunks of 4 for better cache utilization
    let chunks = a.len() / 4;
    let remainder = a.len() % 4;

    for i in 0..chunks {
        let idx = i * 4;
        dot += a[idx] * b[idx]
            + a[idx + 1] * b[idx + 1]
            + a[idx + 2] * b[idx + 2]
            + a[idx + 3] * b[idx + 3];
        
        norm_a += a[idx] * a[idx]
            + a[idx + 1] * a[idx + 1]
            + a[idx + 2] * a[idx + 2]
            + a[idx + 3] * a[idx + 3];
        
        norm_b += b[idx] * b[idx]
            + b[idx + 1] * b[idx + 1]
            + b[idx + 2] * b[idx + 2]
            + b[idx + 3] * b[idx + 3];
    }

    // Handle remainder
    let start = chunks * 4;
    for i in 0..remainder {
        let idx = start + i;
        dot += a[idx] * b[idx];
        norm_a += a[idx] * a[idx];
        norm_b += b[idx] * b[idx];
    }

    let denom = (norm_a * norm_b).sqrt();
    if denom > 1e-10 {
        dot / denom
    } else {
        0.0
    }
}

/// Batch compute similarities (parallel)
pub fn batch_cosine_similarity(query: &[f32], vectors: &[Vec<f32>]) -> Vec<f32> {
    use rayon::prelude::*;
    
    vectors
        .par_iter()
        .map(|v| cosine_similarity(query, v))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_identical_vectors() {
        let v = vec![1.0, 2.0, 3.0, 4.0];
        let sim = cosine_similarity(&v, &v);
        assert!((sim - 1.0).abs() < 1e-6);
    }

    #[test]
    fn test_orthogonal_vectors() {
        let a = vec![1.0, 0.0, 0.0];
        let b = vec![0.0, 1.0, 0.0];
        let sim = cosine_similarity(&a, &b);
        assert!(sim.abs() < 1e-6);
    }

    #[test]
    fn test_opposite_vectors() {
        let a = vec![1.0, 2.0, 3.0];
        let b = vec![-1.0, -2.0, -3.0];
        let sim = cosine_similarity(&a, &b);
        assert!((sim + 1.0).abs() < 1e-6);
    }

    #[test]
    fn test_batch_similarity() {
        let query = vec![1.0, 0.0, 0.0];
        let vectors = vec![
            vec![1.0, 0.0, 0.0],
            vec![0.0, 1.0, 0.0],
            vec![-1.0, 0.0, 0.0],
        ];
        let results = batch_cosine_similarity(&query, &vectors);
        assert!((results[0] - 1.0).abs() < 1e-6);
        assert!(results[1].abs() < 1e-6);
        assert!((results[2] + 1.0).abs() < 1e-6);
    }
}
