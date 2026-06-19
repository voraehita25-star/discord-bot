//! GIF animation detection

/// Check if data is an animated GIF (has multiple frames)
pub fn is_animated_gif(data: &[u8]) -> bool {
    // Check GIF magic bytes
    if data.len() < 13 || (&data[0..6] != b"GIF89a" && &data[0..6] != b"GIF87a") {
        return false;
    }

    // Count frames by Image Descriptor (0x2C) blocks, which is the
    // authoritative frame marker. GCE (0x21 0xF9) is optional per frame.
    let mut frame_count: usize = 0;
    let mut i: usize = 13; // Skip header

    // Skip Global Color Table if present
    let flags = data[10];
    if flags & 0x80 != 0 {
        let table_size: usize = 3 * (1 << ((flags & 0x07) + 1));
        i = i.saturating_add(table_size);
        if i >= data.len() {
            return false; // Corrupted GIF
        }
    }

    // Safety limit to prevent DoS on malformed GIF data
    let max_iterations = data.len().min(100_000);
    let mut iterations: usize = 0;

    // Loop bound `i < data.len()` (not `i + 2 < ...`) so a second Image
    // Descriptor sitting in the final 2 bytes is still examined — otherwise a
    // genuinely-animated 2-frame GIF could be reported as static. Every inner
    // access (data[i+9], i+=2, etc.) is individually bounds-checked below, and
    // this matches get_gif_frame_count's loop condition.
    while i < data.len() && iterations < max_iterations {
        iterations += 1;
        match data[i] {
            0x21 => {
                // Extension — skip it
                if i + 2 >= data.len() {
                    break;
                }
                i += 2;
                while i < data.len() && data[i] != 0 {
                    let block_size = data[i] as usize;
                    if i.saturating_add(1).saturating_add(block_size) > data.len() {
                        break;
                    }
                    i += 1 + block_size;
                }
                if i >= data.len() {
                    break;
                }
                i += 1; // Skip block terminator
            }
            0x2C => {
                // Image Descriptor = one frame
                frame_count += 1;
                if frame_count > 1 {
                    return true; // Multiple frames = animated
                }
                if i + 10 > data.len() {
                    break;
                }

                let local_flags = data[i + 9];
                i += 10;

                // Skip Local Color Table if present
                if local_flags & 0x80 != 0 {
                    let table_size = 3 * (1 << ((local_flags & 0x07) + 1));
                    if i.saturating_add(table_size) > data.len() {
                        break;
                    }
                    i += table_size;
                }

                // Skip LZW minimum code size
                if i >= data.len() {
                    break;
                }
                i += 1;

                // Skip image data blocks
                while i < data.len() && data[i] != 0 {
                    let block_size = data[i] as usize;
                    if i.saturating_add(1).saturating_add(block_size) > data.len() {
                        break;
                    }
                    i += 1 + block_size;
                }
                if i >= data.len() {
                    break;
                }
                i += 1; // Skip block terminator
            }
            0x3B => {
                // Trailer
                break;
            }
            _ => {
                i += 1;
            }
        }
    }

    false
}

/// Get GIF frame count using proper GIF structure parsing.
///
/// NOT wired to a `#[pyfunction]` on purpose — Python only needs the boolean
/// `is_animated_gif` (exposed as `py_is_animated`); the exact count has no
/// Python consumer today. It is kept `pub` (hence `#[allow(dead_code)]`, since
/// it is dead on the Python/library surface) because `benches/media_bench.rs`
/// and the `#[cfg(test)]` coverage below exercise it. If Python ever needs the
/// count, wire a `#[pyfunction]` and drop the allow. PARITY HAZARD: this is a
/// second hand-rolled GIF walker that must stay bounds-check-consistent with
/// `is_animated_gif` above — note the two intentionally differ only in how they
/// terminate on a malformed sub-block (`is_animated_gif` `break`s to keep
/// scanning; this `return`s the count so far). Apply any bounds fix to BOTH.
#[allow(dead_code)]
pub fn get_gif_frame_count(data: &[u8]) -> usize {
    if data.len() < 13 || (&data[0..6] != b"GIF89a" && &data[0..6] != b"GIF87a") {
        return 0;
    }

    let mut frame_count: usize = 0;
    let mut i: usize = 13; // Skip header

    // Skip Global Color Table if present
    let flags = data[10];
    if flags & 0x80 != 0 {
        let table_size: usize = 3 * (1 << ((flags & 0x07) + 1));
        i = i.saturating_add(table_size);
        if i >= data.len() {
            return 0;
        }
    }

    // Safety limit to prevent DoS on malformed GIF data
    let max_iterations = data.len().min(100_000);
    let mut iterations: usize = 0;

    while i < data.len() && iterations < max_iterations {
        iterations += 1;
        match data[i] {
            0x21 => {
                // Extension block - skip it
                if i + 2 >= data.len() {
                    break;
                }
                i += 2;
                // Skip sub-blocks
                while i < data.len() && data[i] != 0 {
                    let block_size = data[i] as usize;
                    if i.saturating_add(1).saturating_add(block_size) > data.len() {
                        return frame_count;
                    }
                    i += 1 + block_size;
                }
                if i >= data.len() {
                    break;
                }
                i += 1; // Skip block terminator
            }
            0x2C => {
                // Image Descriptor = one frame
                frame_count += 1;
                if i + 10 > data.len() {
                    break;
                }

                let local_flags = data[i + 9];
                i += 10;

                // Skip Local Color Table if present
                if local_flags & 0x80 != 0 {
                    let table_size = 3 * (1 << ((local_flags & 0x07) + 1));
                    if i.saturating_add(table_size) > data.len() {
                        break;
                    }
                    i += table_size;
                }

                // Skip LZW minimum code size
                if i >= data.len() {
                    break;
                }
                i += 1;

                // Skip image data sub-blocks
                while i < data.len() && data[i] != 0 {
                    let block_size = data[i] as usize;
                    if i.saturating_add(1).saturating_add(block_size) > data.len() {
                        return frame_count;
                    }
                    i += 1 + block_size;
                }
                if i >= data.len() {
                    break;
                }
                i += 1; // Skip block terminator
            }
            0x3B => {
                // Trailer
                break;
            }
            _ => {
                i += 1;
            }
        }
    }

    frame_count
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_non_gif_data() {
        let png_header = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
        assert!(!is_animated_gif(&png_header));
    }

    #[test]
    fn test_empty_data() {
        assert!(!is_animated_gif(&[]));
    }

    /// Minimal valid GIF89a carrying exactly two Image Descriptor frames.
    /// (Same fixture as benches/media_bench.rs.)
    fn two_frame_gif() -> Vec<u8> {
        vec![
            0x47, 0x49, 0x46, 0x38, 0x39, 0x61, // GIF89a
            0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, // LSD
            0x21, 0xF9, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, // GCE
            0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, // Image 1
            0x02, 0x02, 0x44, 0x01, 0x00, 0x21, 0xF9, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, // GCE
            0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, // Image 2
            0x02, 0x02, 0x44, 0x01, 0x00, 0x3B, // Trailer
        ]
    }

    #[test]
    fn test_two_frame_gif_is_animated() {
        let gif = two_frame_gif();
        assert!(is_animated_gif(&gif), "2-frame GIF must be detected as animated");
    }

    #[test]
    fn test_get_gif_frame_count_counts_two() {
        let gif = two_frame_gif();
        assert_eq!(get_gif_frame_count(&gif), 2);
    }

    #[test]
    fn test_single_frame_gif_not_animated() {
        // One Image Descriptor only -> static.
        let gif = vec![
            0x47, 0x49, 0x46, 0x38, 0x39, 0x61, // GIF89a
            0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, // LSD
            0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, // Image 1
            0x02, 0x02, 0x44, 0x01, 0x00, 0x3B, // Trailer
        ];
        assert!(!is_animated_gif(&gif));
        assert_eq!(get_gif_frame_count(&gif), 1);
    }
}
