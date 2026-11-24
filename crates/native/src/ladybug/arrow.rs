use std::ffi::{CStr, c_char, c_void};
use std::mem::size_of;
use std::ops::Range;

use super::ffi::{ArrowArray, ArrowSchema};
use super::{BackendError, Batch, ColumnData, ColumnSpec, ScalarType};

#[derive(Clone, Copy)]
pub(super) enum ScalarFormat {
    Bool,
    Int64,
    Float64,
    Utf8,
    LargeUtf8,
}

impl ScalarFormat {
    fn slot_bytes(self) -> usize {
        match self {
            Self::Bool => size_of::<Option<bool>>(),
            Self::Int64 => size_of::<Option<i64>>(),
            Self::Float64 => size_of::<Option<f64>>(),
            Self::Utf8 | Self::LargeUtf8 => size_of::<Option<String>>(),
        }
    }
}

pub(super) fn read_schema(
    root: &ArrowSchema,
) -> Result<(Vec<ColumnSpec>, Vec<ScalarFormat>), BackendError> {
    if root.release.is_none()
        || name(root.format)? != "+s"
        || !root.dictionary.is_null()
        || root.n_children <= 0
    {
        return Err(BackendError::Schema);
    }
    let field_count = usize::try_from(root.n_children).map_err(|_| BackendError::Schema)?;
    let fields = pointer_slice(root.children, field_count).ok_or(BackendError::Schema)?;
    let mut schema = Vec::with_capacity(field_count);
    let mut formats = Vec::with_capacity(field_count);
    for &field in fields {
        let field = unsafe { field.as_ref() }.ok_or(BackendError::Schema)?;
        if field.release.is_none() || field.n_children != 0 || !field.dictionary.is_null() {
            return Err(BackendError::Schema);
        }
        let (data_type, format) = match name(field.format)? {
            "b" => (ScalarType::Boolean, ScalarFormat::Bool),
            "l" => (ScalarType::BigInt, ScalarFormat::Int64),
            "g" => (ScalarType::Double, ScalarFormat::Float64),
            "u" => (ScalarType::Varchar, ScalarFormat::Utf8),
            "U" => (ScalarType::Varchar, ScalarFormat::LargeUtf8),
            _ => return Err(BackendError::Schema),
        };
        schema.push(ColumnSpec {
            name: name(field.name)?.to_owned(),
            data_type,
        });
        formats.push(format);
    }
    Ok((schema, formats))
}

pub(super) fn read_batch(
    root: &ArrowArray,
    formats: &[ScalarFormat],
    max_bytes: Option<usize>,
) -> Result<Batch, BackendError> {
    let len = usize::try_from(root.length).map_err(|_| BackendError::Arrow)?;
    let offset = usize::try_from(root.offset).map_err(|_| BackendError::Arrow)?;
    if root.release.is_none()
        || root.null_count != 0
        || root.n_buffers != 1
        || !root.dictionary.is_null()
        || usize::try_from(root.n_children).ok() != Some(formats.len())
    {
        return Err(BackendError::Arrow);
    }
    let children = pointer_slice(root.children, formats.len()).ok_or(BackendError::Arrow)?;
    if let Some(mut budget) = max_bytes {
        // Account for backing storage requested by the Rust bridge. Ladybug's Arrow arrays
        // already exist at this point and remain under the producer's own resource policy.
        reserve_slots(&mut budget, formats.len(), size_of::<ColumnData>())?;
        for (&array, &format) in children.iter().zip(formats) {
            reserve_slots(&mut budget, len, format.slot_bytes())?;
            let array = unsafe { array.as_ref() }.ok_or(BackendError::Arrow)?;
            let reader = ArrayReader::new(array, offset, len, format)?;
            match format {
                ScalarFormat::Utf8 => reader.account_strings::<i32>(&mut budget)?,
                ScalarFormat::LargeUtf8 => reader.account_strings::<i64>(&mut budget)?,
                _ => {}
            }
        }
    }

    let mut columns = Vec::with_capacity(formats.len());
    for (&array, &format) in children.iter().zip(formats) {
        let array = unsafe { array.as_ref() }.ok_or(BackendError::Arrow)?;
        let reader = ArrayReader::new(array, offset, len, format)?;
        let column = match format {
            ScalarFormat::Bool => {
                ColumnData::Boolean(reader.read(|reader, index| bit(reader.buffers[1], index))?)
            }
            ScalarFormat::Int64 => {
                ColumnData::BigInt(reader.read(|reader, index| value(reader.buffers[1], index))?)
            }
            ScalarFormat::Float64 => {
                ColumnData::Double(reader.read(|reader, index| value(reader.buffers[1], index))?)
            }
            ScalarFormat::Utf8 => ColumnData::Varchar(reader.strings::<i32>()?),
            ScalarFormat::LargeUtf8 => ColumnData::Varchar(reader.strings::<i64>()?),
        };
        columns.push(column);
    }
    Ok(Batch { columns, len })
}

fn reserve_slots(
    budget: &mut usize,
    count: usize,
    bytes_per_slot: usize,
) -> Result<(), BackendError> {
    let bytes = count
        .checked_mul(bytes_per_slot)
        .ok_or(BackendError::BatchBudget)?;
    *budget = budget.checked_sub(bytes).ok_or(BackendError::BatchBudget)?;
    Ok(())
}

struct ArrayReader<'a> {
    buffers: &'a [*const c_void],
    start: usize,
    end: usize,
}

impl<'a> ArrayReader<'a> {
    fn new(
        array: &'a ArrowArray,
        parent_offset: usize,
        len: usize,
        format: ScalarFormat,
    ) -> Result<Self, BackendError> {
        let array_len = usize::try_from(array.length).map_err(|_| BackendError::Arrow)?;
        let array_offset = usize::try_from(array.offset).map_err(|_| BackendError::Arrow)?;
        let buffer_count = match format {
            ScalarFormat::Utf8 | ScalarFormat::LargeUtf8 => 3,
            _ => 2,
        };
        let start = array_offset
            .checked_add(parent_offset)
            .ok_or(BackendError::Arrow)?;
        let end = start.checked_add(len).ok_or(BackendError::Arrow)?;
        if array.release.is_none()
            || array.n_children != 0
            || !array.dictionary.is_null()
            || array.null_count < -1
            || array.null_count > array.length
            || parent_offset
                .checked_add(len)
                .is_none_or(|end| end > array_len)
            || array.n_buffers != buffer_count
        {
            return Err(BackendError::Arrow);
        }
        let buffers =
            pointer_slice(array.buffers, buffer_count as usize).ok_or(BackendError::Arrow)?;
        if array.null_count != 0 && buffers[0].is_null() {
            return Err(BackendError::Arrow);
        }
        Ok(Self {
            buffers,
            start,
            end,
        })
    }

    fn is_valid(&self, index: usize) -> Result<bool, BackendError> {
        if self.buffers[0].is_null() {
            return Ok(true);
        }
        bit(self.buffers[0], index)
    }

    fn read<T>(
        &self,
        value: impl Fn(&Self, usize) -> Result<T, BackendError>,
    ) -> Result<Vec<Option<T>>, BackendError> {
        let mut values = Vec::with_capacity(self.end - self.start);
        for index in self.start..self.end {
            let item = if self.is_valid(index)? {
                Some(value(self, index)?)
            } else {
                None
            };
            values.push(item);
        }
        Ok(values)
    }

    fn string_range<T: Copy + TryInto<usize>>(
        &self,
        index: usize,
    ) -> Result<Range<usize>, BackendError> {
        let first = value::<T>(self.buffers[1], index)?
            .try_into()
            .map_err(|_| BackendError::Arrow)?;
        let next = index.checked_add(1).ok_or(BackendError::Arrow)?;
        let last = value::<T>(self.buffers[1], next)?
            .try_into()
            .map_err(|_| BackendError::Arrow)?;
        if last < first || last > isize::MAX as usize {
            return Err(BackendError::Arrow);
        }
        Ok(first..last)
    }

    fn account_strings<T: Copy + TryInto<usize>>(
        &self,
        budget: &mut usize,
    ) -> Result<(), BackendError> {
        for index in self.start..self.end {
            let range = self.string_range::<T>(index)?;
            if self.is_valid(index)? {
                reserve_slots(budget, 1, range.len())?;
            }
        }
        Ok(())
    }

    fn strings<T: Copy + TryInto<usize>>(&self) -> Result<Vec<Option<String>>, BackendError> {
        let mut output = Vec::with_capacity(self.end - self.start);
        for index in self.start..self.end {
            let range = self.string_range::<T>(index)?;
            if !self.is_valid(index)? {
                output.push(None);
                continue;
            }
            if range.is_empty() {
                output.push(Some(String::new()));
                continue;
            }
            if self.buffers[2].is_null() {
                return Err(BackendError::Arrow);
            }
            let bytes = unsafe {
                std::slice::from_raw_parts(
                    self.buffers[2].cast::<u8>().add(range.start),
                    range.len(),
                )
            };
            let string = std::str::from_utf8(bytes).map_err(|_| BackendError::Arrow)?;
            output.push(Some(string.to_owned()));
        }
        Ok(output)
    }
}

fn value<T: Copy>(buffer: *const c_void, index: usize) -> Result<T, BackendError> {
    let offset = index
        .checked_mul(size_of::<T>())
        .ok_or(BackendError::Arrow)?;
    if buffer.is_null() || offset > (isize::MAX as usize).saturating_sub(size_of::<T>()) {
        return Err(BackendError::Arrow);
    }
    Ok(unsafe { buffer.cast::<u8>().add(offset).cast::<T>().read_unaligned() })
}

fn bit(buffer: *const c_void, index: usize) -> Result<bool, BackendError> {
    let byte = value::<u8>(buffer, index / 8)?;
    Ok((byte & (1 << (index % 8))) != 0)
}

fn name<'a>(raw: *const c_char) -> Result<&'a str, BackendError> {
    if raw.is_null() {
        return Err(BackendError::Schema);
    }
    unsafe { CStr::from_ptr(raw) }
        .to_str()
        .map_err(|_| BackendError::Schema)
}

// The producer owns the allocations. The C Data interface passes buffer pointers and logical
// dimensions, leaving allocation sizes as a property of the pinned Ladybug library.
fn pointer_slice<'a, T>(raw: *const *const T, len: usize) -> Option<&'a [*const T]> {
    if len == 0 {
        return Some(&[]);
    }
    if raw.is_null() || len > (isize::MAX as usize) / size_of::<*const T>() {
        return None;
    }
    Some(unsafe { std::slice::from_raw_parts(raw, len) })
}
