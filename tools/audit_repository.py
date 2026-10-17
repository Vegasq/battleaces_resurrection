"""Audit staged/tracked content and reachable history before source publication.

This is a guard against common accidental inclusion, not a substitute for review.
Only Git objects are read, so ignored local runtime files are not inspected.
"""
from __future__ import annotations
import argparse
from pathlib import PurePosixPath
import re
import subprocess

ROOT_FILES = {".gitignore", ".gitattributes", "README.txt"}
SOURCE_DIRS = {"server", "client_patch", "tools", "tests", "docs", ".github"}
EXTENSIONS = {".py", ".cpp", ".h", ".hpp", ".ps1", ".cmd", ".txt", ".json", ".yml", ".yaml"}
FORBIDDEN_PARTS = {"local", "build", "dist", "assets", "fixtures", "captures", "original",
                   "backups", "metadata", "descriptors", "battle aces_data", "__pycache__"}


def inspect_content(name: str, data: bytes) -> list[str]:
    path = PurePosixPath(name)
    reasons = []
    if name not in ROOT_FILES and (path.parts[0] not in SOURCE_DIRS or path.suffix.lower() not in EXTENSIONS):
        reasons.append("not an allowed source/documentation path")
    if any(part.lower() in FORBIDDEN_PARTS for part in path.parts):
        reasons.append("runtime/capture/asset directory")
    if len(data) > 256 * 1024:
        reasons.append("source file over 256 KiB; review for embedded payload")
    if data.startswith((b"MZ", b"\x7fELF", b"PK\x03\x04", b"\x1f\x8b")) or b"\0" in data:
        reasons.append("binary or archive content")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return reasons + ["not UTF-8 source"]
    if re.search(r"[A-Za-z0-9+/]{512,}={0,2}", content):
        reasons.append("long encoded payload")
    if re.search(r"(?:0x[0-9a-fA-F]{2}\s*,\s*){128}", content):
        reasons.append("large byte array")
    if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", content):
        reasons.append("private key")
    if re.search(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b", content):
        reasons.append("GitHub credential")
    if re.search(r"(?<![A-Za-z0-9_-])ba1_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])", content):
        reasons.append("player invite credential")
    if re.search(r"[A-Za-z]:[\\/](?:Users|games)[\\/]", content, re.I):
        reasons.append("developer-specific absolute path")
    return reasons


def git(*args):
    return subprocess.check_output(["git", *args])


def entries(tree=None):
    if tree is None:
        rows = git("ls-files", "--stage", "-z")
        for row in rows.split(b"\0"):
            if row:
                metadata, name = row.split(b"\t", 1)
                mode, oid, stage = metadata.split()
                if stage != b"0":
                    raise ValueError("unmerged index")
                yield mode, oid.decode(), name.decode("utf-8")
    else:
        for row in git("ls-tree", "-r", "-z", tree).split(b"\0"):
            if row:
                metadata, name = row.split(b"\t", 1)
                mode, kind, oid = metadata.split()
                if kind != b"blob":
                    raise ValueError("submodules are outside the source allowlist")
                yield mode, oid.decode(), name.decode("utf-8")


def audit(history=False):
    failures, seen = [], set()
    trees = [None]
    if history:
        trees.extend(git("rev-list", "--all").decode().splitlines())
    for tree in trees:
        for mode, oid, name in entries(tree):
            if (oid, name) in seen:
                continue
            seen.add((oid, name))
            reasons = inspect_content(name, git("cat-file", "blob", oid))
            if mode not in (b"100644", b"100755"):
                reasons.append("symlink or unsupported file mode")
            if reasons:
                failures.append({"path": name, "object": oid, "reasons": reasons})
    return len(seen), failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    count, failures = audit(args.history)
    for item in failures:
        print(item["path"] + ": " + "; ".join(item["reasons"]))
    print(f"Audited {count} distinct source paths/objects; {len(failures)} failures.")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
