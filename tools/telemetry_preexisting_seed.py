"""Seed and verify two authored SDK queue files in a fresh owned profile."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

EXPECTED = {
    'Events/authored-event-120.event': 'd8f2d6b8d957ce7109e7277ed39a7c60301c97d6251068fe536ed62b0814207b',
    'Sessions/authored-session-120.session': '0dbcc2e8b51e7dc44fe0a056161f9bbfe5199e5976fcf0a2a35446eb88698c8b',
}
SOURCE = Path(__file__).resolve().parents[1] / 'client_patch/src/telemetry_cache_probe.cpp'


def literals():
    source = SOURCE.read_text(encoding='utf-8')
    result = {}
    for relative, name in zip(EXPECTED, ('eventFixture', 'sessionFixture')):
        match = re.findall(rf'static constexpr const char\* {name}=R"\((.*?)\)";', source, re.S)
        if len(match) != 1:
            raise ValueError(f'{name} source literal missing or ambiguous')
        payload = match[0].encode('utf-8')
        if hashlib.sha256(payload).hexdigest() != EXPECTED[relative]:
            raise ValueError(f'{name} changed from pinned authored fixture')
        result[relative] = payload
    return result


def queue_root(game: Path, profile: str) -> Path:
    if not re.fullmatch(r'nativestest_[a-z0-9_-]{1,34}', profile):
        raise ValueError('owned diagnostic profile required')
    game = game.resolve(strict=True)
    if not game.is_relative_to(Path(__file__).resolve().parents[1] / 'local'):
        raise ValueError('owned game under local required')
    parent = game / '.battleaces-resurrection/profiles'
    if not parent.is_dir() or parent.is_symlink() or parent.resolve() != parent:
        raise ValueError('owned profile parent differs')
    return parent / profile / 'qc/Bugsnag'


def snapshot(root: Path) -> dict:
    if not root.is_dir() or root.is_symlink():
        raise ValueError('authored queue root missing')
    payloads = literals()
    actual = sorted(path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file())
    if actual != sorted(payloads):
        raise ValueError('authored queue file set differs')
    result = {}
    for relative, payload in payloads.items():
        path = root / relative
        if path.is_symlink() or path.read_bytes() != payload:
            raise ValueError('authored queue file bytes differ')
        info = path.stat()
        result[relative] = dict(sha256=EXPECTED[relative], size=info.st_size,
                                device=info.st_dev, file_id=info.st_ino)
    return result


def seed(game: Path, profile: str) -> tuple[Path, dict]:
    root = queue_root(game, profile)
    profile_dir = root.parents[1]
    if profile_dir.exists() or profile_dir.is_symlink():
        raise ValueError('preexisting-queue profile must be new')
    payloads = literals()
    for relative, payload in payloads.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as output:
            output.write(payload)
            output.flush()
    return root, snapshot(root)
