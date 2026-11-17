//! Versioned C ABI for an explicitly opted-in, isolated Python worker.
//!
//! Input is borrowed for one call. A successful decode returns UTF-8 JSON in an
//! owned allocation, without a trailing NUL; free its exact pointer and length
//! once with `ba_free_buffer`. Failure leaves a valid output slot null/zero.
//! Statuses carry no dynamically allocated error text or native exception data.
//!
//! Unwinding Rust panics are contained at this boundary. Invalid foreign memory,
//! double frees, allocator aborts and panic=abort builds cannot be recovered by
//! catch_unwind; callers must uphold the documented pointer/ownership contract.
//! The input and JSON bounds do not bound all intermediate decoder allocations.

use crate::{MAX_SNAPSHOT_BYTES, Snapshot, decode_snapshot};
use std::{
    io::{self, Write},
    panic::{UnwindSafe, catch_unwind},
    ptr, slice,
};

pub const ABI_VERSION: u32 = 1;
pub const MAX_JSON_BYTES: usize = 64 * 1024 * 1024;
pub const STATUS_OK: i32 = 0;
pub const STATUS_ARGUMENT: i32 = 1;
pub const STATUS_SNAPSHOT: i32 = 2;
pub const STATUS_JSON: i32 = 3;
pub const STATUS_PANIC: i32 = 4;

/// C layout: `{ uint8_t *data; size_t len; }`.
#[repr(C)]
#[derive(Debug)]
pub struct BaBuffer {
    pub data: *mut u8,
    pub len: usize,
}

impl Default for BaBuffer {
    fn default() -> Self {
        Self {
            data: ptr::null_mut(),
            len: 0,
        }
    }
}

struct BoundedJson {
    bytes: Vec<u8>,
    limit: usize,
}

impl Write for BoundedJson {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        let end = self
            .bytes
            .len()
            .checked_add(buffer.len())
            .filter(|&end| end <= self.limit)
            .ok_or_else(|| io::Error::other("JSON output exceeds limit"))?;
        if end > self.bytes.capacity() {
            // Grow geometrically without asking the allocator for more than the
            // output ceiling. try_reserve_exact avoids Vec's larger growth rule.
            let capacity = end
                .checked_next_power_of_two()
                .unwrap_or(self.limit)
                .max(1024)
                .min(self.limit);
            self.bytes
                .try_reserve_exact(capacity - self.bytes.len())
                .map_err(|_| io::Error::other("JSON output allocation failed"))?;
        }
        self.bytes.extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn serialize(snapshot: &Snapshot, limit: usize) -> Result<Box<[u8]>, i32> {
    let mut output = BoundedJson {
        bytes: Vec::new(),
        limit,
    };
    serde_json::to_writer(&mut output, snapshot).map_err(|_| STATUS_JSON)?;
    Ok(output.bytes.into_boxed_slice())
}

fn protected<T>(operation: impl FnOnce() -> Result<T, i32> + UnwindSafe) -> Result<T, i32> {
    catch_unwind(operation).unwrap_or(Err(STATUS_PANIC))
}

/// Return the exact ABI revision implemented by this library.
#[unsafe(no_mangle)]
pub extern "C" fn ba_snapshot_decoder_abi_version() -> u32 {
    ABI_VERSION
}

/// Decode a snapshot into one owned JSON buffer.
///
/// `include_entities` must be 0 or 1. `data` may be null only when `len` is zero;
/// empty input is a snapshot error. Oversized input is an argument error.
/// Null or misaligned `out` is an argument error and is never dereferenced.
/// A valid output slot is cleared before any other validation. It must not hold
/// an earlier allocation that still needs freeing.
///
/// # Safety
/// For a non-null, aligned `out`, the caller must provide exclusive writable
/// storage for one `BaBuffer`. For nonzero `len` within the input bound, a
/// non-null `data` must point to that many initialized, readable bytes in one
/// allocation, remaining immutable for the call. The two regions must not
/// overlap. Success transfers one buffer to the caller, which must free it
/// exactly once with this same loaded library before unloading the library.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ba_decode_snapshot(
    data: *const u8,
    len: usize,
    viewer: u32,
    include_entities: u8,
    out: *mut BaBuffer,
) -> i32 {
    if out.is_null() || !out.is_aligned() {
        return STATUS_ARGUMENT;
    }
    // SAFETY: the caller provides a valid, exclusive, aligned output slot.
    unsafe { out.write(BaBuffer::default()) };
    if len > MAX_SNAPSHOT_BYTES || include_entities > 1 || data.is_null() && len != 0 {
        return STATUS_ARGUMENT;
    }
    let result = protected(|| {
        let bytes = if len == 0 {
            &[]
        } else {
            // SAFETY: null/length checks above and caller-owned readable input.
            unsafe { slice::from_raw_parts(data, len) }
        };
        let snapshot =
            decode_snapshot(bytes, viewer, include_entities != 0).map_err(|_| STATUS_SNAPSHOT)?;
        serialize(&snapshot, MAX_JSON_BYTES)
    });
    match result {
        Ok(bytes) => {
            let len = bytes.len();
            let data = Box::into_raw(bytes).cast::<u8>();
            // SAFETY: the same valid output slot now receives transferred ownership.
            unsafe { out.write(BaBuffer { data, len }) };
            STATUS_OK
        }
        Err(status) => status,
    }
}

/// Release a successful decode's exact pointer and length. Null/zero is a no-op.
/// Malformed null/length pairs and lengths outside the output bound are refused.
///
/// # Safety
/// A non-null pointer with a nonzero in-bound length must be an allocation
/// returned by `ba_decode_snapshot` from this same loaded library, with the exact
/// original length. It must not have been freed, and no references/readers may
/// remain. This function cannot validate allocation provenance or double frees.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ba_free_buffer(data: *mut u8, len: usize) -> i32 {
    if data.is_null() {
        return if len == 0 { STATUS_OK } else { STATUS_ARGUMENT };
    }
    if len == 0 || len > MAX_JSON_BYTES {
        return STATUS_ARGUMENT;
    }
    protected(|| {
        // SAFETY: the caller returns the exact live Box<[u8]> allocation once.
        unsafe { drop(Box::from_raw(ptr::slice_from_raw_parts_mut(data, len))) };
        Ok(())
    })
    .map_or_else(|status| status, |()| STATUS_OK)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn call(bytes: &[u8], viewer: u32, entities: u8) -> (i32, BaBuffer) {
        let mut out = BaBuffer::default();
        // SAFETY: live immutable input and disjoint exclusive output storage.
        let status =
            unsafe { ba_decode_snapshot(bytes.as_ptr(), bytes.len(), viewer, entities, &mut out) };
        (status, out)
    }

    fn read(out: &BaBuffer) -> Vec<u8> {
        assert!(!out.data.is_null());
        assert!((1..=MAX_JSON_BYTES).contains(&out.len));
        // SAFETY: the tests retain ownership until a subsequent free.
        unsafe { slice::from_raw_parts(out.data, out.len) }.to_vec()
    }

    fn free(out: BaBuffer) {
        // SAFETY: moved, exact buffer obtained from one successful call.
        assert_eq!(unsafe { ba_free_buffer(out.data, out.len) }, STATUS_OK);
    }

    fn position_snapshot(position: [u32; 3]) -> [u8; 80] {
        let mut bytes = [0; 80];
        for (offset, value) in [
            (4, 20u16),
            (6, 8),
            (22, 4),
            (32, 8),
            (34, 12),
            (36, 4),
            (38, 8),
        ] {
            bytes[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
        }
        for (offset, value) in [
            (0, 24u32),
            (24, 20),
            (28, 12),
            (40, 8),
            (44, 12),
            (48, 16),
            (56, 1),
            (60, 1),
            (64, 1),
        ] {
            bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        for (index, value) in position.into_iter().enumerate() {
            bytes[68 + index * 4..72 + index * 4].copy_from_slice(&value.to_le_bytes());
        }
        bytes
    }

    #[test]
    fn abi_layout_and_owned_json_match_the_safe_decoder() {
        assert_eq!(ba_snapshot_decoder_abi_version(), 1);
        assert_eq!(
            std::mem::offset_of!(BaBuffer, len),
            std::mem::size_of::<*mut u8>()
        );
        assert_eq!(
            std::mem::size_of::<BaBuffer>(),
            2 * std::mem::size_of::<usize>()
        );
        let bytes = position_snapshot([
            (-0.0f32).to_bits(),
            f32::MIN_POSITIVE.to_bits(),
            f32::MAX.to_bits(),
        ]);
        for viewer in [0, 31, 32, u32::MAX] {
            for entities in [0, 1] {
                let expected =
                    serde_json::to_vec(&decode_snapshot(&bytes, viewer, entities != 0).unwrap())
                        .unwrap();
                let (status, out) = call(&bytes, viewer, entities);
                assert_eq!(status, STATUS_OK);
                assert_eq!(read(&out), expected);
                free(out);
            }
        }
    }

    #[test]
    fn results_have_independent_ownership_and_survive_input_drop() {
        let (status_a, a) = call(&Vec::from([0; 4]), 0, 0);
        let (status_b, b) = call(&[0; 4], u32::MAX, 1);
        assert_eq!((status_a, status_b), (STATUS_OK, STATUS_OK));
        assert_ne!(a.data, b.data);
        let expected_b = read(&b);
        free(a);
        assert_eq!(read(&b), expected_b);
        free(b);
        let (status_c, c) = call(&[0; 4], 31, 1);
        assert_eq!(status_c, STATUS_OK);
        free(c);
    }

    #[test]
    fn rejected_arguments_and_snapshots_leave_no_partial_output() {
        let mut out = BaBuffer {
            data: ptr::dangling_mut(),
            len: usize::MAX,
        };
        // SAFETY: oversize input is rejected before the deliberately unused pointer;
        // out is valid exclusive storage and contains no owned allocation.
        assert_eq!(
            unsafe { ba_decode_snapshot(ptr::dangling(), MAX_SNAPSHOT_BYTES + 1, 31, 1, &mut out) },
            STATUS_ARGUMENT
        );
        assert!(out.data.is_null());
        assert_eq!(out.len, 0);
        // SAFETY: recognized null/unaligned arguments are not dereferenced.
        assert_eq!(
            unsafe { ba_decode_snapshot(ptr::null(), 0, 31, 1, ptr::null_mut()) },
            STATUS_ARGUMENT
        );
        let mut storage = [0u8; std::mem::size_of::<BaBuffer>() + 1];
        let candidate = storage.as_mut_ptr().cast::<BaBuffer>();
        let unaligned = if candidate.is_aligned() {
            storage[1..].as_mut_ptr().cast::<BaBuffer>()
        } else {
            candidate
        };
        assert_eq!(
            unsafe { ba_decode_snapshot(ptr::null(), 0, 31, 1, unaligned) },
            STATUS_ARGUMENT
        );
        assert_eq!(
            unsafe { ba_decode_snapshot(ptr::null(), 1, 31, 1, &mut out) },
            STATUS_ARGUMENT
        );
        assert_eq!(
            unsafe { ba_decode_snapshot(ptr::null(), 0, 31, 1, &mut out) },
            STATUS_SNAPSHOT
        );
        for (bytes, entities, expected) in [
            (&[0; 4][..], 2, STATUS_ARGUMENT),
            (&[0; 3][..], 1, STATUS_SNAPSHOT),
            (&[255; 4][..], 1, STATUS_SNAPSHOT),
        ] {
            let (status, out) = call(bytes, 31, entities);
            assert_eq!(status, expected);
            assert!(out.data.is_null());
            assert_eq!(out.len, 0);
        }
        // SAFETY: malformed combinations below are rejected without pointer access.
        assert_eq!(unsafe { ba_free_buffer(ptr::null_mut(), 0) }, STATUS_OK);
        assert_eq!(
            unsafe { ba_free_buffer(ptr::null_mut(), 1) },
            STATUS_ARGUMENT
        );
        assert_eq!(
            unsafe { ba_free_buffer(ptr::dangling_mut(), 0) },
            STATUS_ARGUMENT
        );
        assert_eq!(
            unsafe { ba_free_buffer(ptr::dangling_mut(), MAX_JSON_BYTES + 1) },
            STATUS_ARGUMENT
        );
    }

    #[test]
    fn nonfinite_json_refusal_does_not_break_later_calls_or_summary_mode() {
        for value in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
            let bytes = position_snapshot([0, value.to_bits(), 0]);
            let (status, out) = call(&bytes, 31, 1);
            assert_eq!(status, STATUS_JSON);
            assert!(out.data.is_null());
            assert_eq!(out.len, 0);
            let (status, summary) = call(&bytes, 31, 0);
            assert_eq!(status, STATUS_OK);
            free(summary);
            let (status, ordinary) = call(&[0; 4], 31, 1);
            assert_eq!(status, STATUS_OK);
            free(ordinary);
        }
    }

    #[test]
    fn serializer_enforces_exact_ceiling_and_panics_become_statuses() {
        let snapshot = decode_snapshot(&[0; 4], 31, true).unwrap();
        let expected = serde_json::to_vec(&snapshot).unwrap();
        assert_eq!(&*serialize(&snapshot, expected.len()).unwrap(), expected);
        assert_eq!(serialize(&snapshot, expected.len() - 1), Err(STATUS_JSON));
        let mut writer = BoundedJson {
            bytes: Vec::new(),
            limit: 4,
        };
        writer.write_all(b"1234").unwrap();
        assert!(writer.write_all(b"5").is_err());
        assert_eq!(writer.bytes, b"1234");
        assert!(writer.bytes.capacity() <= writer.limit);
        assert_eq!(
            protected::<()>(|| panic!("authored boundary panic")),
            Err(STATUS_PANIC)
        );
        assert_eq!(protected(|| Ok(17)), Ok(17));
    }
}
