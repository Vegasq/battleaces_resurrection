"""Audit staged/tracked content and reachable history before source publication.

This is a guard against common accidental inclusion, not a substitute for review.
Only Git objects are read, so ignored local runtime files are not inspected.
"""
from __future__ import annotations
import argparse
from pathlib import PurePosixPath
import hashlib
import re
import subprocess

ROOT_FILES = {".gitignore", ".gitattributes", "README.txt", "README.md", "AGENTS.md"}
SOURCE_DIRS = {"server", "client_patch", "tools", "tests", "docs", ".github"}
EXTENSIONS = {".py", ".cpp", ".cs", ".h", ".hpp", ".ps1", ".cmd", ".txt", ".json", ".yml", ".yaml", ".js", ".asm"}
DOC_SCREENSHOTS = {
    "docs/screenshots/client-installer.png": "50e00f44dd4c90548f11d7a7ba82977febeddeba6c140d167b85dd685e2b9f75",
    "docs/screenshots/server-dashboard.png": "d89b2b68b6a0fbff259f3169a4039f98460d2dff065069064ff07cd08d0ee28a",
}
DOC_MEDIA = {
    "docs/media/crabs-2026.gif": (11450491, "0a55bca8d973e006520c4621ad2a2cd1c3b87532d81b15ca953d8b6aff033b1f"),
    "docs/media/discord-server.webp": (14522, "20a8cc9fad8aa716d0f85c1782b0aab35ec22c95b53468a91779f9833e87ea83"),
}
DEPLOY_SOURCES = {
    "deploy/linux/README.md",
    "deploy/linux/ba-server-supervise",
    "deploy/linux/battle-aces-server.service",
}
FORBIDDEN_PARTS = {"local", "build", "dist", "assets", "fixtures", "captures", "original",
                   "backups", "metadata", "descriptors", "battle aces_data", "__pycache__"}
SOURCE_FIXTURES = {
    "tests/fixtures/ads_caller181/callback.asm",
    "tests/fixtures/ads_caller181/host.cpp",
    "tests/fixtures/ads_watch471/host.cpp",
}
# Reviewed authored controller source; native captures remain under ignored local/.
# These are exact Git-blob bytes. Changes require review again; this exception
# bypasses only the generic size warning, never the content/path checks below.
REVIEWED_LARGE_SOURCES = {
    "tools/verify_prediction_multiplayer.py": (
        272778, "91d3ca5ab198ec6f823a980e6c706903d25b76637d260a0ee1d9a9449b8ec804"),
}

# Exact, already-published blobs reviewed independently of the current index.
# Four old README versions contain the same generic game-folder example. The
# controller versions retain their earlier authored-source review. These entries
# waive only the named finding for the exact historical bytes; new/indexed data
# and every other content/path/credential check still use the normal rules.
REVIEWED_HISTORICAL_FINDINGS = {
    ("README.md", 8173, "7ded7f6a265b84f99120eb57a640fdf4809f5ecd3bf9d998727950309740f5bc"):
        frozenset({"developer-specific absolute path"}),
    ("README.md", 7820, "b842ac0e5848e11980051dd2b7f9dd1fd81f03958e3b072c2440df182993295f"):
        frozenset({"developer-specific absolute path"}),
    ("README.md", 7246, "09ba338cddc466db9ab85ee04e3b21da62570aa49976fb108aaad3e6360cd14b"):
        frozenset({"developer-specific absolute path"}),
    ("README.md", 6727, "68982d429db09847befa466c0d239da504c8924f4dab759bc4cc136039281f8e"):
        frozenset({"developer-specific absolute path"}),
    ("tools/verify_prediction_multiplayer.py", 270502,
     "c434521815a5d99c5b99f281680aab23a19859446e70fb4a34327fb1ec9562fc"):
        frozenset({"source file over 256 KiB; review for embedded payload"}),
    ("tools/verify_prediction_multiplayer.py", 271482,
     "23b9c6b9fc08671e6568de7d876df5e7341bd3c708cba4d6479fbd09c77b6002"):
        frozenset({"source file over 256 KiB; review for embedded payload"}),
    ("tools/verify_prediction_multiplayer.py", 272006,
     "872bd37fea2eeac4210dd3044fa22fc04b981b3514dea6c8bec5a62f1d193c29"):
        frozenset({"source file over 256 KiB; review for embedded payload"}),
}


def inspect_content(name: str, data: bytes) -> list[str]:
    if name in DOC_MEDIA:
        size, digest = DOC_MEDIA[name]
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            return ["unreviewed documentation media"]
        return []
    if name in DOC_SCREENSHOTS:
        if (len(data) > 128 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n") or
                hashlib.sha256(data).hexdigest() != DOC_SCREENSHOTS[name]):
            return ["unreviewed documentation screenshot"]
        return []
    path = PurePosixPath(name)
    reasons = []
    if name not in ROOT_FILES | DEPLOY_SOURCES and (path.parts[0] not in SOURCE_DIRS or path.suffix.lower() not in EXTENSIONS):
        reasons.append("not an allowed source/documentation path")
    if name not in SOURCE_FIXTURES and any(part.lower() in FORBIDDEN_PARTS for part in path.parts):
        reasons.append("runtime/capture/asset directory")
    if (len(data) > 256 * 1024 and
            REVIEWED_LARGE_SOURCES.get(name) != (len(data), hashlib.sha256(data).hexdigest())):
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


def inspect_history(name: str, data: bytes) -> list[str]:
    reasons = inspect_content(name, data)
    reviewed = REVIEWED_HISTORICAL_FINDINGS.get(
        (name, len(data), hashlib.sha256(data).hexdigest()), frozenset())
    return [reason for reason in reasons if reason not in reviewed]


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
            data = git("cat-file", "blob", oid)
            reasons = inspect_content(name, data) if tree is None else inspect_history(name, data)
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
