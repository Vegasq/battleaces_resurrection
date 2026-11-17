//! Bounded offline decoder/measurement CLI; no game or network access.
#![forbid(unsafe_code)]

use ba_snapshot_decoder::{MAX_SNAPSHOT_BYTES, decode_snapshot};
use serde_json::json;
use std::{env, error::Error, fs::File, hint::black_box, io::Read, path::PathBuf, time::Instant};

struct Options {
    command: String,
    path: PathBuf,
    viewer: u32,
    entities: bool,
    iterations: usize,
    samples: usize,
}

fn arguments() -> Result<Options, Box<dyn Error>> {
    let mut args = env::args_os().skip(1);
    let command = args
        .next()
        .and_then(|s| s.into_string().ok())
        .ok_or("expected decode or bench")?;
    if command != "decode" && command != "bench" {
        return Err("expected decode or bench".into());
    }
    let path = PathBuf::from(args.next().ok_or("snapshot file required")?);
    let mut result = Options {
        command,
        path,
        viewer: 31,
        entities: false,
        iterations: 100,
        samples: 7,
    };
    let mut seen = std::collections::BTreeSet::new();
    while let Some(option) = args.next() {
        let option = option.into_string().map_err(|_| "invalid option")?;
        if !seen.insert(option.clone()) {
            return Err("duplicate option".into());
        }
        match option.as_str() {
            "--entities" => result.entities = true,
            "--viewer" => {
                result.viewer = args
                    .next()
                    .and_then(|s| s.into_string().ok())
                    .ok_or("viewer required")?
                    .parse()?
            }
            "--iterations" if result.command == "bench" => {
                result.iterations = args
                    .next()
                    .and_then(|s| s.into_string().ok())
                    .ok_or("iterations required")?
                    .parse()?
            }
            "--samples" if result.command == "bench" => {
                result.samples = args
                    .next()
                    .and_then(|s| s.into_string().ok())
                    .ok_or("samples required")?
                    .parse()?
            }
            _ => return Err("unknown option".into()),
        }
    }
    if !(1..=100_000).contains(&result.iterations)
        || !(1..=100).contains(&result.samples)
        || result
            .iterations
            .checked_mul(result.samples)
            .is_none_or(|n| n > 1_000_000)
    {
        return Err("benchmark iteration/sample budget exceeded".into());
    }
    Ok(result)
}

fn run() -> Result<(), Box<dyn Error>> {
    let args = arguments()?;
    // Avoid opening devices/FIFOs before the type check. This offline tool
    // consumes owned fixtures; it is not a race-safe untrusted-file service.
    let metadata = std::fs::metadata(&args.path)?;
    if !metadata.is_file() || metadata.len() > MAX_SNAPSHOT_BYTES as u64 {
        return Err("snapshot must be a regular file up to16MiB".into());
    }
    let file = File::open(&args.path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > MAX_SNAPSHOT_BYTES as u64 {
        return Err("snapshot must be a regular file up to16MiB".into());
    }
    let mut data = Vec::new();
    file.take((MAX_SNAPSHOT_BYTES + 1) as u64)
        .read_to_end(&mut data)?;
    let state = decode_snapshot(&data, args.viewer, args.entities)?;
    // Serialize once before measurement; nonfinite values fail rather than becoming null.
    let encoded = serde_json::to_vec(&state)?;
    if args.command == "decode" {
        println!("{}", String::from_utf8(encoded)?);
        return Ok(());
    }
    if cfg!(debug_assertions) {
        return Err("benchmark requires a release build".into());
    }
    for _ in 0..10 {
        black_box(decode_snapshot(
            black_box(&data),
            args.viewer,
            args.entities,
        )?);
    }
    let mut decode_ms = Vec::new();
    let mut decode_serialize_ms = Vec::new();
    for _ in 0..args.samples {
        let began = Instant::now();
        for _ in 0..args.iterations {
            black_box(decode_snapshot(
                black_box(&data),
                args.viewer,
                args.entities,
            )?);
        }
        decode_ms.push(began.elapsed().as_secs_f64() * 1000.0 / args.iterations as f64);
        let began = Instant::now();
        for _ in 0..args.iterations {
            let decoded = decode_snapshot(black_box(&data), args.viewer, args.entities)?;
            black_box(serde_json::to_vec(&decoded)?);
        }
        decode_serialize_ms.push(began.elapsed().as_secs_f64() * 1000.0 / args.iterations as f64);
    }
    println!(
        "{}",
        json!({
            "schema": 1, "os": env::consts::OS, "arch": env::consts::ARCH,
            "release_build": !cfg!(debug_assertions), "viewer": args.viewer,
            "include_entities": args.entities, "iterations": args.iterations, "samples": args.samples,
            "raw_sha256": state.raw_sha256, "canonical_fnv1a64": state.canonical_fnv1a64,
            "decoded_json_bytes": encoded.len(), "decode_ms": decode_ms,
            "decode_serialize_ms": decode_serialize_ms,
            "scope": "in-process warmed decode/destruction and decode+JSON; file IO, process startup and final JSON excluded; not simulation/server latency"
        })
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("snapshot decoder: {error}");
        std::process::exit(2);
    }
}
