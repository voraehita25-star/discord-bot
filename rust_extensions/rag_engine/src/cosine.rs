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
    // agree. NOTE: this exactly-zero check only guarantees SIMD/scalar parity
    // for genuinely zero vectors. A vector with tiny non-zero components whose
    // norm falls below 1e-10 (e.g. denormals) passes this guard, after which
    // the scalar path still floors to 0.0 (denom guard) but the SIMD path may
    // return a finite non-zero similarity — a parity gap real embeddings never
    // reach. `.all()` short-circuits on the first non-zero element, so
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

    // Floor a non-finite result to 0.0 rather than leaking it. Finite-but-huge
    // inputs (e.g. components near f32::MAX, which still pass an is_finite()
    // input check) overflow the dot/norm accumulators to +/-Inf, giving a
    // denom of Inf (> 1e-10, so the zero-denom guard does NOT catch it) and a
    // dot of Inf, hence Inf/Inf = NaN. Public callers (compute_similarity)
    // promise to never return a non-finite score, and search() already maps
    // non-finite to 0.0; mirror that here so the contract holds uniformly.
    let denom = (norm_a * norm_b).sqrt();
    if denom > 1e-10 {
        let sim = dot / denom;
        if sim.is_finite() {
            sim
        } else {
            0.0
        }
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

    #[test]
    fn test_scalar_cosine_finite_but_huge_inputs_floored() {
        // Regression (rs-rag-missed-1), scalar path specifically: components
        // near f32::MAX are finite (pass an is_finite() input check) but
        // overflow the dot/norm accumulators, producing denom=Inf and dot=Inf
        // -> NaN. scalar_cosine previously returned that raw NaN. It must now
        // floor any non-finite result to 0.0. Test the scalar fn directly so
        // the floor is pinned regardless of whether SIMD intercepts the public
        // entry point. 4 lanes hits the chunk-of-4 loop.
        let huge = vec![3.0e38_f32; 4];
        let sim = scalar_cosine(&huge, &huge);
        assert!(sim.is_finite(), "scalar expected finite, got {sim}");
        assert_eq!(sim, 0.0);

        // Non-multiple-of-4 length exercises the remainder loop too.
        let huge3 = vec![3.0e38_f32; 3];
        let sim3 = scalar_cosine(&huge3, &huge3);
        assert!(sim3.is_finite(), "scalar expected finite, got {sim3}");
        assert_eq!(sim3, 0.0);
    }

    #[test]
    fn test_public_entry_never_leaks_nonfinite_for_huge_inputs() {
        // The public cosine_similarity tries SIMD first; simsimd may return a
        // finite value for these inputs (higher-precision accumulators) or fall
        // through to scalar_cosine. Either way the contract is: the score is
        // ALWAYS finite, never NaN/Inf. Assert only finiteness here (the SIMD
        // value, if any, is implementation-defined).
        let huge = vec![3.0e38_f32; 4];
        assert!(cosine_similarity(&huge, &huge).is_finite());
        let huge3 = vec![3.0e38_f32; 3];
        assert!(cosine_similarity(&huge3, &huge3).is_finite());
    }
}
