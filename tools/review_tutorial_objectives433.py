"""Inspect the shipped Tutorial01 objective bundle without starting the game."""

import argparse
import base64
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

from tools.extract_descriptors import Metadata, PE


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'local/privacy301-runtime01/game/Battle Aces_Data/StreamingAssets/aa/catalog.json'
BUNDLE_DIR = CATALOG.parent / 'StandaloneWindows64'
ORIGINAL = Path(os.environ.get('BA_ORIGINAL_GAME_ROOT', ROOT / 'local/pristine-game'))
CURRENT = ROOT / 'local/privacy301-runtime01/game/GameAssembly.dll'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entries(catalog):
    raw = base64.b64decode(catalog['m_EntryDataString'], validate=True)
    count, = struct.unpack_from('<I', raw)
    assert len(raw) == 4 + count * 28
    return [struct.unpack_from('<7i', raw, 4 + i * 28) for i in range(count)]


def buckets(catalog, wanted):
    raw = base64.b64decode(catalog['m_BucketDataString'], validate=True)
    count, = struct.unpack_from('<I', raw)
    cursor = 4
    selected = {}
    for index in range(count):
        _, entry_count = struct.unpack_from('<2i', raw, cursor)
        cursor += 8
        if index in wanted:
            selected[index] = set(struct.unpack_from('<' + str(entry_count) + 'i', raw, cursor))
        cursor += entry_count * 4
    assert cursor == len(raw)
    return selected


def named_object(objects, name):
    matches = []
    for obj in objects:
        if obj.type.name != 'MonoBehaviour':
            continue
        data = obj.read_typetree()
        if data.get('m_Name') == name:
            matches.append((obj.path_id, data))
    assert len(matches) == 1, (name, len(matches))
    return matches[0]


def reference(data, rid):
    matches = [item for item in data['references']['RefIds'] if item['rid'] == rid]
    assert len(matches) == 1
    return matches[0]


def main(output, unitypy_root):
    sys.path.insert(0, str(unitypy_root.resolve()))
    import UnityPy

    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    rows = entries(catalog)
    ids = catalog['m_InternalIds']
    def row_for(path):
        matches = [(index, row) for index, row in enumerate(rows) if ids[row[0]] == path]
        assert len(matches) == 1, (path, len(matches))
        return matches[0]

    objective_entry, objective = row_for('Assets/RGame/Content/FTUE/ObjectiveController.asset')
    game_entry, game = row_for('FTUEGame.asset')
    selected = buckets(catalog, {objective[2], game[2]})
    only_objective = selected[objective[2]] - selected[game[2]]
    assert len(only_objective) == 1, only_objective
    bundle_entry = next(iter(only_objective))
    bundle_id = ids[rows[bundle_entry][0]]
    assert bundle_id.endswith('.bundle')
    bundle = BUNDLE_DIR / Path(bundle_id.replace('\\', '/')).name
    assert bundle.is_file()
    environment = UnityPy.load(str(bundle))
    assert 'Assets/RGame/Content/FTUE/ObjectiveController.asset' in environment.container
    assert len(environment.container) == 16

    _, built = named_object(environment.objects, '2_Expand_2_Built')
    assert len(built['Conditions']) == 1
    condition = reference(built, built['Conditions'][0]['rid'])
    assert condition['type']['class'] == 'UnitTypeProduced'
    assert condition['data']['UnitType']['_id'] == 18
    assert condition['data']['RequiredCountNumber'] == 1
    variables = {v['name']: reference(built, v['variable']['rid'])['data']['m_Value']
                 for v in built['Description']['m_LocalVariables']}
    assert variables['HotKeyName'] == 'Z'
    assert variables['UnitName'] == 'LOC[ExpansionBuilt]:[Units]'

    _, final = named_object(environment.objects, 'FinalComplete')
    assert len(final['MetaDataArray']) == 1
    event = reference(final, final['MetaDataArray'][0]['rid'])
    assert event['type']['class'] == 'ObjectiveSkippedEvent'
    action = reference(final, event['data']['ExecutableMetaList'][0]['rid'])
    assert action['type']['class'] == 'MarkFTUEFullyComplete'

    _, graph_asset = named_object(environment.objects, 'FTUEtutorial')
    graph = json.loads(graph_asset['_data']['_json'])['graph']
    refs = graph_asset['_data']['_objectReferences']
    present = {item['m_PathID'] for item in refs if item['m_FileID'] == 0}
    built_path = named_object(environment.objects, '2_Expand_2_Built')[0]
    final_path = named_object(environment.objects, 'FinalComplete')[0]
    assert built_path in present and final_path in present
    assert len(graph['elements']) == 6

    metadata_path = ORIGINAL / 'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat'
    md = Metadata(metadata_path.read_bytes())
    assert md.string(md.types[3743][0]) == 'MarkFTUEFullyComplete'
    execute = next(method for method in md.methods_for_type(md.types[3743])
                   if md.string(method[0]) == 'Uncapped.ObjectiveFramework.IExectuableMeta.Execute')
    original = PE((ORIGINAL / 'GameAssembly.dll').read_bytes())
    current = PE(CURRENT.read_bytes())
    _, table = original.module('RGame.dll', execute[6] & 0xFFFFFF)
    address, = struct.unpack_from('<Q', original.data,
                                  original.offset(table + ((execute[6] & 0xFFFFFF) - 1) * 8))
    assert address == original.base + 0x6AF170
    marker_bytes = bytes.fromhex('c20000')
    assert original.data[original.offset(address, 3):original.offset(address, 3) + 3] == marker_bytes
    assert current.data[current.offset(address, 3):current.offset(address, 3) + 3] == marker_bytes
    result = {
        'passed': True,
        'scope': 'Shipped catalog and authored Tutorial01 bundle data; not a runtime objective or completion result',
        'catalog_sha256': sha256(CATALOG),
        'objective_catalog_entry': objective_entry,
        'ftue_game_catalog_entry': game_entry,
        'objective_only_bundle_entry': bundle_entry,
        'bundle': bundle.name,
        'bundle_sha256': sha256(bundle),
        'bundle_container_count': len(environment.container),
        'first_observed_objective': {
            'name': built['m_Name'],
            'dependency_path_id': built['Dependency']['m_PathID'],
            'condition': condition['type']['class'],
            'unit_type_id': condition['data']['UnitType']['_id'],
            'required_count': condition['data']['RequiredCountNumber'],
            'variables': variables,
        },
        'final_objective': {
            'name': final['m_Name'],
            'event': event['type']['class'],
            'action': action['type']['class'],
            'execute_rva': hex(address - original.base),
            'original_current_execute_bytes': marker_bytes.hex(),
        },
        'graph_references_both': True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'output': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--unitypy-root', type=Path, default=ROOT / 'local/d5-unitypy')
    args = parser.parse_args()
    main(args.output, args.unitypy_root)
