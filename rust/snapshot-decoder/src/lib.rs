//! Decoder for the selected observable state in server/native_simulation.py.
//! This module does not load game binaries or advance a simulation.
#![deny(unsafe_code)]

// Pointer ownership is confined to the opt-in C ABI; the decoder stays safe Rust.
#[allow(unsafe_code)]
pub mod ffi;

use serde::{Serialize, Serializer};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, error::Error, fmt};

pub const MAX_SNAPSHOT_BYTES: usize = 16 * 1024 * 1024;
pub const PROJECTION_VERSION: u32 = 1;
const MAX_VECTOR_ITEMS: usize = 1_000_000;
const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;
const RESOURCE_NAMES: [&str; 8] = [
    "primary",
    "secondary",
    "current_supply",
    "max_supply",
    "primary_gathered",
    "secondary_gathered",
    "primary_lost",
    "secondary_lost",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DecodeError(pub &'static str);
impl fmt::Display for DecodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}
impl Error for DecodeError {}
type Result<T> = std::result::Result<T, DecodeError>;

struct Buffer<'a>(&'a [u8]);
impl Buffer<'_> {
    fn bytes(&self, offset: usize, size: usize) -> Result<&[u8]> {
        let end = offset
            .checked_add(size)
            .ok_or(DecodeError("snapshot bounds"))?;
        self.0
            .get(offset..end)
            .ok_or(DecodeError("snapshot bounds"))
    }
    fn u16(&self, offset: usize) -> Result<u16> {
        Ok(u16::from_le_bytes(
            self.bytes(offset, 2)?.try_into().unwrap(),
        ))
    }
    fn u32(&self, offset: usize) -> Result<u32> {
        Ok(u32::from_le_bytes(
            self.bytes(offset, 4)?.try_into().unwrap(),
        ))
    }
    fn field(&self, table: usize, index: usize) -> Result<usize> {
        if table == 0 {
            return Ok(0);
        }
        // FlatBuffers uses a signed displacement; a shared vtable can follow a table.
        let displacement = self.u32(table)? as i32 as i64;
        let vtable = i64::try_from(table)
            .map_err(|_| DecodeError("snapshot bounds"))?
            .checked_sub(displacement)
            .ok_or(DecodeError("snapshot bounds"))?;
        let vtable = usize::try_from(vtable).map_err(|_| DecodeError("snapshot bounds"))?;
        let slot = 4 + 2 * index;
        if slot + 2 > usize::from(self.u16(vtable)?) {
            return Ok(0);
        }
        let relative = usize::from(
            self.u16(
                vtable
                    .checked_add(slot)
                    .ok_or(DecodeError("snapshot bounds"))?,
            )?,
        );
        if relative == 0 {
            return Ok(0);
        }
        let position = table
            .checked_add(relative)
            .ok_or(DecodeError("snapshot bounds"))?;
        self.bytes(position, 1)?;
        Ok(position)
    }
    fn indirect(&self, offset: usize) -> Result<usize> {
        if offset == 0 {
            return Ok(0);
        }
        let target = offset
            .checked_add(self.u32(offset)? as usize)
            .ok_or(DecodeError("snapshot bounds"))?;
        self.bytes(target, 4)?;
        Ok(target)
    }
    fn table(&self, table: usize, index: usize) -> Result<usize> {
        self.indirect(self.field(table, index)?)
    }
    fn vector(&self, table: usize, index: usize, stride: usize) -> Result<(&[u8], usize)> {
        let offset = self.table(table, index)?;
        if offset == 0 {
            return Ok((&[], 0));
        }
        let count = self.u32(offset)? as usize;
        if count > MAX_VECTOR_ITEMS {
            return Err(DecodeError("snapshot vector count exceeds bound"));
        }
        let size = count
            .checked_mul(stride)
            .ok_or(DecodeError("snapshot bounds"))?;
        Ok((
            self.bytes(
                offset
                    .checked_add(4)
                    .ok_or(DecodeError("snapshot bounds"))?,
                size,
            )?,
            count,
        ))
    }
    fn scalar_u32(&self, table: usize, index: usize) -> Result<u32> {
        let p = self.field(table, index)?;
        if p == 0 { Ok(0) } else { self.u32(p) }
    }
    fn scalar_u64(&self, table: usize, index: usize) -> Result<u64> {
        let p = self.field(table, index)?;
        if p == 0 {
            Ok(0)
        } else {
            Ok(u64::from_le_bytes(self.bytes(p, 8)?.try_into().unwrap()))
        }
    }
    fn scalar_bool(&self, table: usize, index: usize) -> Result<bool> {
        let p = self.field(table, index)?;
        if p == 0 {
            Ok(false)
        } else {
            Ok(self.bytes(p, 1)?[0] != 0)
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
pub struct GameState {
    pub complete: bool,
    pub game_over_frame: i32,
    pub winning_alliance: u32,
    pub army_conceded_flag: u32,
    pub game_over_checksum: u64,
}

fn finite_position<S: Serializer>(
    position: &Option<[f64; 3]>,
    serializer: S,
) -> std::result::Result<S::Ok, S::Error> {
    if position.is_some_and(|values| values.iter().any(|v| !v.is_finite())) {
        return Err(serde::ser::Error::custom(
            "nonfinite position cannot be serialized as JSON",
        ));
    }
    position.serialize(serializer)
}

#[derive(Debug, Serialize, PartialEq, Default)]
pub struct Entity {
    pub id: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub army: Option<u32>,
    #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
    pub kind: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_health: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub current_damage: Option<u32>,
    #[serde(
        skip_serializing_if = "Option::is_none",
        serialize_with = "finite_position"
    )]
    pub position: Option<[f64; 3]>,
}

/// Explicit projection selection. Every projection validates all selected
/// components, including finite positions, before returning any state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u32)]
pub enum ProjectionMode {
    Summary = 0,
    Full = 1,
    Ownership = 2,
}

impl TryFrom<u32> for ProjectionMode {
    type Error = DecodeError;

    fn try_from(value: u32) -> Result<Self> {
        match value {
            0 => Ok(Self::Summary),
            1 => Ok(Self::Full),
            2 => Ok(Self::Ownership),
            _ => Err(DecodeError("unsupported snapshot projection mode")),
        }
    }
}

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct Ownership {
    pub id: u32,
    pub army: u32,
    #[serde(rename = "type")]
    pub kind: u32,
}

#[derive(Debug, Serialize, PartialEq)]
pub struct Snapshot {
    pub frame: u32,
    pub viewer: u32,
    pub local_alliance: u32,
    pub canonical_fnv1a64: String,
    pub raw_sha256: String,
    pub byte_count: usize,
    pub counts: BTreeMap<&'static str, usize>,
    pub resources: BTreeMap<u32, BTreeMap<&'static str, i32>>,
    pub game_state: GameState,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub entities: Option<Vec<Entity>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ownership: Option<Vec<Ownership>>,
}

fn hash_word(hash: &mut u64, word: u32) {
    for byte in word.to_le_bytes() {
        *hash = (*hash ^ u64::from(byte)).wrapping_mul(FNV_PRIME);
    }
}
fn word(bytes: &[u8], offset: usize) -> u32 {
    // Internal calls use already validated vectors and fixed row widths.
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}

/// Decode the existing Python observable-state contract, including its zero-root
/// and u32-viewer behavior. Native snapshot acquisition enforces viewer0..31.
/// Unlike the standalone Python helper, this boundary also caps input at16MiB.
/// Position bits enter the checksum before f32-to-f64 conversion. Nonfinite
/// positions remain representable here; JSON serialization explicitly rejects them.
pub fn decode_snapshot(data: &[u8], viewer: u32, include_entities: bool) -> Result<Snapshot> {
    decode_internal(
        data,
        viewer,
        if include_entities {
            ProjectionMode::Full
        } else {
            ProjectionMode::Summary
        },
        false,
    )
}

/// Decode a version1 projection with strict validation in every mode. Ownership
/// includes only IDs present in both army and type components, ordered by ID.
/// Checksums still scan every original selected component and the complete input.
pub fn decode_snapshot_v2(data: &[u8], viewer: u32, mode: ProjectionMode) -> Result<Snapshot> {
    decode_internal(data, viewer, mode, true)
}

fn decode_internal(
    data: &[u8],
    viewer: u32,
    mode: ProjectionMode,
    strict: bool,
) -> Result<Snapshot> {
    if data.len() > MAX_SNAPSHOT_BYTES {
        return Err(DecodeError("snapshot exceeds16MiB"));
    }
    let b = Buffer(data);
    let root = b.u32(0)? as usize;
    b.bytes(root, 4)?;
    let frame = b.scalar_u32(root, 0)?;
    let mut canonical = FNV_OFFSET;
    for value in [1, viewer, frame] {
        hash_word(&mut canonical, value);
    }
    let mut counts = BTreeMap::new();
    let mut resources = BTreeMap::new();
    let mut entities: BTreeMap<u32, Entity> = BTreeMap::new();
    let mut ownership: BTreeMap<u32, (Option<u32>, Option<u32>)> = BTreeMap::new();
    for (field, words, name, health) in [
        (2, 1, "army", false),
        (3, 1, "type", false),
        (5, 1, "health", true),
        (7, 3, "position", false),
        (21, 8, "resources", false),
    ] {
        let table = b.table(root, field)?;
        let (ids, count) = b.vector(table, 0, 4)?;
        let (values, value_count) = b.vector(table, 1, 4 * words)?;
        let (damage, damage_count) = if health {
            b.vector(table, 2, 4)?
        } else {
            (&[][..], 0)
        };
        if value_count != count || health && damage_count != count {
            return Err(DecodeError("component vector lengths disagree"));
        }
        // Sort indices instead of constructing a second copy of every word.
        let mut order: Vec<(u32, usize)> = (0..count).map(|i| (word(ids, i * 4), i)).collect();
        order.sort_unstable_by_key(|&(id, _)| id);
        if order.windows(2).any(|pair| pair[0].0 == pair[1].0) {
            return Err(DecodeError("duplicate component ID"));
        }
        hash_word(&mut canonical, field as u32);
        hash_word(&mut canonical, count as u32);
        counts.insert(name, count);
        for (id, i) in order {
            hash_word(&mut canonical, id);
            let mut row = [0u32; 8];
            for (j, value) in row[..words].iter_mut().enumerate() {
                *value = word(values, (i * words + j) * 4);
                hash_word(&mut canonical, *value);
            }
            let current_damage = if health { word(damage, i * 4) } else { 0 };
            if health {
                hash_word(&mut canonical, current_damage);
            }
            if strict
                && name == "position"
                && row[..3]
                    .iter()
                    .any(|value| !f32::from_bits(*value).is_finite())
            {
                return Err(DecodeError("nonfinite snapshot position"));
            }
            if name == "resources" {
                resources.insert(
                    id,
                    RESOURCE_NAMES
                        .into_iter()
                        .zip(row.map(|v| v as i32))
                        .collect(),
                );
            } else if mode == ProjectionMode::Ownership && matches!(name, "army" | "type") {
                let record = ownership.entry(id).or_default();
                if name == "army" {
                    record.0 = Some(row[0]);
                } else {
                    record.1 = Some(row[0]);
                }
            } else if mode == ProjectionMode::Full {
                let entity = entities.entry(id).or_insert_with(|| Entity {
                    id,
                    ..Entity::default()
                });
                match name {
                    "army" => entity.army = Some(row[0]),
                    "type" => entity.kind = Some(row[0]),
                    "health" => {
                        entity.max_health = Some(row[0]);
                        entity.current_damage = Some(current_damage);
                    }
                    "position" => {
                        entity.position = Some([
                            f32::from_bits(row[0]) as f64,
                            f32::from_bits(row[1]) as f64,
                            f32::from_bits(row[2]) as f64,
                        ])
                    }
                    _ => unreachable!("fixed component list"),
                }
            }
        }
    }
    let state = b.table(root, 23)?;
    Ok(Snapshot {
        frame,
        viewer,
        local_alliance: b.scalar_u32(root, 1)?,
        canonical_fnv1a64: format!("{canonical:016x}"),
        raw_sha256: format!("{:x}", Sha256::digest(data)),
        byte_count: data.len(),
        counts,
        resources,
        game_state: GameState {
            complete: b.scalar_bool(state, 0)?,
            game_over_frame: b.scalar_u32(state, 1)? as i32,
            winning_alliance: b.scalar_u32(state, 2)?,
            army_conceded_flag: b.scalar_u32(state, 3)?,
            game_over_checksum: b.scalar_u64(state, 4)?,
        },
        ownership: (mode == ProjectionMode::Ownership).then(|| {
            ownership
                .into_iter()
                .filter_map(|(id, (army, kind))| {
                    Some(Ownership {
                        id,
                        army: army?,
                        kind: kind?,
                    })
                })
                .collect()
        }),
        entities: (mode == ProjectionMode::Full).then(|| entities.into_values().collect()),
    })
}

#[cfg(test)]
pub(crate) mod test_support {
    /// Small independent authored FlatBuffer layout; no game binaries or captures.
    pub struct Builder(pub Vec<u8>);

    impl Builder {
        pub fn new() -> Self {
            let mut result = Self(vec![0; 156]);
            result.u32(0, 56);
            result.u16(4, 52);
            result.u16(6, 100);
            result.u32(56, 52);
            result
        }

        pub fn u32(&mut self, at: usize, value: u32) {
            self.0[at..at + 4].copy_from_slice(&value.to_le_bytes());
        }

        fn u16(&mut self, at: usize, value: u16) {
            self.0[at..at + 2].copy_from_slice(&value.to_le_bytes());
        }

        fn allocate(&mut self, size: usize) -> usize {
            self.0.resize(self.0.len().next_multiple_of(4), 0);
            let at = self.0.len();
            self.0.resize(at + size, 0);
            at
        }

        fn vector(&mut self, words: &[u32], width: usize) -> usize {
            let at = self.allocate(4 + words.len() * 4);
            self.u32(at, (words.len() / width) as u32);
            for (index, word) in words.iter().enumerate() {
                self.u32(at + 4 + index * 4, *word);
            }
            at
        }

        /// Returns the ID vector offset so tests can forge its count or rows.
        pub fn component(
            &mut self,
            field: usize,
            ids: &[u32],
            values: &[u32],
            damage: &[u32],
        ) -> usize {
            let health = field == 5;
            let width = match field {
                7 => 3,
                21 => 8,
                _ => 1,
            };
            let vtable = self.allocate(if health { 10 } else { 8 });
            let table = self.allocate(if health { 16 } else { 12 });
            self.u16(vtable, if health { 10 } else { 8 });
            self.u16(vtable + 2, if health { 16 } else { 12 });
            self.u16(vtable + 4, 4);
            self.u16(vtable + 6, 8);
            self.u32(table, (table - vtable) as u32);
            if health {
                self.u16(vtable + 8, 12);
            }
            let root_field = 56 + 4 * (field + 1);
            self.u16(8 + 2 * field, (4 * (field + 1)) as u16);
            self.u32(root_field, (table - root_field) as u32);
            let id_vector = self.vector(ids, 1);
            let value_vector = self.vector(values, width);
            self.u32(table + 4, (id_vector - table - 4) as u32);
            self.u32(table + 8, (value_vector - table - 8) as u32);
            if health {
                let damage_vector = self.vector(damage, 1);
                self.u32(table + 12, (damage_vector - table - 12) as u32);
            }
            id_vector
        }
    }
}

#[cfg(test)]
mod tests {
    use super::test_support::Builder;
    use super::*;

    const MODES: [ProjectionMode; 3] = [
        ProjectionMode::Summary,
        ProjectionMode::Full,
        ProjectionMode::Ownership,
    ];

    #[test]
    fn ownership_is_sorted_complete_intersection_and_summaries_are_identical() {
        let mut fixture = Builder::new();
        fixture.component(2, &[9, 3, 7], &[2, 1, 8], &[]);
        fixture.component(3, &[7, 4, 3], &[70, 40, 30], &[]);
        fixture.component(5, &[1, 3], &[100, 200], &[0, 50]);
        fixture.component(7, &[2, 3], &[0; 6], &[]);
        fixture.component(21, &[0], &[0; 8], &[]);
        let full = decode_snapshot_v2(&fixture.0, 31, ProjectionMode::Full).unwrap();
        let full_json = serde_json::to_value(&full).unwrap();
        let compact = decode_snapshot_v2(&fixture.0, 31, ProjectionMode::Ownership).unwrap();
        assert_eq!(
            compact.ownership,
            Some(vec![
                Ownership {
                    id: 3,
                    army: 1,
                    kind: 30
                },
                Ownership {
                    id: 7,
                    army: 8,
                    kind: 70
                },
            ])
        );
        assert!(compact.entities.is_none());
        assert_eq!(
            full.entities
                .as_ref()
                .unwrap()
                .iter()
                .map(|entity| entity.id)
                .collect::<Vec<_>>(),
            [1, 2, 3, 4, 7, 9]
        );
        let mut summary_json = full_json.clone();
        summary_json.as_object_mut().unwrap().remove("entities");
        assert_eq!(summary_json.as_object().unwrap().len(), 9);
        for mode in MODES {
            let mut actual =
                serde_json::to_value(decode_snapshot_v2(&fixture.0, 31, mode).unwrap()).unwrap();
            actual.as_object_mut().unwrap().remove("entities");
            actual.as_object_mut().unwrap().remove("ownership");
            assert_eq!(actual, summary_json);
        }
        for include_entities in [false, true] {
            let mode = if include_entities {
                ProjectionMode::Full
            } else {
                ProjectionMode::Summary
            };
            assert_eq!(
                serde_json::to_vec(&decode_snapshot(&fixture.0, 31, include_entities).unwrap())
                    .unwrap(),
                serde_json::to_vec(&decode_snapshot_v2(&fixture.0, 31, mode).unwrap()).unwrap()
            );
        }
    }

    #[test]
    fn empty_and_absent_ownership_components_do_not_invent_records() {
        for field in [2, 3, 5, 7] {
            let mut fixture = Builder::new();
            fixture.component(field, &[1], &vec![0; if field == 7 { 3 } else { 1 }], &[0]);
            let result =
                decode_snapshot_v2(&fixture.0, u32::MAX, ProjectionMode::Ownership).unwrap();
            assert_eq!(result.ownership, Some(vec![]));
        }
        assert_eq!(
            decode_snapshot_v2(&[0; 4], 31, ProjectionMode::Ownership)
                .unwrap()
                .ownership,
            Some(vec![])
        );
        for value in [3, 255, u32::MAX] {
            assert!(ProjectionMode::try_from(value).is_err());
        }
    }

    #[test]
    fn every_explicit_mode_validates_omitted_components_and_positions() {
        for field in [2, 3, 5, 7, 21] {
            let width = match field {
                7 => 3,
                21 => 8,
                _ => 1,
            };
            let mut duplicate = Builder::new();
            duplicate.component(field, &[1, 1], &vec![0; width * 2], &[0, 0]);
            let mut mismatch = Builder::new();
            mismatch.component(field, &[1, 2], &vec![0; width], &[0, 0]);
            let mut damage_mismatch = Builder::new();
            damage_mismatch.component(5, &[1, 2], &[100, 100], &[0]);
            let mut huge = Builder::new();
            let at = huge.component(field, &[1], &vec![0; width], &[0]);
            huge.u32(at, 1_000_001);
            for mode in MODES {
                for bytes in [&duplicate.0, &mismatch.0, &damage_mismatch.0, &huge.0] {
                    assert!(decode_snapshot_v2(bytes, 31, mode).is_err());
                }
            }
        }
        for value in [
            0x7fc00001, 0xffc12345, 0x7f800001, 0xff800001, 0x7f800000, 0xff800000,
        ] {
            for axis in 0..3 {
                let mut fixture = Builder::new();
                let mut position = [0; 3];
                position[axis] = value;
                fixture.component(7, &[1], &position, &[]);
                for mode in MODES {
                    assert!(decode_snapshot_v2(&fixture.0, 31, mode).is_err());
                }
                assert!(decode_snapshot(&fixture.0, 31, false).is_ok());
                assert!(
                    serde_json::to_vec(&decode_snapshot(&fixture.0, 31, true).unwrap()).is_err()
                );
            }
        }
    }

    #[test]
    fn ownership_keeps_uint32_extremes_and_hashes_hidden_components() {
        let mut fixture = Builder::new();
        fixture.component(2, &[u32::MAX, 0], &[u32::MAX, 0], &[]);
        fixture.component(3, &[0, u32::MAX], &[u32::MAX, 0], &[]);
        let positions = [(-0.0f32).to_bits(), f32::MAX.to_bits(), 1];
        let at = fixture.component(7, &[17], &positions, &[]);
        let base = decode_snapshot_v2(&fixture.0, u32::MAX, ProjectionMode::Ownership).unwrap();
        assert_eq!(
            base.ownership,
            Some(vec![
                Ownership {
                    id: 0,
                    army: 0,
                    kind: u32::MAX
                },
                Ownership {
                    id: u32::MAX,
                    army: u32::MAX,
                    kind: 0
                },
            ])
        );
        for mode in MODES {
            assert!(decode_snapshot_v2(&fixture.0, u32::MAX, mode).is_ok());
        }
        // Change only a position ID: ownership is identical but both checksums
        // still bind the omitted component. Row order is separately canonical.
        fixture.u32(at + 4, 18);
        let changed = decode_snapshot_v2(&fixture.0, u32::MAX, ProjectionMode::Ownership).unwrap();
        assert_eq!(changed.ownership, base.ownership);
        assert_ne!(changed.canonical_fnv1a64, base.canonical_fnv1a64);
        assert_ne!(changed.raw_sha256, base.raw_sha256);
        let mut reordered = Builder::new();
        reordered.component(2, &[0, u32::MAX], &[0, u32::MAX], &[]);
        reordered.component(3, &[u32::MAX, 0], &[0, u32::MAX], &[]);
        reordered.component(7, &[17], &positions, &[]);
        let reordered =
            decode_snapshot_v2(&reordered.0, u32::MAX, ProjectionMode::Ownership).unwrap();
        assert_eq!(reordered.canonical_fnv1a64, base.canonical_fnv1a64);
        assert_ne!(reordered.raw_sha256, base.raw_sha256);
    }

    #[test]
    fn empty_root_matches_reference_and_entities_are_optional() {
        let result = decode_snapshot(&[0; 4], 31, false).unwrap();
        assert_eq!(result.frame, 0);
        assert_eq!(result.game_state.game_over_frame, 0);
        assert_eq!(result.counts.len(), 5);
        assert!(
            !serde_json::to_value(&result)
                .unwrap()
                .as_object()
                .unwrap()
                .contains_key("entities")
        );
        assert_eq!(
            decode_snapshot(&[0; 4], u32::MAX, true)
                .unwrap()
                .entities
                .unwrap(),
            []
        );
    }

    #[test]
    fn arbitrary_bounded_bytes_do_not_panic() {
        let mut seed = 0x82ef_195du32;
        for length in 0..2048 {
            let bytes: Vec<_> = (0..length)
                .map(|_| {
                    seed ^= seed << 13;
                    seed ^= seed >> 17;
                    seed ^= seed << 5;
                    seed as u8
                })
                .collect();
            let _ = decode_snapshot(&bytes, 31, true);
            for mode in MODES {
                let _ = decode_snapshot_v2(&bytes, 31, mode);
            }
        }
        assert!(decode_snapshot(&vec![0; MAX_SNAPSHOT_BYTES + 1], 31, true).is_err());
        assert!(decode_snapshot(&[0; 4], 31, true).is_ok());
        for mode in MODES {
            assert!(decode_snapshot_v2(&vec![0; MAX_SNAPSHOT_BYTES + 1], 31, mode).is_err());
        }
    }

    #[test]
    fn nonfinite_json_is_refused_and_negative_zero_preserved() {
        let mut entity = Entity {
            id: 1,
            position: Some([-0.0, f64::from(f32::MIN_POSITIVE), f64::from(f32::MAX)]),
            ..Entity::default()
        };
        assert!(serde_json::to_string(&entity).unwrap().contains("-0.0"));
        for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
            entity.position = Some([0.0, value, 0.0]);
            assert!(serde_json::to_string(&entity).is_err());
        }
    }
}
