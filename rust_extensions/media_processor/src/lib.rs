//! Media Processor - High-performance image processing
//!
//! A Rust-based media processor with:
//! - Fast image resizing
//! - GIF animation detection
//! - Base64 encoding/decoding
//! - Parallel batch processing

mod encode;
mod errors;
mod gif;
mod resize;

use image::GenericImageView;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

pub use encode::{from_base64, to_base64};
pub use errors::MediaError;
pub use gif::{get_gif_frame_count, is_animated_gif};
pub use resize::{resize_image, ResizeMode};

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
        Self {
            data,
            width,
            height,
            channels,
            format,
        }
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
        Self {
            max_dimension,
            jpeg_quality,
        }
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
    // Explicit signature so the trailing Option args are genuinely optional
    // from Python. Without it, pyo3 0.28 makes them REQUIRED positional args
    // (the implicit-None default for trailing Option was removed in 0.23),
    // so `resize(data)` — as the .pyi stub advertises — would TypeError.
    #[pyo3(signature = (data, max_width=None, max_height=None))]
    fn resize<'py>(
        &self,
        _py: Python<'py>,
        data: &Bound<'py, PyBytes>,
        max_width: Option<u32>,
        max_height: Option<u32>,
    ) -> PyResult<ImageData> {
        let bytes = data.as_bytes();
        check_bomb_dimensions(bytes)?;
        let max_w = max_width.unwrap_or(self.max_dimension);
        let max_h = max_height.unwrap_or(self.max_dimension);

        let result = resize_image(bytes, max_w, max_h, ResizeMode::Fit, self.jpeg_quality)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;

        Ok(result)
    }

    /// Resize image to exact dimensions (with cropping)
    fn resize_exact<'py>(
        &self,
        _py: Python<'py>,
        data: &Bound<'py, PyBytes>,
        width: u32,
        height: u32,
    ) -> PyResult<ImageData> {
        let bytes = data.as_bytes();
        check_bomb_dimensions(bytes)?;

        let result = resize_image(bytes, width, height, ResizeMode::Fill, self.jpeg_quality)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;

        Ok(result)
    }

    /// Create thumbnail
    fn thumbnail<'py>(
        &self,
        _py: Python<'py>,
        data: &Bound<'py, PyBytes>,
        size: u32,
    ) -> PyResult<ImageData> {
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

    /// Get image dimensions without fully decoding.
    ///
    /// Header-only: this reads the format header and never allocates a pixel
    /// buffer, so it is intentionally NOT routed through
    /// ``check_bomb_dimensions`` (there is nothing to bomb). If a future edit
    /// adds a full decode here, it MUST call ``check_bomb_dimensions`` first.
    #[staticmethod]
    fn get_dimensions<'py>(data: &Bound<'py, PyBytes>) -> PyResult<(u32, u32)> {
        let bytes = data.as_bytes();

        let reader = image::ImageReader::new(std::io::Cursor::new(bytes))
            .with_guessed_format()
            .map_err(|e| PyValueError::new_err(e.to_string()))?;

        let dims = reader
            .into_dimensions()
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
        let bytes = from_base64(encoded).map_err(|e| PyValueError::new_err(e.to_string()))?;
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
        let quality = self.jpeg_quality;
        let mut output = Vec::with_capacity(images.len());

        for chunk in images.chunks(BATCH_CHUNK_SIZE) {
            let bytes_list: Vec<Vec<u8>> = chunk.iter().map(|b| b.as_bytes().to_vec()).collect();
            // Release the GIL while this chunk's bytes are bomb-checked and
            // resized on the rayon worker pool (pure-Rust work). Chunking
            // bounds peak memory: we decode+resize one BATCH_CHUNK_SIZE chunk
            // at a time and drop its allocations before pulling the next,
            // instead of holding every decoded image at once.
            let chunk_results =
                py.detach(|| process_batch_chunk(&bytes_list, max_width, max_height, quality));
            output.extend(chunk_results?);
        }
        Ok(output)
    }

    /// Get format from image bytes.
    ///
    /// Header-only magic-byte sniff: never decodes pixels, so (like
    /// ``get_dimensions``) it intentionally skips ``check_bomb_dimensions``.
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
/// the full decode allocates pixel memory. ``checked_mul`` is belt-and-
/// suspenders: both dims are u32, so ``u32::MAX * u32::MAX`` (~1.8e19) still
/// fits in u64 and the None branch is effectively unreachable — it just makes
/// the intent explicit at zero cost. All public entry points that decode
/// untrusted bytes and DECODE pixels go through this so the 100MP cap is
/// enforced uniformly across the decoding entry points (load, resize,
/// resize_exact, thumbnail, batch_resize). The header-only entry points
/// (get_dimensions, detect_format) never allocate a pixel buffer and so are
/// intentionally guard-free — see their doc comments. The resize/resize_exact/thumbnail
/// wrappers do parse the header twice — once here and again inside
/// ``resize_image`` (resize.rs) — but the duplicate probe is cheap next to the
/// full decode and is deliberate defense-in-depth: ``resize_image`` is ``pub``
/// (and also reached via ``batch_resize``), so both layers keep the bomb guard
/// intact. Do NOT drop these calls to save the redundant header parse.
fn check_bomb_dimensions(bytes: &[u8]) -> PyResult<()> {
    let reader = image::ImageReader::new(std::io::Cursor::new(bytes))
        .with_guessed_format()
        .map_err(|e| PyValueError::new_err(format!("Failed to detect image format: {}", e)))?;
    match reader.into_dimensions() {
        Ok((w, h)) => {
            let product = (w as u64).checked_mul(h as u64).ok_or_else(|| {
                PyValueError::new_err(format!("Image dimensions overflow: {}x{}", w, h))
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

/// Max images decoded+resized concurrently per chunk in batch_resize.
/// Bounds peak memory so a large batch can't hold every decoded image at once.
const BATCH_CHUNK_SIZE: usize = 8;

/// Resize one chunk of already-copied image byte buffers.
///
/// Factored out of the ``batch_resize`` ``#[pymethods]`` wrapper so the
/// security-critical batch path (the per-chunk decompression-bomb guard and
/// the parallel resize) is unit-testable WITHOUT a Python interpreter — the
/// wrapper just copies ``PyBytes`` to ``Vec<u8>`` and calls this inside
/// ``py.detach`` to release the GIL. Behavior is identical to the previous
/// inline body: EVERY input in the chunk is bomb-checked BEFORE any decode, so
/// a single hostile image rejects the whole chunk before the rayon pool
/// allocates unbounded pixel buffers; then the chunk is resized in parallel,
/// preserving input order.
fn process_batch_chunk(
    bytes_list: &[Vec<u8>],
    max_width: u32,
    max_height: u32,
    quality: u8,
) -> PyResult<Vec<ImageData>> {
    use rayon::prelude::*;

    for bytes in bytes_list {
        check_bomb_dimensions(bytes)?;
    }
    bytes_list
        .par_iter()
        .map(|bytes| resize_image(bytes, max_width, max_height, ResizeMode::Fit, quality))
        .collect::<Result<Vec<ImageData>, _>>()
        .map_err(|e| PyValueError::new_err(e.to_string()))
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    /// Encode a real, tiny RGB PNG so decode/resize paths get valid input.
    fn tiny_png(w: u32, h: u32) -> Vec<u8> {
        let img = image::RgbImage::from_fn(w, h, |x, y| {
            image::Rgb([(x % 256) as u8, (y % 256) as u8, 128])
        });
        let mut out = Vec::new();
        image::DynamicImage::ImageRgb8(img)
            .write_to(&mut Cursor::new(&mut out), image::ImageFormat::Png)
            .unwrap();
        out
    }

    /// Hand-craft a PNG whose IHDR advertises `w`x`h` with NO real pixel data.
    /// `into_dimensions()` reads only the header, so this lets check_bomb_dimensions
    /// see a >100MP image without allocating one (a decompression-bomb stand-in).
    fn png_header_claiming(w: u32, h: u32) -> Vec<u8> {
        let mut v = vec![0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]; // signature
        // IHDR chunk: length (13), type, 13 bytes of data, CRC.
        v.extend_from_slice(&13u32.to_be_bytes());
        let mut chunk = Vec::new();
        chunk.extend_from_slice(b"IHDR");
        chunk.extend_from_slice(&w.to_be_bytes());
        chunk.extend_from_slice(&h.to_be_bytes());
        chunk.push(8); // bit depth
        chunk.push(2); // color type = RGB
        chunk.push(0); // compression
        chunk.push(0); // filter
        chunk.push(0); // interlace
        let crc = png_crc(&chunk);
        v.extend_from_slice(&chunk);
        v.extend_from_slice(&crc.to_be_bytes());
        v
    }

    /// CRC-32 (PNG/zlib polynomial) over a chunk's type+data, as PNG requires.
    fn png_crc(bytes: &[u8]) -> u32 {
        let mut crc: u32 = 0xFFFF_FFFF;
        for &b in bytes {
            crc ^= b as u32;
            for _ in 0..8 {
                crc = if crc & 1 != 0 {
                    (crc >> 1) ^ 0xEDB8_8320
                } else {
                    crc >> 1
                };
            }
        }
        crc ^ 0xFFFF_FFFF
    }

    #[test]
    fn check_bomb_dimensions_rejects_over_100mp() {
        // 20000 x 20000 = 400 MP, well over the 100MP cap.
        let bomb = png_header_claiming(20_000, 20_000);
        assert!(check_bomb_dimensions(&bomb).is_err());
    }

    #[test]
    fn check_bomb_dimensions_accepts_small_image() {
        let ok = tiny_png(8, 8);
        assert!(check_bomb_dimensions(&ok).is_ok());
    }

    #[test]
    fn process_batch_chunk_rejects_bomb_before_decode() {
        // One valid image + one header-only bomb in the same chunk: the
        // per-chunk guard must reject the WHOLE chunk before any worker decodes.
        let good = tiny_png(8, 8);
        let bomb = png_header_claiming(20_000, 20_000);
        let chunk = vec![good, bomb];
        assert!(process_batch_chunk(&chunk, 4, 4, 85).is_err());
    }

    #[test]
    fn process_batch_chunk_preserves_order_and_length() {
        // Distinct sizes so we can assert order is preserved through the
        // parallel resize. All within the 4x4 Fit bound -> all downscaled.
        let inputs = vec![tiny_png(20, 10), tiny_png(10, 20), tiny_png(16, 16)];
        let out = process_batch_chunk(&inputs, 4, 4, 85).unwrap();
        assert_eq!(out.len(), 3);
        // Fit keeps aspect: 20x10 -> wider than tall, 10x20 -> taller than wide.
        assert!(out[0].width >= out[0].height);
        assert!(out[1].height >= out[1].width);
        // None degenerate.
        for img in &out {
            assert!(img.width >= 1 && img.height >= 1);
        }
    }

    #[test]
    fn batch_chunk_size_is_respected_across_boundary() {
        // Feed more than BATCH_CHUNK_SIZE images through the same helper the
        // wrapper calls per chunk, simulating two chunks (8 + 2), and assert
        // the stitched output length/order matches the input. This pins the
        // chunk-boundary stitching the memory-bounding comment describes.
        let n = BATCH_CHUNK_SIZE + 2;
        let inputs: Vec<Vec<u8>> = (0..n).map(|_| tiny_png(12, 6)).collect();
        let mut output = Vec::new();
        for chunk in inputs.chunks(BATCH_CHUNK_SIZE) {
            output.extend(process_batch_chunk(chunk, 4, 4, 85).unwrap());
        }
        assert_eq!(output.len(), n);
        for img in &output {
            // 12x6 fit into 4x4 -> width >= height (landscape preserved).
            assert!(img.width >= img.height);
        }
    }

    #[test]
    fn detect_format_identifies_png() {
        let png = tiny_png(4, 4);
        assert_eq!(detect_format(&png), Some("png"));
        // Too-short input returns None.
        assert_eq!(detect_format(&[0x89, 0x50]), None);
    }
}
