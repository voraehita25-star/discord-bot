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

    // A zero-norm vector has undefined cosine. simsimd reports cosine
    // *distance* 0 for two zero vectors, which the SIMD path below turns into
    // similarity 1.0 — while the scalar fallback returns 0.0 (its denom
    // guard). That disagreement would let a junk/zero embedding rank as a
    // perfect match. Treat a zero vector as "no similarity" so both paths
    // agree. `.all()` short-circuits on the first non-zero element, so
    // non-degenerate vectors pay ~one comparison. (clippy::float_cmp exempts
    // comparisons against a zero literal.)
    if a.iter().all(|&x| x == 0.0) || b.iter().all(|&x| x == 0.0) {
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

    // simsimd returns cosine *distance* (1.0 - similarity), so convert to similarity
    f32::cosine(a, b).and_then(|v| {
        let similarity = 1.0 - v as f32;
        if similarity.is_finite() {
            Some(similarity)
        } else {
            None
        }
    })
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
    fn test_zero_vector() {
        // Regression: a zero-norm vector must yield 0.0 on BOTH the SIMD and
        // scalar paths. simsimd reports cosine distance 0 for zero vectors,
        // which would otherwise surface as similarity 1.0 (a "perfect match").
        let zero = vec![0.0_f32, 0.0, 0.0, 0.0];
        let v = vec![1.0_f32, 2.0, 3.0, 4.0];
        assert_eq!(cosine_similarity(&zero, &v), 0.0);
        assert_eq!(cosine_similarity(&v, &zero), 0.0);
        assert_eq!(cosine_similarity(&zero, &zero), 0.0);
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
}
