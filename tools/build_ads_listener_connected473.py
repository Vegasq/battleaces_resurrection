"""Bind the proven menu write-watch sensor to suspended recipe39 clients."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy473-connected-watch01'
SOURCE = ROOT / 'local/privacy472-adswatch01/observer.js'
GAME = ROOT / 'local/privacy441-game01/Battle Aces.exe'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> None:
    template = SOURCE.read_text(encoding='utf-8')
    if "const expectedPid=49300,runId='4a015a7f4456323dccaf8bcbc70f470d';" not in template:
        raise ValueError('positive-reviewed menu observer differs')
    if not OUT.is_dir() or not GAME.is_file():
        raise ValueError('fresh private pair is not suspended')
    for index in (0, 1):
        folder = OUT / f'client-{index}'
        pid = json.loads((folder / 'game-process.json').read_text(encoding='utf-8'))['pid']
        run_id = secrets.token_hex(16)
        source = template.replace(
            "const expectedPid=49300,runId='4a015a7f4456323dccaf8bcbc70f470d';",
            f"const expectedPid={pid},runId='{run_id}';")
        if source == template:
            raise ValueError('observer identity substitution failed')
        path = folder / 'listener-watch.js'
        path.write_text(source, encoding='utf-8')
        (folder / 'listener-watch-binding.json').write_text(json.dumps(dict(
            pid=pid, run_id=run_id, game=str(GAME), game_sha256=sha(GAME),
            source=str(SOURCE), source_sha256=sha(SOURCE),
            script_sha256=sha(path)), indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(index=index, pid=pid, run_id=run_id, script=str(path))))


if __name__ == '__main__':
    run()
