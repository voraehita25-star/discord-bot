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
pub use gif::{is_animated_gif, get_gif_frame_count};
pub use encode::{to_base64, from_base64};
pub use errors::MediaError;

/// Image data container
#[pyclass(from_py_object)]
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
        PyBytes::new(py, &self.data)
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

        check_bomb_dimensions(bytes)?;

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
        check_bomb_dimensions(bytes)?;
        let max_w = max_width.unwrap_or(self.max_dimension);
        let max_h = max_height.unwrap_or(self.max_dimension);

        let result = resize_image(bytes, max_w, max_h, ResizeMode::Fit, self.jpeg_quality)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;

        Ok(result)
    }

    /// Resize image to exact dimensions (with cropping)
    fn resize_exact<'py>(&self, _py: Python<'py>, data: &Bound<'py, PyBytes>, width: u32, height: u32) -> PyResult<ImageData> {
        let bytes = data.as_bytes();
        check_bomb_dimensions(bytes)?;

        let result = resize_image(bytes, width, height, ResizeMode::Fill, self.jpeg_quality)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;

        Ok(result)
    }

    /// Create thumbnail
    fn thumbnail<'py>(&self, _py: Python<'py>, data: &Bound<'py, PyBytes>, size: u32) -> PyResult<ImageData> {
        let bytes = data.as_bytes();
        check_bomb_dimensions(bytes)?;

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
        Ok(PyBytes::new(py, &bytes))
    }

    /// Batch resize multiple images (parallel, releases GIL).
    ///
    /// Processes inputs in chunks to bound peak memory: previously the
    /// full ``Vec<Vec<u8>>`` of decoded image bytes was held in memory
    /// at once, so a 100-image batch of 5 MB JPEGs would spike to
    /// ~500 MB before resize. We now decode-and-resize one chunk at a
    /// time, releasing the chunk's allocations before pulling the next.
    fn batch_resize<'py>(
        &self,
        py: Python<'py>,
        images: Vec<Bound<'py, PyBytes>>,
        max_width: u32,
        max_height: u32,
    ) -> PyResult<Vec<ImageData>> {
        use rayon::prelude::*;

        const BATCH_CHUNK_SIZE: usize = 8;
        let quality = self.jpeg_quality;
        let mut output = Vec::with_capacity(images.len());

        for chunk in images.chunks(BATCH_CHUNK_SIZE) {
            let bytes_list: Vec<Vec<u8>> =
                chunk.iter().map(|b| b.as_bytes().to_vec()).collect();
            // Enforce the 100MP decompression-bomb cap on every input
            // before we hand the chunk to rayon. The single-image
            // entry points (load / resize / resize_exact / thumbnail)
            // all call this; previously the batch path bypassed it,
            // letting a single hostile image inside a batch allocate
            // unbounded pixel buffers on the rayon worker pool.
            for bytes in &bytes_list {
                check_bomb_dimensions(bytes)?;
            }
            let chunk_results = py.detach(|| {
                bytes_list
                    .par_iter()
                    .map(|bytes| resize_image(bytes, max_width, max_height, ResizeMode::Fit, quality))
                    .collect::<Result<Vec<ImageData>, _>>()
            });
            let chunk_results = chunk_results.map_err(|e| PyValueError::new_err(e.to_string()))?;
            output.extend(chunk_results);
        }
        Ok(output)
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

/// Reject decompression-bomb inputs by reading the header dimensions before
/// the full decode allocates pixel memory. ``u64::checked_mul`` guards
/// against ``u32::MAX * u32::MAX`` overflowing past the 100MP check.
/// All public entry points that decode untrusted bytes go through this so
/// the 100MP cap is enforced uniformly (load, resize, resize_exact,
/// thumbnail).
fn check_bomb_dimensions(bytes: &[u8]) -> PyResult<()> {
    let reader = image::ImageReader::new(std::io::Cursor::new(bytes))
        .with_guessed_format()
        .map_err(|e| PyValueError::new_err(format!("Failed to detect image format: {}", e)))?;
    match reader.into_dimensions() {
        Ok((w, h)) => {
            let product = (w as u64).checked_mul(h as u64).ok_or_else(|| {
                PyValueError::new_err(format!(
                    "Image dimensions overflow: {}x{}",
                    w, h
                ))
            })?;
            if product > 100_000_000 {
                return Err(PyValueError::new_err(format!(
                    "Image too large: {}x{} exceeds 100MP limit",
                    w, h
                )));
            }
            Ok(())
        }
        Err(e) => Err(PyValueError::new_err(format!(
            "Cannot determine image dimensions (possible decompression bomb): {}",
            e
        ))),
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

    // Version info — sourced from Cargo's compile-time env so the
    // exposed ``__version__`` can't drift away from Cargo.toml. The
    // workspace inherits ``version.workspace = true`` so a single bump
    // updates both the Cargo metadata and the Python-visible value.
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
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
