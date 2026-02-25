//! Memory-mapped vector storage for persistent RAG

use memmap2::{MmapMut, MmapOptions};
use std::fs::OpenOptions;
use std::path::Path;
use bytemuck::{Pod, Zeroable};

use crate::errors::RagError;

/// Header for the vector storage file
#[repr(C, packed)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct StorageHeader {
    magic: [u8; 4],      // "RAGV"
    version: u32,
    dimension: u32,
    count: u64,
    reserved: [u8; 48],  // Future use
}

/// Memory-mapped vector storage
pub struct VectorStorage {
    mmap: Option<MmapMut>,
    dimension: usize,
    capacity: usize,
    count: usize,
}

impl VectorStorage {
    const MAGIC: [u8; 4] = *b"RAGV";
    const VERSION: u32 = 1;
    const HEADER_SIZE: usize = std::mem::size_of::<StorageHeader>();

    /// Create a new in-memory storage
    pub fn new(dimension: usize, capacity: usize) -> Self {
        Self {
            mmap: None,
            dimension,
            capacity,
            count: 0,
        }
    }

    /// Create or open a memory-mapped file
    pub fn open<P: AsRef<Path>>(path: P, dimension: usize, capacity: usize) -> Result<Self, RagError> {
        let vector_size = dimension.checked_mul(std::mem::size_of::<f32>())
            .ok_or_else(|| RagError::Serialization("Dimension overflow in vector size calculation".to_string()))?;
        let file_size = Self::HEADER_SIZE
            .checked_add(
                capacity.checked_mul(vector_size)
                    .ok_or_else(|| RagError::Serialization("Capacity overflow in file size calculation".to_string()))?
            )
            .ok_or_else(|| RagError::Serialization("File size overflow".to_string()))?;

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(path.as_ref())?;

        // Check existing file: only grow, never truncate existing data
        let existing_len = file.metadata()?.len();
        if existing_len > 0 && (file_size as u64) < existing_len {
            // File already exists and is larger than requested capacity.
            // Use the existing file size to avoid truncating stored vectors.
            // Do NOT call set_len here.
        } else {
            file.set_len(file_size as u64)?;
        }

        let mut mmap = unsafe { MmapOptions::new().map_mut(&file)? };

        // Initialize header if new file
        let header_bytes = &mmap[..Self::HEADER_SIZE];
        let magic = &header_bytes[0..4];
        
        if magic != Self::MAGIC {
            // New file, write header
            let header = StorageHeader {
                magic: Self::MAGIC,
                version: Self::VERSION,
                dimension: dimension as u32,
                count: 0,
                reserved: [0; 48],
            };
            mmap[..Self::HEADER_SIZE].copy_from_slice(bytemuck::bytes_of(&header));
            mmap.flush()?;
        }

        // Read header to get count
        let header: StorageHeader = *bytemuck::from_bytes(&mmap[..Self::HEADER_SIZE]);

        // Validate version (copy packed field to local to avoid unaligned access)
        let hdr_version = header.version;
        if hdr_version != Self::VERSION {
            return Err(RagError::Serialization(format!(
                "Unsupported storage version: expected {}, got {}",
                Self::VERSION, hdr_version
            )));
        }

        let hdr_dimension = header.dimension as usize;
        if hdr_dimension != dimension {
            return Err(RagError::DimensionMismatch {
                expected: dimension,
                got: hdr_dimension,
            });
        }

        // Use the larger of requested capacity or existing count
        let hdr_count = header.count as usize;
        let effective_capacity = capacity.max(hdr_count);

        Ok(Self {
            mmap: Some(mmap),
            dimension,
            capacity: effective_capacity,
            count: hdr_count,
        })
    }

    /// Add a vector to storage
    pub fn push(&mut self, vector: &[f32]) -> Result<usize, RagError> {
        if vector.len() != self.dimension {
            return Err(RagError::DimensionMismatch {
                expected: self.dimension,
                got: vector.len(),
            });
        }

        if self.count >= self.capacity {
            return Err(RagError::CapacityExceeded);
        }

        let idx = self.count;
        
        if let Some(ref mut mmap) = self.mmap {
            let vector_size = self.dimension * std::mem::size_of::<f32>();
            let offset = Self::HEADER_SIZE.checked_add(
                idx.checked_mul(vector_size)
                    .ok_or_else(|| RagError::Serialization("Index overflow in push".to_string()))?
            ).ok_or_else(|| RagError::Serialization("Offset overflow in push".to_string()))?;
            let bytes: &[u8] = bytemuck::cast_slice(vector);
            let end = offset.checked_add(vector_size)
                .ok_or_else(|| RagError::Serialization("End offset overflow in push".to_string()))?;
            if end > mmap.len() {
                return Err(RagError::Serialization(format!(
                    "Write exceeds mmap bounds: offset {} + size {} > mmap len {}",
                    offset, vector_size, mmap.len()
                )));
            }
            mmap[offset..end].copy_from_slice(bytes);
            
            // Update count in header via full header struct rewrite
            self.count += 1;
            let header = StorageHeader {
                magic: Self::MAGIC,
                version: Self::VERSION,
                dimension: self.dimension as u32,
                count: self.count as u64,
                reserved: [0; 48],
            };
            mmap[..Self::HEADER_SIZE].copy_from_slice(bytemuck::bytes_of(&header));
            
            // Flush to ensure data is persisted to disk
            mmap.flush()?;
        } else {
            return Err(RagError::Serialization("Cannot push vectors without file backing (in-memory mode not supported)".to_string()));
        }

        Ok(idx)
    }

    /// Get a vector by index
    pub fn get(&self, idx: usize) -> Option<Vec<f32>> {
        if idx >= self.count {
            return None;
        }

        if let Some(ref mmap) = self.mmap {
            let vector_size = self.dimension * std::mem::size_of::<f32>();
            let offset = Self::HEADER_SIZE.checked_add(idx.checked_mul(vector_size)?)?;
            let end = offset.checked_add(vector_size)?;
            // Bounds check to prevent panic on corrupted/truncated file
            if end > mmap.len() {
                return None;
            }
            let bytes = &mmap[offset..end];
            let floats: &[f32] = bytemuck::cast_slice(bytes);
            Some(floats.to_vec())
        } else {
            None
        }
    }

    /// Get number of stored vectors
    pub fn len(&self) -> usize {
        self.count
    }

    /// Check if storage is empty
    pub fn is_empty(&self) -> bool {
        self.count == 0
    }

    /// Flush changes to disk
    pub fn flush(&mut self) -> Result<(), RagError> {
        if let Some(ref mut mmap) = self.mmap {
            mmap.flush()?;
        }
        Ok(())
    }
}
