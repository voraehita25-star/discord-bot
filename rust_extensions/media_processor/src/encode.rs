//! Base64 encoding/decoding

use base64::{Engine as _, engine::general_purpose::STANDARD};

use crate::errors::MediaError;

/// Encode bytes to base64 string
pub fn to_base64(data: &[u8]) -> String {
    STANDARD.encode(data)
}

/// Decode base64 string to bytes
pub fn from_base64(encoded: &str) -> Result<Vec<u8>, MediaError> {
    STANDARD.decode(encoded)
        .map_err(|e| MediaError::Decode(e.to_string()))
}

/// Encode with data URI prefix
#[allow(dead_code)]
pub fn to_data_uri(data: &[u8], mime_type: &str) -> String {
    format!("data:{};base64,{}", mime_type, STANDARD.encode(data))
}

/// Extract base64 from data URI
#[allow(dead_code)]
pub fn from_data_uri(uri: &str) -> Result<Vec<u8>, MediaError> {
    let base64_part = if let Some(pos) = uri.find(",") {
        &uri[pos + 1..]
    } else {
        uri
    };
    
    from_base64(base64_part)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_roundtrip() {
        let original = b"Hello, World!";
        let encoded = to_base64(original);
        let decoded = from_base64(&encoded).unwrap();
        assert_eq!(original.as_slice(), decoded.as_slice());
    }

    #[test]
    fn test_data_uri() {
        let data = b"test image data";
        let uri = to_data_uri(data, "image/png");
        assert!(uri.starts_with("data:image/png;base64,"));
        
        let decoded = from_data_uri(&uri).unwrap();
        assert_eq!(data.as_slice(), decoded.as_slice());
    }
}
