//! Image resizing functionality

use image::{DynamicImage, GenericImageView, ImageFormat};
use std::io::Cursor;

use crate::errors::MediaError;
use crate::ImageData;

/// Resize mode
#[derive(Clone, Copy)]
pub enum ResizeMode {
    /// Fit within bounds, maintaining aspect ratio
    Fit,
    /// Fill bounds, cropping if necessary
    Fill,
    /// Stretch to exact dimensions
    Stretch,
}

/// Maximum allowed dimension for resize operations (prevents DoS via extreme allocations)
const MAX_ALLOWED_DIMENSION: u32 = 16384;
/// Maximum allowed pixel count to prevent decompression bombs
const MAX_PIXEL_COUNT: u64 = 100_000_000; // 100 megapixels

/// Resize an image
pub fn resize_image(
    data: &[u8],
    max_width: u32,
    max_height: u32,
    mode: ResizeMode,
    jpeg_quality: u8,
) -> Result<ImageData, MediaError> {
    // Validate dimensions to prevent panic in image crate
    if max_width == 0 || max_height == 0 {
        return Err(MediaError::Encode(
            "Dimensions must be greater than 0".to_string(),
        ));
    }

    // Clamp dimensions to safe maximum to prevent extreme memory allocation
    let max_width = max_width.min(MAX_ALLOWED_DIMENSION);
    let max_height = max_height.min(MAX_ALLOWED_DIMENSION);

    // Clamp JPEG quality to valid range (1-100)
    let jpeg_quality = jpeg_quality.clamp(1, 100);

    // Check image dimensions BEFORE full decode to prevent decompression bombs
    let reader = image::ImageReader::new(std::io::Cursor::new(data))
        .with_guessed_format()
        .map_err(|e| MediaError::Encode(format!("Failed to detect image format: {}", e)))?;
    match reader.into_dimensions() {
        Ok((w, h)) => {
            // Mirror the checked_mul style used by lib.rs check_bomb_dimensions and the
            // Fill intermediate guard below. Both operands are u32 widened to u64 so the
            // product cannot actually overflow u64 — checked_mul is for stylistic
            // consistency, not a live overflow risk.
            let pixels = (w as u64).checked_mul(h as u64);
            if pixels.is_none_or(|p| p > MAX_PIXEL_COUNT) {
                return Err(MediaError::Encode(format!(
                    "Image too large: {}x{} ({} MP, max {} MP)",
                    w,
                    h,
                    pixels.unwrap_or(u64::MAX) / 1_000_000,
                    MAX_PIXEL_COUNT / 1_000_000
                )));
            }
        }
        Err(e) => {
            return Err(MediaError::Encode(format!(
                "Cannot determine image dimensions (possible decompression bomb): {}",
                e
            )));
        }
    }

    let img = image::load_from_memory(data)?;
    let (orig_w, orig_h) = img.dimensions();

    // Guard against degenerate/corrupt images with zero dimensions
    if orig_w == 0 || orig_h == 0 {
        return Err(MediaError::Encode("Image has zero dimensions".to_string()));
    }

    // Calculate new dimensions
    let (new_w, new_h) = match mode {
        ResizeMode::Fit => calculate_fit_dimensions(orig_w, orig_h, max_width, max_height),
        ResizeMode::Fill => (max_width, max_height),
        ResizeMode::Stretch => (max_width, max_height),
    };

    // Skip if already smaller (only for Fit mode — Fill/Stretch must reach requested dimensions)
    if matches!(mode, ResizeMode::Fit) && new_w >= orig_w && new_h >= orig_h {
        return Ok(ImageData {
            data: data.to_vec(),
            width: orig_w,
            height: orig_h,
            channels: img.color().channel_count(),
            // Report the TRUE format of the original bytes being returned (sniffed
            // from magic bytes), not the png/jpeg guess from color type — otherwise a
            // small WebP/GIF/BMP that skips resizing would be mislabeled.
            format: image::guess_format(data)
                .map(format_to_string)
                .unwrap_or_else(|_| detect_format_from_image(&img)),
        });
    }

    // Perform resize
    let resized = match mode {
        ResizeMode::Fill => {
            // Crop to fill
            let scale = f64::max(new_w as f64 / orig_w as f64, new_h as f64 / orig_h as f64);
            let scaled_w = (orig_w as f64 * scale).ceil().min(u32::MAX as f64) as u32;
            let scaled_h = (orig_h as f64 * scale).ceil().min(u32::MAX as f64) as u32;

            // Bound the Fill intermediate by the same 100MP cap the input is
            // checked against. An extreme-aspect input (e.g. 16384x1) has a tiny
            // INPUT pixel count and sails past the bomb guard, but Fill upscales
            // to scaled_w x scaled_h (16384x16384 -> ~268M px wide) and the
            // resize_exact buffer explodes to tens of TB. checked_mul also
            // rejects the saturating-to-u32::MAX overflow instead of clamping
            // into a huge allocation.
            if (scaled_w as u64)
                .checked_mul(scaled_h as u64)
                .is_none_or(|p| p > MAX_PIXEL_COUNT)
            {
                return Err(MediaError::Encode(format!(
                    "Fill intermediate too large: {}x{} exceeds {} MP",
                    scaled_w,
                    scaled_h,
                    MAX_PIXEL_COUNT / 1_000_000
                )));
            }

            let scaled =
                img.resize_exact(scaled_w, scaled_h, image::imageops::FilterType::Lanczos3);

            // Get actual dimensions after resize for bounds check
            let (actual_w, actual_h) = scaled.dimensions();

            let x = (actual_w.saturating_sub(new_w)) / 2;
            let y = (actual_h.saturating_sub(new_h)) / 2;

            // Clamp crop dimensions to prevent panic on edge cases
            let crop_w = new_w.min(actual_w.saturating_sub(x)).max(1);
            let crop_h = new_h.min(actual_h.saturating_sub(y)).max(1);

            scaled.crop_imm(x, y, crop_w, crop_h)
        }
        ResizeMode::Stretch => {
            img.resize_exact(new_w, new_h, image::imageops::FilterType::Lanczos3)
        }
        ResizeMode::Fit => img.resize(new_w, new_h, image::imageops::FilterType::Lanczos3),
    };

    // Encode result
    let (new_w, new_h) = resized.dimensions();
    let mut output = Vec::new();
    // determine_output_format only ever returns Png or Jpeg, and this build has
    // no WebP encoder — so handle Png explicitly and encode everything else as
    // JPEG, reassigning `format` so the reported format always matches the bytes
    // (the old WebP/`_` arms were unreachable and the `_` arm mislabeled output).
    let mut format = determine_output_format(&img);
    match format {
        ImageFormat::Png => {
            resized.write_to(&mut Cursor::new(&mut output), ImageFormat::Png)?;
        }
        _ => {
            format = ImageFormat::Jpeg;
            let encoder =
                image::codecs::jpeg::JpegEncoder::new_with_quality(&mut output, jpeg_quality);
            resized.write_with_encoder(encoder)?;
        }
    }

    Ok(ImageData {
        data: output,
        width: new_w,
        height: new_h,
        channels: resized.color().channel_count(),
        format: format_to_string(format),
    })
}

/// Calculate dimensions to fit within bounds while maintaining aspect ratio
fn calculate_fit_dimensions(orig_w: u32, orig_h: u32, max_w: u32, max_h: u32) -> (u32, u32) {
    let ratio_w = max_w as f64 / orig_w as f64;
    let ratio_h = max_h as f64 / orig_h as f64;
    let ratio = f64::min(ratio_w, ratio_h);

    if ratio >= 1.0 {
        (orig_w, orig_h)
    } else {
        (
            ((orig_w as f64 * ratio).round() as u32).max(1),
            ((orig_h as f64 * ratio).round() as u32).max(1),
        )
    }
}

fn detect_format_from_image(img: &DynamicImage) -> String {
    match img.color() {
        image::ColorType::Rgba8 | image::ColorType::Rgba16 => "png".to_string(),
        _ => "jpeg".to_string(),
    }
}

fn determine_output_format(img: &DynamicImage) -> ImageFormat {
    // Keep PNG for images with transparency
    if img.color().has_alpha() {
        ImageFormat::Png
    } else {
        ImageFormat::Jpeg
    }
}

fn format_to_string(format: ImageFormat) -> String {
    match format {
        ImageFormat::Jpeg => "jpeg",
        ImageFormat::Png => "png",
        ImageFormat::Gif => "gif",
        ImageFormat::WebP => "webp",
        _ => "unknown",
    }
    .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    /// Encode a real, tiny RGB PNG so the resize decode path gets valid input.
    fn tiny_png(w: u32, h: u32) -> Vec<u8> {
        let img = image::RgbImage::from_fn(w, h, |x, y| {
            image::Rgb([(x % 256) as u8, (y % 256) as u8, 64])
        });
        let mut out = Vec::new();
        image::DynamicImage::ImageRgb8(img)
            .write_to(&mut Cursor::new(&mut out), ImageFormat::Png)
            .unwrap();
        out
    }

    #[test]
    fn calculate_fit_preserves_aspect_and_never_zero() {
        // 200x100 into 50x50 -> ratio 0.25 -> 50x25 (aspect preserved).
        assert_eq!(calculate_fit_dimensions(200, 100, 50, 50), (50, 25));
        // Already-smaller -> unchanged.
        assert_eq!(calculate_fit_dimensions(30, 20, 100, 100), (30, 20));
        // Extreme aspect must still never round down to 0.
        let (w, h) = calculate_fit_dimensions(10_000, 1, 100, 100);
        assert!(w >= 1 && h >= 1, "got {w}x{h}");
        assert_eq!(h, 1);
    }

    #[test]
    fn resize_fit_downscales_and_keeps_aspect() {
        let src = tiny_png(40, 20);
        let out = resize_image(&src, 10, 10, ResizeMode::Fit, 85).unwrap();
        // 40x20 fit into 10x10 -> 10x5.
        assert_eq!((out.width, out.height), (10, 5));
    }

    #[test]
    fn resize_fit_skips_when_already_smaller() {
        let src = tiny_png(8, 8);
        let out = resize_image(&src, 100, 100, ResizeMode::Fit, 85).unwrap();
        // Unchanged dimensions; original bytes returned.
        assert_eq!((out.width, out.height), (8, 8));
    }

    #[test]
    fn resize_rejects_zero_target_dimensions() {
        let src = tiny_png(8, 8);
        assert!(resize_image(&src, 0, 10, ResizeMode::Fit, 85).is_err());
        assert!(resize_image(&src, 10, 0, ResizeMode::Fit, 85).is_err());
    }

    #[test]
    fn resize_fill_rejects_explosive_intermediate() {
        // Extreme-aspect input (16384x1) has a tiny INPUT pixel count and sails
        // past the bomb guard, but Fill upscales the intermediate to a huge
        // square (after clamping to MAX_ALLOWED_DIMENSION the requested side is
        // 16384, so scale blows the intermediate well past 100MP). The Fill
        // intermediate guard must reject it instead of allocating tens of TB.
        let src = tiny_png(16384, 1);
        // Match on the Result directly: ImageData has no Debug impl, so
        // unwrap_err() won't compile — pull the error out via a match instead.
        match resize_image(&src, 16384, 16384, ResizeMode::Fill, 85) {
            Ok(_) => panic!("explosive Fill intermediate must be rejected"),
            Err(e) => {
                let msg = format!("{e}");
                assert!(
                    msg.contains("Fill intermediate too large"),
                    "unexpected error: {msg}"
                );
            }
        }
    }
}
