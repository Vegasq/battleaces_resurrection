"""Compare a dedicated server's snapshots/frames with both actual client audits.

python server/verify_dedicated_run.py server/test-data/dedicated01 [-o report.json]
Defaults to investigation/runtime/<run-name>-processes.json for client PIDs.
Exit0: sampled observable state and logged transport hashes match;1: invalid data;
2: divergence;3: insufficient evidence. This is not a complete hidden-state proof.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import pathlib
import re
import struct
import sys

try:
    from .native_simulation import canonical_snapshot, RESOURCE_NAMES
    from .game_data import decode_frame, decode_identity
    from . import protobuf_wire as wire
except ImportError:
    from native_simulation import canonical_snapshot, RESOURCE_NAMES
    from game_data import decode_frame, decode_identity
    import protobuf_wire as wire

ROOT = pathlib.Path(__file__).resolve().parent.parent
COUNT_MAP = {"army": "army_entities", "type": "type_entities", "health": "health_entities",
             "position": "position_entities", "resources": "resource_armies"}
RECEIVED = re.compile(r"LAN received frame (\d+), actions=(\d+), sim=(-?\d+) sha256=([0-9a-f]{64})")
BUILD_SMOKE = re.compile(r"LAN NORMAL BUILD smoke frame(\d+) slot(\d+) army(\d+) HQ(\d+) deckSlot(\d+) unitType(\d+) ability(\d+)")
SESSION_JOIN = re.compile(r"Dedicated session \d+ joined match=([0-9a-f]{32}) assignedSeat=([01])")


def read_events(path):
    events, warnings = [], []
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip(): continue
        try: events.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines)-1 and not text.endswith("\n"):
                warnings.append("Ignored incomplete final event while server log was being written")
            else: raise ValueError(f"malformed events JSON at line{i+1}")
    return events, warnings


def read_tsv(path, keys):
    rows, conflicts = {}, []
    if not path.exists(): return rows, conflicts
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        for line, row in enumerate(reader, 2):
            if row.get("frame") == "frame": continue
            key = tuple(int(row[k]) for k in keys)
            if key in rows and row != rows[key]: conflicts.append({"key": key, "line": line})
            else: rows[key] = row
    return rows, conflicts


def client_log_segment(path, pid):
    if not path.exists(): return [], "client native log missing"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    starts = [i for i, line in enumerate(lines) if "Offline initial state reached" in line and f"PID={pid}" in line]
    if not starts: return [], "client native log has no startup marker for requested PID"
    start = starts[-1]
    end = next((i for i in range(start+1, len(lines)) if "Offline initial state reached" in lines[i]), len(lines))
    return lines[start:end], None


def digest_game_data(path):
    data = path.read_bytes()
    if data.startswith(b"\x1f\x8b"): data = gzip.decompress(data)
    return hashlib.sha256(data).hexdigest()


def scope_match_log(lines, match_id, fallback_slot):
    """Bind a process log to one native session, including its welcome/selection."""
    joins = [(index, SESSION_JOIN.search(line)) for index, line in enumerate(lines) if SESSION_JOIN.search(line)]
    if joins:
        selected = [(index, match) for index, match in joins if match[1] == match_id]
        if len(selected) != 1:
            return [], fallback_slot, "missing or duplicate native match session marker"
        index, match = selected[0]
        starts = [i for i in range(index) if "Dedicated lobby welcome slot " in lines[i]]
        start = starts[-1] if starts else index
        end = next((i for i in range(index + 1, len(lines)) if "Dedicated session reset:" in lines[i] or SESSION_JOIN.search(lines[i])), len(lines))
        return lines[start:end], int(match[2]), None
    welcomes = [re.search(r"Dedicated lobby welcome slot ([01]);", line) for line in lines]
    welcomes = [match for match in welcomes if match]
    if len(welcomes) > 1:
        return [], fallback_slot, "multiple welcomes without per-match session markers"
    return lines, int(welcomes[0][1]) if welcomes else fallback_slot, None


def production_evidence(match_dir, snapshots):
    """Decode authoritative build commands and isolate their observed costs/spawns.

    Gathered-minus-available deltas account for income between snapshots. A window
    containing other player actions is reported as inconclusive rather than
    attributing all resource changes to one command.
    """
    if not match_dir or not (match_dir / "frames.bin").exists():
        return [], []
    raw = (match_dir / "bootstrap.pb.gz").read_bytes()
    if raw.startswith(b"\x1f\x8b"): raw = gzip.decompress(raw)
    config = wire.get_bytes(raw, 1, required=True)
    armies = {wire.get_uint(a, 1): a for a in wire.get_repeated_bytes(config, 2)}
    owners = {decode_identity(identity)["player_id"]: army for army, a in armies.items()
              for identity in wire.get_repeated_bytes(a, 2)}
    decks = {army: wire.get_repeated_uint(wire.get_bytes(a, 3), 1) for army, a in armies.items()}
    entities = {wire.get_uint(e, 1): e for e in wire.get_repeated_bytes(config, 1)}
    build_slots = {wire.get_uint(a, 8): wire.get_uint(wire.get_bytes(a, 25), 1)
                   for a in wire.get_repeated_bytes(config, 10) if any(f.number == 25 for f in wire.parse_fields(a))}
    data = (match_dir / "frames.bin").read_bytes()
    offset, commands, activity, warnings = 0, [], [], []
    while offset < len(data):
        if len(data) - offset < 4:
            warnings.append("Incomplete trailing frame journal length")
            break
        size = struct.unpack_from("<I", data, offset)[0]; offset += 4
        if size > 32 * 1024 * 1024: raise ValueError("frame journal entry exceeds bound")
        if size > len(data) - offset:
            warnings.append("Incomplete trailing frame journal entry")
            break
        frame = decode_frame(data[offset:offset + size]); offset += size
        for player in frame["players"]:
            army = owners.get(decode_identity(wire.get_bytes(player, 1))["player_id"])
            if army is None: raise ValueError("frame journal identity absent from bootstrap")
            for action in wire.get_repeated_bytes(player, 2):
                activity.append((frame["frame"], army))
                command = wire.get_bytes(action, 1)
                if not command: continue
                groups = wire.get_repeated_bytes(command, 1)
                for group in groups:
                    ability = wire.get_uint(group, 2)
                    if ability not in build_slots: continue
                    deck_slot = build_slots[ability]
                    unit_type = decks[army][deck_slot]
                    entity = entities[unit_type]
                    cost = wire.get_bytes(entity, 16)
                    # ResourceCost fields2/3 and EntityConfig.supply_cost4 are Q32.32.
                    expected = {"primary": wire.get_uint(cost, 2) / (1 << 32),
                                "secondary": wire.get_uint(cost, 3) / (1 << 32),
                                "supply": wire.get_uint(entity, 4) / (1 << 32)}
                    commands.append({"frame": frame["frame"], "army": army, "ability": ability,
                                     "deck_slot": deck_slot, "unit_type": unit_type, "expected": expected,
                                     "entity_ids": list(wire.get_repeated_uint(group, 3)),
                                     "single_group": len(groups) == 1})
    for command in commands:
        frame, army = command["frame"], command["army"]
        before_keys = [key for key in snapshots if key[1] == army and key[0] < frame]
        after_keys = [key for key in snapshots if key[1] == army and key[0] >= frame]
        if not before_keys or not after_keys:
            command["status"] = "insufficient_snapshots"
            continue
        before_key, after_key = max(before_keys), min(after_keys)
        before, after = snapshots[before_key], snapshots[after_key]
        other_actions = sum(a == army and before_key[0] < f <= after_key[0] for f, a in activity)
        if other_actions != 1 or not command["single_group"] or len(command["entity_ids"]) != 1:
            command["status"] = "nonisolated_action_window"
            continue
        prior = before["resources"].get(army)
        current = after["resources"].get(army)
        if prior is None or current is None:
            command["status"] = "missing_resource_view"
            continue
        spent = {name: (current[name + "_gathered"] - current[name]) -
                       (prior[name + "_gathered"] - prior[name]) for name in ("primary", "secondary")}
        spent["supply"] = current["current_supply"] - prior["current_supply"]
        previous_ids = {e["id"] for e in before.get("entities", [])}
        new_units = [e["id"] for e in after.get("entities", []) if e["id"] not in previous_ids
                     and e.get("army") == army and e.get("type") == command["unit_type"]]
        command.update(before_frame=before_key[0], after_frame=after_key[0], observed=spent,
                       created_entity_ids=new_units)
        command["status"] = "verified" if spent == command["expected"] and len(new_units) == 1 else "effect_mismatch"
    return commands, warnings


def verify(run_directory, runtime_directory, processes_path, match_id=None):
    events, warnings = read_events(run_directory / "events.jsonl")
    processes = json.loads(processes_path.read_text(encoding="utf-8-sig"))
    pids = processes.get("GamePids", [])
    if len(pids) != 2: raise ValueError("process manifest must identify two GamePids in slot order")
    matches = sorted({e["match"] for e in events if e.get("match")})
    if match_id is None:
        match_id = next((e["match"] for e in reversed(events) if e.get("match")), None)
    if match_id and match_id not in matches: raise ValueError("requested match is absent from server audit")
    selected = [e for e in events if e.get("match") == match_id] if match_id else []
    frame_events = {e["frame"]: e for e in selected if e.get("event") == "frame_queued"}
    snapshots, bad_snapshots = {}, []
    match_dir = run_directory / "matches" / match_id if match_id else None
    if match_dir and (match_dir / "snapshots").exists():
        for path in sorted((match_dir / "snapshots").glob("*.bin")):
            try:
                frame_text, viewer_text = path.stem.split("-")
                frame, viewer = int(frame_text), int(viewer_text)
                state = canonical_snapshot(path.read_bytes(), viewer, include_entities=True)
                if state["frame"] != frame: raise ValueError("filename/embedded frame disagreement")
                snapshots[frame, viewer] = state
            except Exception as error:
                bad_snapshots.append({"path": str(path), "error": str(error)})
    bootstrap_path = match_dir / "bootstrap.pb.gz" if match_dir else None
    server_bootstrap = digest_game_data(bootstrap_path) if bootstrap_path and bootstrap_path.exists() else None
    builds, journal_warnings = production_evidence(match_dir, snapshots)
    warnings.extend(journal_warnings)
    completed = [e for e in selected if e.get("event") == "match_completed"]
    server_result = completed[-1].get("result") if completed else None
    complete_snapshots = [{"frame": f, "viewer": v, "result": state["game_state"]}
                          for (f, v), state in sorted(snapshots.items()) if state["game_state"]["complete"]]
    result_snapshot_mismatches = [row for row in complete_snapshots if server_result and row["result"] != server_result]
    clients, mismatch_count, invalid_count, sufficient = [], 0, len(bad_snapshots), bool(snapshots and frame_events)
    mismatch_count += len(result_snapshot_mismatches) + sum(b["status"] == "effect_mismatch" for b in builds)
    if server_result and {row["viewer"] for row in complete_snapshots} != {0, 1}: sufficient = False
    for slot, pid in enumerate(pids):
        per_match = any(runtime_directory.glob(f"lan-audit-{pid}-*.tsv"))
        suffix = f"{pid}-{match_id}" if per_match else str(pid)
        audit_path = runtime_directory / f"lan-audit-{suffix}.tsv"
        resource_path = runtime_directory / f"lan-resources-{suffix}.tsv"
        log_path = runtime_directory / f"dedicated-native-{pid}.log"
        if not log_path.exists(): log_path = runtime_directory / f"lan-native-{slot}.log"
        segment, log_warning = client_log_segment(log_path, pid)
        segment, slot, scope_warning = scope_match_log(segment, match_id, slot)
        log_warning = log_warning or scope_warning
        audit, duplicates = read_tsv(audit_path, ("frame", "viewer"))
        resources, resource_duplicates = read_tsv(resource_path, ("frame", "viewer", "army"))
        common = sorted(snapshots.keys() & audit.keys())
        canonical_mismatches, count_mismatches, resource_mismatches, missing_resources = [], [], [], []
        resource_comparisons = 0
        for frame, viewer in common:
            state, row = snapshots[frame, viewer], audit[frame, viewer]
            if state["canonical_fnv1a64"] != row["canonical_fnv1a64"].lower():
                canonical_mismatches.append({"frame": frame, "viewer": viewer,
                    "server": state["canonical_fnv1a64"], "client": row["canonical_fnv1a64"]})
            differences = {name: {"server": state["counts"][name], "client": int(row[column])}
                           for name, column in COUNT_MAP.items() if state["counts"][name] != int(row[column])}
            if differences: count_mismatches.append({"frame": frame, "viewer": viewer, "counts": differences})
            for army, values in state["resources"].items():
                resource_row = resources.get((frame, viewer, army))
                if resource_row is None:
                    missing_resources.append({"frame": frame, "viewer": viewer, "army": army})
                    continue
                resource_comparisons += 1
                diff = {name: {"server": value, "client": int(resource_row[name])}
                        for name, value in values.items() if value != int(resource_row[name])}
                if diff: resource_mismatches.append({"frame": frame, "viewer": viewer, "army": army, "values": diff})
        client_results, smoke_builds = [], []
        receipt_path = runtime_directory / f"dedicated-receipts-{pid}-{match_id}.tsv"
        receipt_duplicates = []
        receipt_lines = segment
        if receipt_path.exists():
            receipt_rows, receipt_duplicates = read_tsv(receipt_path, ("frame",))
            if any(row['pid'] != str(pid) or row['match'] != match_id for row in receipt_rows.values()):
                raise ValueError("receipt journal process/match identity mismatch")
            receipt_lines = [f"LAN received frame {row['frame']}, actions={row['actions']}, sim={row['sim']} sha256={row['sha256']}" for row in receipt_rows.values()]
        for line in segment:
            if "Dedicated match ended: " in line:
                receipt = json.loads(line.split("Dedicated match ended: ", 1)[1])
                if receipt.get("match") == match_id: client_results.append(receipt)
            smoke = BUILD_SMOKE.search(line)
            if smoke:
                values = [int(smoke[i]) for i in range(1, 8)]
                record = dict(zip(("frame", "slot", "army", "hq", "deck_slot", "unit_type", "ability"), values))
                record["authoritative_effect_verified"] = any(b["status"] == "verified" and all(
                    record[name] == b[name] for name in ("frame", "army", "deck_slot", "unit_type", "ability")) for b in builds)
                smoke_builds.append(record)
        received, transport_mismatches, missing_server_frames = [], [], []
        for line in receipt_lines:
            match = RECEIVED.search(line)
            if not match: continue
            frame, action_count, sim_frame = (int(match[i]) for i in (1,2,3))
            digest = match[4]
            item = {"frame": frame, "actions": action_count, "sim_frame_at_enqueue": sim_frame, "sha256": digest}
            received.append(item)
            expected = frame_events.get(frame)
            if expected is None: missing_server_frames.append(frame)
            elif digest != expected.get("frame_payload_sha256"):
                transport_mismatches.append(item | {"server_sha256": expected.get("frame_payload_sha256")})
        missing_client_receipts = sorted(set(frame_events) - {row['frame'] for row in received}) if receipt_path.exists() else []
        client_bootstrap_path = runtime_directory / f"dedicated-bootstrap-{pid}-{match_id}.pb.gz"
        if not client_bootstrap_path.exists() and not per_match:
            client_bootstrap_path = runtime_directory / f"lan-bootstrap-{pid}.pb.gz"
        client_bootstrap = digest_game_data(client_bootstrap_path) if client_bootstrap_path.exists() else None
        bootstrap_match = bool(server_bootstrap and client_bootstrap == server_bootstrap)
        result_mismatches = [receipt for receipt in client_results if server_result and receipt.get("result") != server_result]
        local_mismatches = len(canonical_mismatches)+len(count_mismatches)+len(resource_mismatches)+len(transport_mismatches)+len(result_mismatches)
        if server_bootstrap and client_bootstrap and not bootstrap_match: local_mismatches += 1
        mismatch_count += local_mismatches
        invalid_count += len(duplicates)+len(resource_duplicates)+len(receipt_duplicates)
        nonempty = [key for key in common if snapshots[key]["counts"]["position"] and snapshots[key]["counts"]["resources"]]
        client_sufficient = bool({v for f, v in nonempty} == {0, 1} and resource_comparisons and received
                                 and bootstrap_match and not missing_server_frames and not missing_resources
                                 and not missing_client_receipts and not log_warning)
        if server_result and not client_results: client_sufficient = False
        if any(not record["authoritative_effect_verified"] for record in smoke_builds): client_sufficient = False
        sufficient = sufficient and client_sufficient
        clients.append({"slot": slot, "pid": pid, "audit_path": str(audit_path), "resource_path": str(resource_path),
            "native_log_path": str(log_path), "log_scope_warning": log_warning, "evidence_sufficient": client_sufficient,
            "common_snapshot_samples": len(common), "common_frames": len({f for f,v in common}),
            "views": sorted({v for f,v in common}), "nonempty_samples": len(nonempty),
            "only_server_samples": len(snapshots.keys()-audit.keys()), "only_client_samples": len(audit.keys()-snapshots.keys()),
            "canonical_mismatches": canonical_mismatches, "count_mismatches": count_mismatches,
            "resource_rows_compared": resource_comparisons, "resource_mismatches": resource_mismatches,
            "missing_resource_rows": missing_resources, "conflicting_duplicate_audits": duplicates,
            "conflicting_duplicate_resources": resource_duplicates,
            "logged_received_frames": received, "transport_hash_mismatches": transport_mismatches,
            "receipt_journal": str(receipt_path) if receipt_path.exists() else None,
            "conflicting_duplicate_receipts": receipt_duplicates, "missing_client_receipts": missing_client_receipts,
            "logged_frames_missing_on_server": missing_server_frames,
            "build_smoke_commands": smoke_builds, "match_end_receipts": client_results,
            "match_result_mismatches": result_mismatches,
            "bootstrap_sha256": client_bootstrap, "bootstrap_matches_server": bootstrap_match})
    if invalid_count: status, exit_code = "invalid_or_incomplete_artifacts", 1
    elif mismatch_count: status, exit_code = "divergent_evidence", 2
    elif not sufficient: status, exit_code = "insufficient_evidence", 3
    else: status, exit_code = "matching_sampled_server_and_clients", 0
    return {"status": status, "exit_code": exit_code, "match": match_id, "available_matches": matches,
            "run_directory": str(run_directory.resolve()), "process_manifest": str(processes_path.resolve()),
            "server_frame_count": len(frame_events), "server_snapshot_count": len(snapshots),
            "server_bootstrap_sha256": server_bootstrap, "bad_snapshots": bad_snapshots,
            "server_errors": [e for e in events if e.get("event") in ("simulation_error", "protocol_error", "match_aborted")
                              and (not e.get("match") or e.get("match") == match_id)],
            "server_results": completed, "complete_snapshot_results": complete_snapshots,
            "result_snapshot_mismatches": result_snapshot_mismatches, "production_effects": builds,
            "clients": clients, "mismatch_count": mismatch_count, "warnings": warnings,
            "limits": ["Canonical hashes cover selected observable state, not all hidden native fields.",
                       "Client transport logs are sampled: normally every 200 frames and on action-bearing frames.",
                       "Only common server/client snapshot keys are compared; startup or live-tail gaps are reported.",
                       "Per-match audits/receipts are used when present; legacy per-PID audits support one match only."]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_directory", type=pathlib.Path)
    ap.add_argument("--runtime-directory", type=pathlib.Path, default=ROOT/"investigation/runtime")
    ap.add_argument("--processes", type=pathlib.Path)
    ap.add_argument("--match")
    ap.add_argument("-o", "--output", type=pathlib.Path)
    args = ap.parse_args()
    processes = args.processes or args.runtime_directory / f"{args.run_directory.name}-processes.json"
    try: result = verify(args.run_directory, args.runtime_directory, processes, args.match)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {"status": "invalid_input", "exit_code": 1, "error": str(error)}
    rendered = json.dumps(result, indent=2)
    if args.output: args.output.write_text(rendered+"\n", encoding="utf-8")
    print(rendered)
    return result["exit_code"]


if __name__ == "__main__": raise SystemExit(main())
