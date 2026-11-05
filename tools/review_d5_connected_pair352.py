"""Bind recipe38's private connected pair to its separate loaded-byte menu audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.review_d5_connected_pair338 import ROOT, run, sha


def review(case: Path, packages: Path, game: Path, assets: Path, menu: Path) -> dict:
    result = run(case, packages, game, assets)
    installed = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    observed = json.loads((menu / 'verification.json').read_text(encoding='utf-8'))
    audit = (menu / 'native.log').read_text(encoding='utf-8', errors='replace')
    assert RECIPE_VERSION == installed['telemetry']['recipe_version'] == 38
    assert RUNTIME_VALIDATED is installed['telemetry']['runtime_validated'] is False
    assert observed['passed'] and observed['natural_exit'] and not observed['forced_cleanup']
    assert observed['exit_code'] == 0 and observed['owned_process_reaped']
    assert observed['telemetry']['passed'] and observed['telemetry']['recipe_version'] == 38
    assert observed['telemetry']['complete_snapshots'] == 3
    assert 'recipeVersion=38' in audit and 'sdkSessionCacheSignatures=1/1' in audit
    assert observed['patch_manifest_sha256'] == sha(game / '.battleaces-resurrection/patch-manifest.json')
    assert observed['helper_sha256'] == installed['helper_sha256']
    assert observed['shared_settings_unchanged'] and observed['source_files_unchanged']
    assert installed['components']['GameAssembly.dll']['telemetry_guards'] == 102
    result.update(scope='Owned recipe38 private package pair: connected public1 two-human match, natural client shutdown, and separate owned session-cache loaded-byte audit1/1; no full privacy queue/file/wire capture',
                  recipe_version=38, menu_report_sha256=sha(menu / 'verification.json'),
                  menu_audit_sha256=sha(menu / 'native.log'),
                  session_cache_loaded_guard_count=1,
                  package_build_report_sha256=sha(packages / 'build-report.json'))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('case', 'packages', 'game', 'assets', 'menu'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ('case', 'packages', 'game', 'assets', 'menu')}
    assert all(path.is_relative_to(ROOT / 'local') for path in paths.values())
    result = review(**paths)
    output = paths['case'] / 'review.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'review': str(output),
                      'recipe': result['recipe_version'], 'frames': result['frames']}))


if __name__ == '__main__':
    main()
