//! Error types for RAG Engine

use thiserror::Error;

#[derive(Error, Debug)]
pub enum RagError {
    #[error("Dimension mismatch: expected {expected}, got {got}")]
    DimensionMismatch { expected: usize, got: usize },

    #[error("Storage capacity exceeded")]
    CapacityExceeded,

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Serialization error: {0}")]
    Serialization(String),
}
