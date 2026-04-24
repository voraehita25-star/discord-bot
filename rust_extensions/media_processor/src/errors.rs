//! Error types for Media Processor

use thiserror::Error;

#[derive(Error, Debug)]
pub enum MediaError {
    #[error("Image error: {0}")]
    Image(#[from] image::ImageError),

    #[error("Decode error: {0}")]
    Decode(String),

    #[error("Encode error: {0}")]
    Encode(String),

    #[error("Unsupported format: {0}")]
    UnsupportedFormat(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}
