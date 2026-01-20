//! Memory-mapped vector storage for persistent RAG

use memmap2::{MmapMut, MmapOptions};
use std::fs::{File, OpenOptions};
use std::path::Path;
use bytemuck::{Pod, Zeroable};

use crate::errors::RagError;

/// Header for the vector storage file
#[repr(C)]
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
        let vector_size = dimension * std::mem::size_of::<f32>();
        let file_size = Self::HEADER_SIZE + capacity * vector_size;

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(path.as_ref())?;

        file.set_len(file_size as u64)?;

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
        
        if header.dimension as usize != dimension {
            return Err(RagError::DimensionMismatch {
                expected: dimension,
                got: header.dimension as usize,
            });
        }

        Ok(Self {
            mmap: Some(mmap),
            dimension,
            capacity,
            count: header.count as usize,
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
            let offset = Self::HEADER_SIZE + idx * vector_size;
            let bytes: &[u8] = bytemuck::cast_slice(vector);
            mmap[offset..offset + vector_size].copy_from_slice(bytes);
            
            // Update count in header
            self.count += 1;
            let count_offset = 12; // After magic + version + dimension
            mmap[count_offset..count_offset + 8].copy_from_slice(&(self.count as u64).to_le_bytes());
        } else {
            self.count += 1;
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
            let offset = Self::HEADER_SIZE + idx * vector_size;
            let bytes = &mmap[offset..offset + vector_size];
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
