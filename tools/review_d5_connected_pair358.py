"""Bind the corrected recipe38 helper, isolated error fixture and paired match."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.review_d5_connected_pair338 import ROOT, run, sha


def review(case: Path, packages: Path, game: Path, assets: Path,
           error_case: Path, helper_receipt: Path) -> dict:
    result = run(case, packages, game, assets)
    connected = json.loads((case/'verification.json').read_text(encoding='utf-8'))
    error = json.loads((error_case/'verification.json').read_text(encoding='utf-8'))
    installed = json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    receipt = json.loads(helper_receipt.read_text(encoding='utf-8'))
    assert RECIPE_VERSION == installed['telemetry']['recipe_version'] == 38
    assert RUNTIME_VALIDATED is installed['telemetry']['runtime_validated'] is False
    assert error['passed'] and error['natural_exit'] and not error['forced_cleanup']
    assert error['exit_code'] == 0 and error['source_files_unchanged']
    assert error['telemetry']['passed'] and error['telemetry']['recipe_version'] == 38
    assert error['telemetry_cache_contract']['passed'] and error['telemetry_cache_contract']['file_identity_bytes_unchanged']
    assert error['telemetry_report_errors']['passed'] and error['telemetry_report_errors']['calls'] == 7
    assert error['telemetry_report_errors']['original_local_exception_logging']
    assert error['helper_sha256'] == receipt['helper_sha256'] == installed['helper_sha256']
    assert error['patch_manifest_sha256'] == sha(game/'.battleaces-resurrection/patch-manifest.json')
    assert connected['helper_build']['sha256'] == sha(helper_receipt)
    assert connected['helper_build']['receipt']['helper_sha256'] == receipt['helper_sha256']
    assert sha(packages/'battleaces-client-win64/program/client-helper/BattleAcesOffline.dll') == receipt['helper_sha256']
    result.update(scope='Owned corrected-helper recipe38 pair: isolated genuine SDK error fixture and connected public1 two-human match with natural shutdown; no real queue/wire/full privacy claim',
                  recipe_version=38, error_report_sha256=sha(error_case/'verification.json'),
                  helper_receipt_sha256=sha(helper_receipt),
                  package_build_report_sha256=sha(packages/'build-report.json'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('case','packages','game','assets','error-case','helper-receipt'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    paths = {name.replace('-','_'):getattr(args,name.replace('-','_')).resolve()
             for name in ('case','packages','game','assets','error-case','helper-receipt')}
    assert all(path.is_relative_to(ROOT/'local') for path in paths.values())
    result = review(**paths)
    output = paths['case']/'review358.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'review':str(output),
                      'recipe':result['recipe_version'],'frames':result['frames']}))


if __name__=='__main__':main()
