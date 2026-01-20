//! GIF animation detection

/// Check if data is an animated GIF (has multiple frames)
pub fn is_animated_gif(data: &[u8]) -> bool {
    // Check GIF magic bytes
    if data.len() < 13 || &data[0..6] != b"GIF89a" && &data[0..6] != b"GIF87a" {
        return false;
    }

    // Count frame markers (Graphic Control Extension)
    // 0x21 0xF9 indicates a Graphic Control Extension
    let mut frame_count = 0;
    let mut i = 13; // Skip header

    // Skip Global Color Table if present
    let flags = data[10];
    if flags & 0x80 != 0 {
        let table_size = 3 * (1 << ((flags & 0x07) + 1));
        i += table_size;
    }

    while i + 2 < data.len() {
        match data[i] {
            0x21 => {
                // Extension
                if i + 1 < data.len() && data[i + 1] == 0xF9 {
                    // Graphic Control Extension = frame marker
                    frame_count += 1;
                    if frame_count > 1 {
                        return true; // Multiple frames = animated
                    }
                }
                // Skip extension
                i += 2;
                while i < data.len() && data[i] != 0 {
                    let block_size = data[i] as usize;
                    i += 1 + block_size;
                }
                i += 1; // Skip block terminator
            }
            0x2C => {
                // Image Descriptor
                if i + 10 >= data.len() {
                    break;
                }
                
                let local_flags = data[i + 9];
                i += 10;
                
                // Skip Local Color Table if present
                if local_flags & 0x80 != 0 {
                    let table_size = 3 * (1 << ((local_flags & 0x07) + 1));
                    i += table_size;
                }
                
                // Skip LZW minimum code size
                i += 1;
                
                // Skip image data blocks
                while i < data.len() && data[i] != 0 {
                    let block_size = data[i] as usize;
                    i += 1 + block_size;
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

/// Get GIF frame count
pub fn get_gif_frame_count(data: &[u8]) -> usize {
    if data.len() < 13 || &data[0..6] != b"GIF89a" && &data[0..6] != b"GIF87a" {
        return 0;
    }

    let mut frame_count = 0;
    
    // Simple approach: count Image Descriptors (0x2C)
    for i in 0..data.len() {
        if data[i] == 0x2C {
            frame_count += 1;
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
}
