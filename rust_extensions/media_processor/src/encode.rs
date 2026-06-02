//! Base64 encoding/decoding

use base64::{engine::general_purpose::STANDARD, Engine as _};

use crate::errors::MediaError;

/// Encode bytes to base64 string
pub fn to_base64(data: &[u8]) -> String {
    STANDARD.encode(data)
}

/// Decode base64 string to bytes
pub fn from_base64(encoded: &str) -> Result<Vec<u8>, MediaError> {
    STANDARD
        .decode(encoded)
        .map_err(|e| MediaError::Decode(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_roundtrip() {
        let original = b"Hello, World!";
        let encoded = to_base64(original);
        let decoded = from_base64(&encoded).expect("Failed to decode base64");
        assert_eq!(original.as_slice(), decoded.as_slice());
    }
}
