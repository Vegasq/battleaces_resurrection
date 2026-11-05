"""Prepare the isolated advertising caller witness for two owned connected clients.

Run only after the packaged verifier publishes two suspended game-process rows.
The normal game and package launchers never load this diagnostic script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from client_patch.patcher.telemetry import RECIPE_VERSION
from tools.frida_ads_caller import CALLBACK_SIZE, EVENT_LIMIT, SOURCE, describe_unity
from tools.frida_ads_game import EXIT_ADAPTER

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy301-runtime01/game'
ORIGINAL = ROOT.parent.parent / 'BattleAcesBeta_untouched/UnityPlayer.dll'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_for(config: dict) -> str:
    return (SOURCE.replace('__CONFIG__', json.dumps(config))
            .replace('__MODULE__', json.dumps(str(GAME / 'UnityPlayer.dll')))
            .replace('__BODY_SIZE__', str(CALLBACK_SIZE))
            .replace('__LIMIT__', str(EVENT_LIMIT)) + EXIT_ADAPTER)


def prepare(case: Path, trace: Path) -> dict:
    case, trace = case.resolve(), trace.resolve()
    assert case.is_relative_to(ROOT / 'local') and trace.is_relative_to(ROOT / 'local')
    assert trace.is_dir() and not any(trace.iterdir())
    assert RECIPE_VERSION == 38 and GAME.is_dir()
    descriptor = describe_unity(ORIGINAL.read_bytes(), (GAME / 'UnityPlayer.dll').read_bytes())
    entries = []
    for index in range(2):
        row = json.loads((case / f'client-{index}/game-process.json').read_bytes())
        command = row['actual_arguments']
        assert row['suspended_for_observer'] is True and command[0] == str(GAME / 'Battle Aces.exe')
        assert not any(arg.lower().startswith(('-telemetry-audit', '-telemetry-device-probe'))
                       for arg in command)
        profiles = [arg.split('=', 1)[1] for arg in command if arg.startswith('-local-profile=')]
        assert len(profiles) == 1 and re.fullmatch(r'nativestest_rcnetwork_[0-9a-f]{12}_[01]', profiles[0])
        assert profiles[0].endswith(f'_{index}')
        config = dict(image=command[0], profile=str(GAME / '.battleaces-resurrection/profiles' / profiles[0]),
                      argv=command, pid=row['pid'], runId=hashlib.sha256(
                          (str(case) + ':' + str(index) + ':' + str(row['pid'])).encode()).hexdigest()[:32],
                      unity=descriptor)
        source = source_for(config)
        script = trace / f'observer-{index}.js'
        script.write_text(source, encoding='utf-8')
        (trace / f'config-{index}.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
        entries.append(dict(index=index, pid=row['pid'], script=str(script), script_sha256=sha(script)))
    receipt = dict(prepared=True, case=str(case), game=str(GAME), descriptor=descriptor,
                   clients=entries, diagnostic_only=True)
    (trace / 'prepare.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--trace', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.case, args.trace)))
