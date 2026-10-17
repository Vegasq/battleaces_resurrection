"""Validate and import locally exported assets; never download or publish game data."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from server.game_data import GameTemplate, decompress_game_data
from server.native_simulation import SUPPORTED_DLL_SHA256
from server.paths import ASSETS, ROOT
from server.protocol import BUILD_SHA
from tools.extract_descriptors import extract, GAME_ASSEMBLY_SHA256


def verify_export(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'export.json').read_text(encoding='utf-8-sig'))
    if (manifest.get('schema'), manifest.get('asset_format'), manifest.get('build'), manifest.get('complete')) != (1, 1, 37822, True):
        raise ValueError('Incomplete or unsupported client export')
    if manifest.get('original_gameassembly_sha256') != BUILD_SHA or manifest.get('simulation_sha256') != SUPPORTED_DLL_SHA256:
        raise ValueError('Export game build mismatch')
    result = {}
    for name in ('map-1v1.pb.gz', 'unit-catalog.json'):
        data = (directory / name).read_bytes()
        expected = manifest['files'][name]
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Export size/hash mismatch: ' + name)
        result[name] = data
    raw = decompress_game_data(result['map-1v1.pb.gz'])
    if len(raw) != manifest['raw_game_data']['bytes'] or hashlib.sha256(raw).hexdigest() != manifest['raw_game_data']['sha256']:
        raise ValueError('Export uncompressed map hash mismatch')
    return result


def import_assets(game_dir, export_dir, destination=ASSETS, original=None):
    game_dir, destination = Path(game_dir).resolve(), Path(destination).resolve()
    if destination.is_relative_to(ROOT) and not destination.is_relative_to(ROOT / 'local'):
        raise ValueError('Imported game data inside this checkout must stay under ignored local/')
    if destination == game_dir or game_dir.is_relative_to(destination):
        raise ValueError('Choose a separate asset directory, not the game installation or its parent')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Choose an empty destination; existing assets are never overwritten')
    original = Path(original) if original else game_dir / 'GameAssembly.dll'
    if hashlib.sha256(original.read_bytes()).hexdigest() != GAME_ASSEMBLY_SHA256:
        raise ValueError('Descriptor extraction requires the verified original DLL; use --original for a patched install')
    simulation = game_dir / 'Battle Aces_Data/Plugins/x86_64/Simulation.dll'
    sim_data = simulation.read_bytes()
    if hashlib.sha256(sim_data).hexdigest() != SUPPORTED_DLL_SHA256:
        raise ValueError('Simulation DLL hash mismatch')
    exported = verify_export(export_dir)
    metadata = game_dir / 'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat'
    destination.mkdir(parents=True, exist_ok=True)
    # Completion manifest is written last. A failed import remains incomplete;
    # the evidence is retained, and the next attempt needs a fresh destination.
    extraction = extract(original, metadata, destination / 'descriptors')
    for name, data in exported.items():
        (destination / name).write_bytes(data)
    shutil.copyfile(simulation, destination / 'Simulation.dll')
    template = GameTemplate.load(destination / 'map-1v1.pb.gz',
                                 catalog_path=destination / 'unit-catalog.json',
                                 descriptors_path=destination / 'descriptors')
    if template.runtime_catalog is None or template.default_decks_provisional:
        raise ValueError('Export did not produce a complete playable catalog')
    files = {p.relative_to(destination).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(destination.rglob('*')) if p.is_file()}
    manifest = {'schema': 1, 'game_build': 37822, 'asset_format': 1,
                'original_gameassembly_sha256': BUILD_SHA, 'simulation_sha256': SUPPORTED_DLL_SHA256,
                'descriptor_count': extraction['descriptor_count'],
                'playable_units': len(template.catalog_serializable()), 'files': files}
    (destination / 'asset-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--export-dir', type=Path, required=True)
    parser.add_argument('--destination', type=Path, default=ASSETS)
    parser.add_argument('--original', type=Path)
    args = parser.parse_args()
    result = import_assets(args.game_dir, args.export_dir, args.destination, args.original)
    print(json.dumps({'output': str(args.destination.resolve()), 'descriptors': result['descriptor_count'],
                      'playable_units': result['playable_units'], 'files': len(result['files'])}))


if __name__ == '__main__':
    main()
