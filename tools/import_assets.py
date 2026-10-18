"""Validate and import locally exported assets; never download or publish game data."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from server.game_data import GameTemplate, decompress_game_data
from server.native_simulation import SUPPORTED_DLL_SHA256
from server.ai_rules import RuleBook, SUPPORTED_AI_SHA256
from server.bot_catalog import BotCatalog
from server.paths import ASSETS, ROOT
from server.protocol import BUILD_SHA
from tools.extract_descriptors import extract, GAME_ASSEMBLY_SHA256, validate_output_directory


def verify_export(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'export.json').read_text(encoding='utf-8-sig'))
    if (manifest.get('schema'), manifest.get('asset_format'), manifest.get('build'), manifest.get('complete')) != (1, 1, 37822, True):
        raise ValueError('Incomplete or unsupported client export')
    if manifest.get('original_gameassembly_sha256') != BUILD_SHA or manifest.get('simulation_sha256') != SUPPORTED_DLL_SHA256:
        raise ValueError('Export game build mismatch')
    result = {}
    names = ['map-1v1.pb.gz', 'unit-catalog.json']
    if 'ai-rules.json' in manifest['files']: names.append('ai-rules.json')
    bot_files = {'map-2v2.pb.gz', 'map-2vai.pb.gz', 'bot-catalog.json'}
    has_bots = bool(bot_files & manifest['files'].keys())
    if has_bots:
        if not bot_files | {'ai-rules.json'} <= manifest['files'].keys():
            raise ValueError('Incomplete team map/bot export')
        names.extend(sorted(bot_files))
    for name in names:
        data = (directory / name).read_bytes()
        expected = manifest['files'][name]
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Export size/hash mismatch: ' + name)
        result[name] = data
    raw = decompress_game_data(result['map-1v1.pb.gz'])
    if len(raw) != manifest['raw_game_data']['bytes'] or hashlib.sha256(raw).hexdigest() != manifest['raw_game_data']['sha256']:
        raise ValueError('Export uncompressed map hash mismatch')
    if 'ai-rules.json' in result:
        rules = RuleBook(directory)
        if rules.files['ai-rules.json'] != result['ai-rules.json']:
            raise ValueError('AI manifest changed during export verification')
        result.update(rules.files)
    if has_bots:
        maps = {'map-1v1.pb.gz': 1, 'map-2v2.pb.gz': 2, 'map-2vai.pb.gz': 5}
        if set(manifest.get('raw_maps', {})) != set(maps):
            raise ValueError('Incomplete uncompressed map inventory')
        templates = {}
        for name, mode in maps.items():
            raw = decompress_game_data(result[name]); expected = manifest['raw_maps'][name]
            if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
                raise ValueError('Export uncompressed map hash mismatch: ' + name)
            templates[mode] = GameTemplate(raw, catalog_path=directory/'unit-catalog.json')
            if templates[mode].game_mode != mode:
                raise ValueError('Exported map mode mismatch')
        bots = BotCatalog(directory, template=templates[1], rules=rules)
        if bots.raw != result['bot-catalog.json']:
            raise ValueError('Bot catalog changed during export verification')
        for template in templates.values():
            for _, decks in bots.profiles.values():
                for deck in decks: template.validate_deck(deck.units)
    return result


def import_assets(game_dir, export_dir, destination=ASSETS, original=None):
    game_dir, destination = Path(game_dir).resolve(), validate_output_directory(destination)
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
    ai_data = None
    if 'ai-rules.json' in exported:
        ai_data = (game_dir / 'Battle Aces_Data/Plugins/x86_64/aiprogram.dll').read_bytes()
        if hashlib.sha256(ai_data).hexdigest() != SUPPORTED_AI_SHA256:
            raise ValueError('AI DLL hash mismatch')
    metadata = game_dir / 'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat'
    destination.mkdir(parents=True, exist_ok=True)
    # Completion manifest is written last. A failed import remains incomplete;
    # the evidence is retained, and the next attempt needs a fresh destination.
    extraction = extract(original, metadata, destination / 'descriptors')
    for name, data in exported.items():
        (destination / name).write_bytes(data)
    shutil.copyfile(simulation, destination / 'Simulation.dll')
    if ai_data is not None: (destination / 'aiprogram.dll').write_bytes(ai_data)
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
    if ai_data is not None:
        rules = RuleBook(destination)
        if any(not set(summary['entity_ids']) <= template.catalog.keys() for summary in rules.summaries.values()):
            raise ValueError('AI rule entity is absent from exported GameConfig')
        manifest['ai_profiles'] = len(rules.rules)
        manifest['ai_dll_sha256'] = SUPPORTED_AI_SHA256
    if 'bot-catalog.json' in exported:
        bots = BotCatalog(destination, template=template, rules=rules)
        manifest['bot_profiles'] = len(bots.profiles)
        manifest['map_modes'] = [1, 2, 5]
    (destination / 'asset-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--export-dir', type=Path, required=True)
    parser.add_argument('--destination', type=Path, default=ASSETS)
    parser.add_argument('--original', type=Path)
    args = parser.parse_args(argv)
    result = import_assets(args.game_dir, args.export_dir, args.destination, args.original)
    print(json.dumps({'output': str(args.destination.resolve()), 'descriptors': result['descriptor_count'],
                      'playable_units': result['playable_units'], 'files': len(result['files'])}))


if __name__ == '__main__':
    main()
