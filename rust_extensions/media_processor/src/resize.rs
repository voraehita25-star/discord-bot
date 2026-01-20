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

/// Resize an image
pub fn resize_image(
    data: &[u8],
    max_width: u32,
    max_height: u32,
    mode: ResizeMode,
    jpeg_quality: u8,
) -> Result<ImageData, MediaError> {
    let img = image::load_from_memory(data)?;
    let (orig_w, orig_h) = img.dimensions();

    // Calculate new dimensions
    let (new_w, new_h) = match mode {
        ResizeMode::Fit => calculate_fit_dimensions(orig_w, orig_h, max_width, max_height),
        ResizeMode::Fill => (max_width, max_height),
        ResizeMode::Stretch => (max_width, max_height),
    };

    // Skip if already smaller
    if new_w >= orig_w && new_h >= orig_h {
        return Ok(ImageData {
            data: data.to_vec(),
            width: orig_w,
            height: orig_h,
            channels: img.color().channel_count(),
            format: detect_format_from_image(&img),
        });
    }

    // Perform resize
    let resized = match mode {
        ResizeMode::Fill => {
            // Crop to fill
            let scale = f64::max(
                new_w as f64 / orig_w as f64,
                new_h as f64 / orig_h as f64,
            );
            let scaled_w = (orig_w as f64 * scale).ceil() as u32;
            let scaled_h = (orig_h as f64 * scale).ceil() as u32;
            
            let scaled = img.resize_exact(scaled_w, scaled_h, image::imageops::FilterType::Lanczos3);
            
            let x = (scaled_w.saturating_sub(new_w)) / 2;
            let y = (scaled_h.saturating_sub(new_h)) / 2;
            
            scaled.crop_imm(x, y, new_w, new_h)
        }
        ResizeMode::Stretch => {
            img.resize_exact(new_w, new_h, image::imageops::FilterType::Lanczos3)
        }
        ResizeMode::Fit => {
            img.resize(new_w, new_h, image::imageops::FilterType::Lanczos3)
        }
    };

    // Encode result
    let (new_w, new_h) = resized.dimensions();
    let mut output = Vec::new();
    let format = determine_output_format(&img);
    
    match format {
        ImageFormat::Jpeg => {
            let encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut output, jpeg_quality);
            resized.write_with_encoder(encoder)?;
        }
        ImageFormat::Png => {
            resized.write_to(&mut Cursor::new(&mut output), ImageFormat::Png)?;
        }
        ImageFormat::WebP => {
            resized.write_to(&mut Cursor::new(&mut output), ImageFormat::WebP)?;
        }
        _ => {
            // Default to JPEG
            let encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut output, jpeg_quality);
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
        ((orig_w as f64 * ratio).round() as u32, (orig_h as f64 * ratio).round() as u32)
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
    }.to_string()
}
