"""Run the existing packaged verifier on the immutable recipe39 diagnostic pair.

The normal verifier binds a helper receipt to the *current* source tree. This
wrapper accepts only the exact helper and package already reviewed in452; it
does not certify those historical bytes as a current release candidate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import runpy

from tools import verify_native_quit


ROOT = Path(__file__).resolve().parents[1]
GAME = (ROOT / 'local/privacy441-game01').resolve()
PACKAGES = (ROOT / 'local/privacy441-packages03').resolve()
RECEIPT = (ROOT / 'local/privacy441-helper-build01/helper-build.json').resolve()
PRIOR = (ROOT / 'local/privacy452-connected-sdk01/verification.json').resolve()
CHANGED_SOURCE = 'client_patch/src/telemetry_audit.cpp'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned_receipt(game: Path, path: Path, *, source_revision=None) -> dict:
    if source_revision is not None or game.resolve() != GAME or path.resolve() != RECEIPT:
        raise AssertionError('recipe39 historical pair identity differs')
    previous = json.loads(PRIOR.read_text(encoding='utf-8'))
    receipt = json.loads(RECEIPT.read_text(encoding='utf-8'))
    recorded = previous['helper_build']
    if not (previous['passed'] is True and previous['package_files_unchanged'] is True
            and previous['source_files_unchanged'] is True
            and Path(previous['packages']).resolve() == PACKAGES
            and Path(recorded['path']).resolve() == RECEIPT
            and recorded['sha256'] == digest(RECEIPT)
            and recorded['receipt'] == receipt
            and receipt['sources_unchanged_during_build'] is True
            and receipt['helper_sha256'] == digest(GAME / 'BattleAcesOffline.dll')
            and receipt['helper_sha256'] == digest(PACKAGES / 'battleaces-client-win64/program/client-helper/BattleAcesOffline.dll')):
        raise AssertionError('historical recipe39 receipt/package binding differs')
    current = {name: digest(ROOT / name) for name in receipt['source_sha256']}
    differences = {name for name, sha in receipt['source_sha256'].items() if current[name] != sha}
    if differences != {CHANGED_SOURCE}:
        raise AssertionError(f'unexpected source drift from recipe39: {sorted(differences)}')
    return dict(path=str(RECEIPT), sha256=digest(RECEIPT), receipt=receipt,
                binding='historical-recipe39-diagnostic-only', prior_report=str(PRIOR),
                prior_report_sha256=digest(PRIOR), current_source_difference=CHANGED_SOURCE)


if __name__ == '__main__':
    verify_native_quit.verify_build_receipt = pinned_receipt
    runpy.run_module('tools.verify_packaged_multiplayer', run_name='__main__')
