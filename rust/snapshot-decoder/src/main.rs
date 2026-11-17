//! Bounded offline decoder/measurement CLI; no game or network access.
#![forbid(unsafe_code)]

use ba_snapshot_decoder::{
    MAX_SNAPSHOT_BYTES, PROJECTION_VERSION, ProjectionMode, Snapshot, decode_snapshot,
    decode_snapshot_v2,
};
use serde_json::json;
use std::{env, error::Error, fs::File, hint::black_box, io::Read, path::PathBuf, time::Instant};

struct Options {
    command: String,
    path: PathBuf,
    viewer: u32,
    entities: bool,
    mode: Option<ProjectionMode>,
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
        mode: None,
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
            "--mode" => {
                result.mode = Some(
                    match args.next().and_then(|s| s.into_string().ok()).as_deref() {
                        Some("summary") => ProjectionMode::Summary,
                        Some("full") => ProjectionMode::Full,
                        Some("ownership") => ProjectionMode::Ownership,
                        _ => return Err("mode must be summary, full or ownership".into()),
                    },
                );
            }
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
    if result.mode.is_some() && result.entities {
        return Err("--mode and --entities cannot be combined".into());
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

fn decode(data: &[u8], args: &Options) -> Result<Snapshot, ba_snapshot_decoder::DecodeError> {
    match args.mode {
        Some(mode) => decode_snapshot_v2(data, args.viewer, mode),
        None => decode_snapshot(data, args.viewer, args.entities),
    }
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
    let state = decode(&data, &args)?;
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
        black_box(decode(black_box(&data), &args)?);
    }
    let mut decode_ms = Vec::new();
    let mut decode_serialize_ms = Vec::new();
    for _ in 0..args.samples {
        let began = Instant::now();
        for _ in 0..args.iterations {
            black_box(decode(black_box(&data), &args)?);
        }
        decode_ms.push(began.elapsed().as_secs_f64() * 1000.0 / args.iterations as f64);
        let began = Instant::now();
        for _ in 0..args.iterations {
            let decoded = decode(black_box(&data), &args)?;
            black_box(serde_json::to_vec(&decoded)?);
        }
        decode_serialize_ms.push(began.elapsed().as_secs_f64() * 1000.0 / args.iterations as f64);
    }
    let mut report = json!({
        "schema": 1, "os": env::consts::OS, "arch": env::consts::ARCH,
        "release_build": !cfg!(debug_assertions), "viewer": args.viewer,
        "include_entities": args.entities, "iterations": args.iterations, "samples": args.samples,
        "raw_sha256": state.raw_sha256, "canonical_fnv1a64": state.canonical_fnv1a64,
        "decoded_json_bytes": encoded.len(), "decode_ms": decode_ms,
        "decode_serialize_ms": decode_serialize_ms,
        "scope": "in-process warmed decode/destruction and decode+JSON; file IO, process startup and final JSON excluded; not simulation/server latency"
    });
    if let Some(mode) = args.mode {
        let name = match mode {
            ProjectionMode::Summary => "summary",
            ProjectionMode::Full => "full",
            ProjectionMode::Ownership => "ownership",
        };
        report["mode"] = json!(name);
        report["projection_version"] = json!(PROJECTION_VERSION);
        report.as_object_mut().unwrap().remove("include_entities");
    }
    println!("{report}");
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("snapshot decoder: {error}");
        std::process::exit(2);
    }
}
