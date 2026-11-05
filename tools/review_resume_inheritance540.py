"""Transfer the named fresh-process report-resumption proof from173 to recipe47."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED
from tools.review_unity_post512 import GAME, ROOT, review as review_installed


PRIOR = ROOT / 'local/report173-applicability01'
PRIOR_SHA = '0dbe2d1cdf4be0fe4226e5038f9ef05358c54b61f6be793b487f6e88195f6f6f'


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def function(path: Path, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name)


def calls(node: ast.AST, name: str) -> list[int]:
    return sorted(call.lineno for call in ast.walk(node) if isinstance(call, ast.Call)
                  and isinstance(call.func, ast.Name) and call.func.id == name)


def review() -> dict:
    assert RECIPE_VERSION == 47 and RUNTIME_VALIDATED is False
    assert sha(PRIOR / 'verification.json') == PRIOR_SHA
    prior = json.loads((PRIOR / 'verification.json').read_text(encoding='utf-8'))
    assert prior['passed'] and prior['recipe'] == 23 and prior['guard_count'] == 128
    bound = review_installed()
    assert bound['passed'] and bound['recipe'] == 47

    count = 0
    for component in prior['components']:
        name = component['path']
        patches = {(p.rva, p.offset, p.label): p for p in COMPONENTS[name].patches}
        installed = (GAME / name).read_bytes()
        original = (GAME / '.battleaces-resurrection/original' / name).read_bytes()
        assert sha(GAME / '.battleaces-resurrection/original' / name) == component['original_sha256']
        for row in component['guards']:
            patch = patches[(row['rva'], row['offset'], row['label'])]
            assert hashlib.sha256(patch.replacement).hexdigest() == row['replacement_sha256']
            assert original[patch.offset:patch.offset + len(patch.guard)] == patch.guard
            assert installed[patch.offset:patch.offset + len(patch.replacement)] == patch.replacement
            count += 1
    assert count == 128

    selected = {
        'GameAssembly.dll': (0x8201f0, 0x8204c0, 0x820de0, 0x81c6a0, 0x81f730),
        'UnityPlayer.dll': (0xc3bafc, 0xc34270),
    }
    for name, rvas in selected.items():
        inherited = {row['rva'] for component in prior['components'] if component['path'] == name
                     for row in component['guards']}
        assert set(rvas) <= inherited
    post = next(p for p in COMPONENTS['UnityPlayer.dll'].patches if p.rva == 0xc64e20)
    assert post.replacement == bytes.fromhex('31c0c3')
    assert (GAME / 'UnityPlayer.dll').read_bytes()[post.offset:post.offset + 3] == post.replacement

    old_patch = PRIOR / 'sources/client_patch/patcher/patch_client.py'
    new_patch = ROOT / 'client_patch/patcher/patch_client.py'
    old_launcher = PRIOR / 'sources/client_patch/transport/launcher.py'
    new_launcher = ROOT / 'client_patch/transport/launcher.py'
    assert ast.dump(function(old_patch, 'atomic_write')) == ast.dump(function(new_patch, 'atomic_write'))
    assert ast.dump(function(old_launcher, 'spawn_game')) == ast.dump(function(new_launcher, 'spawn_game'))
    old_install, new_install = function(old_patch, 'install'), function(new_patch, 'install')
    assert len(calls(old_install, 'atomic_write')) == len(calls(new_install, 'atomic_write')) == 3
    launch = function(new_launcher, 'launch')
    assert len(calls(launch, 'verify_game')) == len(calls(launch, 'spawn_game')) == 1
    assert calls(launch, 'verify_game')[0] < calls(launch, 'spawn_game')[0]

    return dict(passed=True, recipe=47, prior_recipe=23, prior_guard_count=count,
                selected_managed_entry_rvas=[hex(x) for x in selected['GameAssembly.dll']],
                selected_unity_entry_rvas=[hex(x) for x in selected['UnityPlayer.dll']],
                current_post_guard_rva=hex(post.rva), current_game= str(GAME.relative_to(ROOT)),
                current_unity_sha256=sha(GAME / 'UnityPlayer.dll'),
                current_gameassembly_sha256=sha(GAME / 'GameAssembly.dll'),
                fresh_process_boundary_preserved=True, original_running_process_cancelled=False,
                alternate_paths_closed=False, full_d5_qualified=False)


if __name__ == '__main__':
    result = review()
    out = ROOT / 'local/privacy540-resume-inheritance.json'
    out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
