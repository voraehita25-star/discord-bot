//! Media Processor - High-performance image processing
//!
//! A Rust-based media processor with:
//! - Fast image resizing
//! - GIF animation detection
//! - Base64 encoding/decoding
//! - Parallel batch processing

mod resize;
mod gif;
mod encode;
mod errors;

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::types::PyBytes;
use image::GenericImageView;

pub use resize::{resize_image, ResizeMode};
pub use gif::is_animated_gif;
pub use encode::{to_base64, from_base64};
pub use errors::MediaError;

/// Image data container
#[pyclass]
#[derive(Clone)]
pub struct ImageData {
    #[pyo3(get)]
    pub width: u32,
    #[pyo3(get)]
    pub height: u32,
    #[pyo3(get)]
    pub channels: u8,
    #[pyo3(get)]
    pub format: String,
    pub data: Vec<u8>,
}

#[pymethods]
impl ImageData {
    #[new]
    fn new(data: Vec<u8>, width: u32, height: u32, channels: u8, format: String) -> Self {
        Self { data, width, height, channels, format }
    }

    fn get_data<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new_bound(py, &self.data)
    }

    fn to_base64(&self) -> String {
        to_base64(&self.data)
    }

    fn __len__(&self) -> usize {
        self.data.len()
    }
}

/// Main Media Processor class
#[pyclass]
pub struct MediaProcessor {
    max_dimension: u32,
    jpeg_quality: u8,
}

#[pymethods]
impl MediaProcessor {
    #[new]
    #[pyo3(signature = (max_dimension=1024, jpeg_quality=85))]
    fn new(max_dimension: u32, jpeg_quality: u8) -> Self {
        Self { max_dimension, jpeg_quality }
    }

    /// Load image from bytes
    fn load<'py>(&self, _py: Python<'py>, data: &Bound<'py, PyBytes>) -> PyResult<ImageData> {
        let bytes = data.as_bytes();
        
        // Check dimensions before full decode to prevent decompression bombs
        let reader = image::ImageReader::new(std::io::Cursor::new(bytes))
            .with_guessed_format()
            .map_err(|e| PyValueError::new_err(format!("Failed to detect image format: {}", e)))?;
        match reader.into_dimensions() {
            Ok((w, h)) => {
                if (w as u64) * (h as u64) > 100_000_000 {
                    return Err(PyValueError::new_err(format!(
                        "Image too large: {}x{} exceeds 100MP limit", w, h
                    )));
                }
            }
            Err(e) => {
                // If we can't read dimensions, reject the image as a safety precaution
                return Err(PyValueError::new_err(format!(
                    "Cannot determine image dimensions (possible decompression bomb): {}", e
                )));
            }
        }

        let img = image::load_from_memory(bytes)
            .map_err(|e| PyValueError::new_err(format!("Failed to load image: {}", e)))?;
        
        let (width, height) = img.dimensions();
        let channels = img.color().channel_count();
        
        // Detect format from magic bytes
        let format = detect_format(bytes).unwrap_or("unknown").to_string();
        
        Ok(ImageData {
            data: bytes.to_vec(),
            width,
            height,
            channels,
            format,
        })
    }

    /// Resize image to fit within max dimensions
    fn resize<'py>(&self, _py: Python<'py>, data: &Bound<'py, PyBytes>, max_width: Option<u32>, max_height: Option<u32>) -> PyResult<ImageData> {
        let bytes = data.as_bytes();
        let max_w = max_width.unwrap_or(self.max_dimension);
        let max_h = max_height.unwrap_or(self.max_dimension);
        
        let result = resize_image(bytes, max_w, max_h, ResizeMode::Fit, self.jpeg_quality)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        
        Ok(result)
    }

    /// Resize image to exact dimensions (with cropping)
    fn resize_exact<'py>(&self, _py: Python<'py>, data: &Bound<'py, PyBytes>, width: u32, height: u32) -> PyResult<ImageData> {
        let bytes = data.as_bytes();
        
        let result = resize_image(bytes, width, height, ResizeMode::Fill, self.jpeg_quality)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        
        Ok(result)
    }

    /// Create thumbnail
    fn thumbnail<'py>(&self, _py: Python<'py>, data: &Bound<'py, PyBytes>, size: u32) -> PyResult<ImageData> {
        let bytes = data.as_bytes();
        
        let result = resize_image(bytes, size, size, ResizeMode::Fit, self.jpeg_quality)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        
        Ok(result)
    }

    /// Check if image is an animated GIF
    #[staticmethod]
    fn is_animated<'py>(data: &Bound<'py, PyBytes>) -> bool {
        is_animated_gif(data.as_bytes())
    }

    /// Get image dimensions without fully decoding
    #[staticmethod]
    fn get_dimensions<'py>(data: &Bound<'py, PyBytes>) -> PyResult<(u32, u32)> {
        let bytes = data.as_bytes();
        
        let reader = image::ImageReader::new(std::io::Cursor::new(bytes))
            .with_guessed_format()
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        
        let dims = reader.into_dimensions()
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        
        Ok(dims)
    }

    /// Convert image to base64
    #[staticmethod]
    fn encode_base64<'py>(data: &Bound<'py, PyBytes>) -> String {
        to_base64(data.as_bytes())
    }

    /// Decode base64 to bytes
    #[staticmethod]
    fn decode_base64<'py>(py: Python<'py>, encoded: &str) -> PyResult<Bound<'py, PyBytes>> {
        let bytes = from_base64(encoded)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok(PyBytes::new_bound(py, &bytes))
    }

    /// Batch resize multiple images (parallel, releases GIL)
    fn batch_resize<'py>(&self, py: Python<'py>, images: Vec<Bound<'py, PyBytes>>, max_width: u32, max_height: u32) -> PyResult<Vec<ImageData>> {
        use rayon::prelude::*;
        
        let bytes_list: Vec<Vec<u8>> = images.iter()
            .map(|b| b.as_bytes().to_vec())
            .collect();
        
        let quality = self.jpeg_quality;
        
        // Release the GIL during CPU-intensive parallel processing
        let results = py.allow_threads(|| {
            bytes_list
                .par_iter()
                .map(|bytes| resize_image(bytes, max_width, max_height, ResizeMode::Fit, quality))
                .collect::<Result<Vec<ImageData>, _>>()
        });
        
        results.map_err(|e| PyValueError::new_err(e.to_string()))
    }

    /// Get format from image bytes
    #[staticmethod]
    fn detect_format<'py>(data: &Bound<'py, PyBytes>) -> Option<String> {
        detect_format(data.as_bytes()).map(|s| s.to_string())
    }
}

/// Detect image format from magic bytes
fn detect_format(data: &[u8]) -> Option<&'static str> {
    if data.len() < 4 {
        return None;
    }
    
    match &data[0..4] {
        [0x89, 0x50, 0x4E, 0x47] => Some("png"),
        [0xFF, 0xD8, 0xFF, _] => Some("jpeg"),
        [0x47, 0x49, 0x46, 0x38] => Some("gif"),
        [0x52, 0x49, 0x46, 0x46] if data.len() >= 12 && &data[8..12] == b"WEBP" => Some("webp"),
        _ => None,
    }
}

/// Python module
#[pymodule]
fn media_processor(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<MediaProcessor>()?;
    m.add_class::<ImageData>()?;
    
    // Convenience functions
    m.add_function(wrap_pyfunction!(py_is_animated, m)?)?;
    m.add_function(wrap_pyfunction!(py_get_dimensions, m)?)?;
    m.add_function(wrap_pyfunction!(py_to_base64, m)?)?;
    
    // Version info
    m.add("__version__", "0.1.0")?;
    m.add("__author__", "voraehita25-star")?;
    
    Ok(())
}

#[pyfunction]
fn py_is_animated<'py>(data: &Bound<'py, PyBytes>) -> bool {
    is_animated_gif(data.as_bytes())
}

#[pyfunction]
fn py_get_dimensions<'py>(data: &Bound<'py, PyBytes>) -> PyResult<(u32, u32)> {
    MediaProcessor::get_dimensions(data)
}

#[pyfunction]
fn py_to_base64<'py>(data: &Bound<'py, PyBytes>) -> String {
    to_base64(data.as_bytes())
}
