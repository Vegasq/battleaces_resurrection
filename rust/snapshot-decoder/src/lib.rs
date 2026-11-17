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
            if name == "resources" {
                resources.insert(
                    id,
                    RESOURCE_NAMES
                        .into_iter()
                        .zip(row.map(|v| v as i32))
                        .collect(),
                );
            } else if include_entities {
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
        entities: include_entities.then(|| entities.into_values().collect()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

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
        }
        assert!(decode_snapshot(&vec![0; MAX_SNAPSHOT_BYTES + 1], 31, true).is_err());
        assert!(decode_snapshot(&[0; 4], 31, true).is_ok());
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
