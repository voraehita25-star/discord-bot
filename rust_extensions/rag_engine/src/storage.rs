//! Memory-mapped vector storage for persistent RAG

use memmap2::{MmapMut, MmapOptions};
use std::fs::{File, OpenOptions};
use std::path::Path;
use fs2::FileExt;

use crate::errors::RagError;

// On-disk file layout (always little-endian, host-independent):
//
//   offset  size  field
//   0       4     magic       = b"RAGV"
//   4       4     version     = u32
//   8       4     dimension   = u32
//   12      8     count       = u64
//   20      48    reserved    (zeroed)
//   68      ...   vectors     (count × dimension × f32 LE)
//
// The header is read/written via explicit `to_le_bytes`/`from_le_bytes`
// rather than as a packed struct so the format stays byte-stable across
// architectures and we never make unaligned accesses.

/// Memory-mapped vector storage
pub struct VectorStorage {
    mmap: Option<MmapMut>,
    file: Option<File>,
    dimension: usize,
    capacity: usize,
    count: usize,
}

impl VectorStorage {
    const MAGIC: [u8; 4] = *b"RAGV";
    const VERSION: u32 = 1;
    /// Size of the on-disk header. Kept fixed so existing files written by
    /// the old packed-struct layout (which was 68 bytes on every platform we
    /// care about — magic 4 + u32 4 + u32 4 + u64 8 + reserved 48) load
    /// without migration.
    const HEADER_SIZE: usize = 68;

    /// Create a new in-memory storage
    pub fn new(dimension: usize, capacity: usize) -> Self {
        Self {
            mmap: None,
            file: None,
            dimension,
            capacity,
            count: 0,
        }
    }

    /// Create or open a memory-mapped file
    pub fn open<P: AsRef<Path>>(path: P, dimension: usize, capacity: usize) -> Result<Self, RagError> {
        // Path traversal protection (defense in depth — callers should already
        // validate, but the open path is reachable via Python and would
        // otherwise let a relative ``../../`` escape the project root).
        Self::validate_path(path.as_ref())?;

        let vector_size = dimension.checked_mul(std::mem::size_of::<f32>())
            .ok_or_else(|| RagError::Serialization("Dimension overflow in vector size calculation".to_string()))?;
        // Use u64 for byte arithmetic so 32-bit hosts don't wrap on big indices.
        let file_size_u64: u64 = (Self::HEADER_SIZE as u64)
            .checked_add(
                (capacity as u64).checked_mul(vector_size as u64)
                    .ok_or_else(|| RagError::Serialization("Capacity overflow in file size calculation".to_string()))?
            )
            .ok_or_else(|| RagError::Serialization("File size overflow".to_string()))?;

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path.as_ref())?;

        // Acquire exclusive file lock to prevent concurrent modification
        file.lock_exclusive().map_err(|e| {
            RagError::Serialization(format!("Failed to acquire file lock: {}", e))
        })?;

        // Check existing file: only grow, never truncate existing data
        let existing_len = file.metadata()?.len();
        if existing_len > 0 && file_size_u64 < existing_len {
            // File already exists and is larger than requested capacity.
            // Use the existing file size to avoid truncating stored vectors.
            // Do NOT call set_len here.
        } else {
            file.set_len(file_size_u64)?;
            file.sync_all()?; // Ensure file size is committed before mmap
        }

        // SAFETY: the file is held under an exclusive flock so no other process
        // we know about will truncate or write to it. External processes that
        // ignore the lock could still SIGBUS us via truncation — bounds checks
        // in get()/push() guard the in-bounds path but a truncation between
        // bounds check and access is a fundamental mmap risk on POSIX.
        let mut mmap = unsafe { MmapOptions::new().map_mut(&file)? };

        // Initialize header if new file
        let header_bytes = &mmap[..Self::HEADER_SIZE];
        let magic = &header_bytes[0..4];

        if magic != Self::MAGIC {
            // New file, write header
            Self::write_header(&mut mmap, dimension, 0);
            mmap.flush()?;
        }

        // Decode header explicitly via little-endian byte conversions. This
        // makes the on-disk format byte-stable across architectures (the
        // previous bytemuck-of-packed-struct path silently produced a
        // different layout on a hypothetical big-endian host).
        let (hdr_version, hdr_dimension, hdr_count) = Self::read_header(&mmap)?;

        if hdr_version != Self::VERSION {
            return Err(RagError::Serialization(format!(
                "Unsupported storage version: expected {}, got {}",
                Self::VERSION, hdr_version
            )));
        }

        if hdr_dimension as usize != dimension {
            return Err(RagError::DimensionMismatch {
                expected: dimension,
                got: hdr_dimension as usize,
            });
        }

        // Use the larger of requested capacity or existing count
        let hdr_count = hdr_count as usize;
        let effective_capacity = capacity.max(hdr_count);

        Ok(Self {
            mmap: Some(mmap),
            file: Some(file),
            dimension,
            capacity: effective_capacity,
            count: hdr_count,
        })
    }

    /// Reject relative paths that try to climb above the working directory or
    /// reference Windows drive prefixes (``C:``, ``\\?\`` etc.) — both are a
    /// path-traversal vector when callers pass a string straight through.
    fn validate_path(p: &Path) -> Result<(), RagError> {
        if p.is_absolute() {
            return Err(RagError::Serialization(
                "Storage path must be relative to the project root".to_string(),
            ));
        }
        for component in p.components() {
            use std::path::Component;
            match component {
                Component::ParentDir => {
                    return Err(RagError::Serialization(
                        "Storage path may not contain '..' segments".to_string(),
                    ));
                }
                Component::Prefix(_) => {
                    // Windows drive / UNC prefixes — relative paths shouldn't have these
                    return Err(RagError::Serialization(
                        "Storage path may not contain a drive prefix".to_string(),
                    ));
                }
                _ => {}
            }
        }
        Ok(())
    }

    /// Encode the header into the mmap's first 64 bytes using little-endian
    /// byte order regardless of host architecture.
    fn write_header(mmap: &mut MmapMut, dimension: usize, count: u64) {
        let mut buf = [0u8; Self::HEADER_SIZE];
        buf[0..4].copy_from_slice(&Self::MAGIC);
        buf[4..8].copy_from_slice(&Self::VERSION.to_le_bytes());
        buf[8..12].copy_from_slice(&(dimension as u32).to_le_bytes());
        buf[12..20].copy_from_slice(&count.to_le_bytes());
        // buf[20..68] stays zero (reserved)
        mmap[..Self::HEADER_SIZE].copy_from_slice(&buf);
    }

    /// Decode (version, dimension, count) from the mmap header.
    fn read_header(mmap: &MmapMut) -> Result<(u32, u32, u64), RagError> {
        if mmap.len() < Self::HEADER_SIZE {
            return Err(RagError::Serialization("File smaller than header".to_string()));
        }
        let bytes = &mmap[..Self::HEADER_SIZE];
        let mut v = [0u8; 4];
        v.copy_from_slice(&bytes[4..8]);
        let version = u32::from_le_bytes(v);
        let mut d = [0u8; 4];
        d.copy_from_slice(&bytes[8..12]);
        let dimension = u32::from_le_bytes(d);
        let mut c = [0u8; 8];
        c.copy_from_slice(&bytes[12..20]);
        let count = u64::from_le_bytes(c);
        Ok((version, dimension, count))
    }

    /// Add a vector to storage
    pub fn push(&mut self, vector: &[f32]) -> Result<usize, RagError> {
        if vector.len() != self.dimension {
            return Err(RagError::DimensionMismatch {
                expected: self.dimension,
                got: vector.len(),
            });
        }

        // Reject NaN/Inf — persisting these silently corrupts every later
        // similarity score that touches this row, and serde_json refuses to
        // serialise them so a future RagEngine::save() over the same data
        // would also fail. Match RagEngine::add()'s validation.
        if vector.iter().any(|v| !v.is_finite()) {
            return Err(RagError::Serialization(
                "vector contains non-finite values (NaN/Inf)".to_string(),
            ));
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
            // Write the vector as little-endian f32 bytes regardless of host
            // byte order so the file format is portable across architectures.
            let mut buf = vec![0u8; vector_size];
            for (i, &f) in vector.iter().enumerate() {
                let i4 = i.checked_mul(4).ok_or_else(|| RagError::Serialization(
                    "Vector index overflow in byte conversion".to_string(),
                ))?;
                buf[i4..i4 + 4].copy_from_slice(&f.to_le_bytes());
            }
            let end = offset.checked_add(vector_size)
                .ok_or_else(|| RagError::Serialization("End offset overflow in push".to_string()))?;
            if end > mmap.len() {
                return Err(RagError::Serialization(format!(
                    "Write exceeds mmap bounds: offset {} + size {} > mmap len {}",
                    offset, vector_size, mmap.len()
                )));
            }
            mmap[offset..end].copy_from_slice(&buf);

            // Crash-safety ordering: flush the vector bytes BEFORE bumping the
            // count. If we crash between data-write and header-write, the
            // partially-written slot is invisible to later reads (count is
            // still old). The previous code wrote both in one flush, so a
            // torn write across pages could leave count incremented while
            // the vector bytes hadn't reached disk yet.
            //
            // mmap.flush() is `msync(MS_ASYNC)` on some platforms — it just
            // schedules the writeback. Follow it with file.sync_all() to
            // force fsync so the data actually hits disk before we update
            // and fsync the header. Without this, a power loss can leave a
            // bumped count pointing at vector bytes that were never durable.
            mmap.flush()?;
            if let Some(file) = &self.file {
                file.sync_all()?;
            }
            self.count += 1;
            Self::write_header(mmap, self.dimension, self.count as u64);
            mmap.flush()?;
            if let Some(file) = &self.file {
                file.sync_all()?;
            }
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
            // Decode little-endian f32 bytes. The previous bytemuck::cast_slice
            // path was endian-naive and would return garbage if the file had
            // ever been written by a big-endian host; with explicit LE we
            // round-trip correctly across architectures.
            let mut floats = Vec::with_capacity(self.dimension);
            for chunk in bytes.chunks_exact(4) {
                let mut b = [0u8; 4];
                b.copy_from_slice(chunk);
                floats.push(f32::from_le_bytes(b));
            }
            if floats.len() != self.dimension {
                return None;
            }
            Some(floats)
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

impl Drop for VectorStorage {
    fn drop(&mut self) {
        // Best-effort flush before unmapping. If a writer is mid-push and a
        // panic unwinds the stack, the previous behaviour dropped the mmap
        // before any pending dirty page made it to disk. flush() is a no-op
        // when there are no dirty pages, so this is cheap on the common path.
        if let Some(ref mut mmap) = self.mmap {
            let _ = mmap.flush();
        }
        // Drop mmap first to unmap memory before releasing file lock
        self.mmap.take();
        // Release file lock (unlock + close) by dropping the file handle
        if let Some(file) = self.file.take() {
            let _ = file.unlock();
        }
    }
}
