"""Verify completeness and accidental changes in a locally imported asset bundle."""
import hashlib
import json
from pathlib import Path, PurePosixPath
from .protocol import BUILD_SHA, SIM_SHA
from .ai_rules import RuleBook, SUPPORTED_AI_SHA256
from .bot_catalog import BotCatalog
from .game_data import GameTemplate
from .cosmetics import CosmeticCatalog


ASSET_FAILURES = {
    'missing_manifest': 'Asset manifest is missing. Check assets_directory or import assets into a fresh directory.',
    'unreadable_manifest': 'Asset manifest cannot be read. Check file access and retry after other file operations finish.',
    'invalid_manifest': 'Asset manifest is damaged or malformed. Restore a verified asset bundle or import into a fresh directory.',
    'unsupported_manifest': 'Asset manifest format or game build is unsupported. Use build37822 assets and matching server tools.',
    'build_mismatch': 'Asset build hashes do not match this server. Use matching build37822 assets.',
    'incomplete_manifest': 'Asset manifest is incomplete. Restore a verified asset bundle or import into a fresh directory.',
    'unsafe_path': 'Asset manifest contains an invalid file path. Restore a verified asset bundle.',
    'missing_asset': 'A declared asset file is missing. Restore a verified asset bundle or import into a fresh directory.',
    'unreadable_asset': 'An asset file cannot be read. Check file access and retry after other file operations finish.',
    'content_mismatch': 'Asset content does not match its manifest. Restore a verified asset bundle; do not edit its hashes.',
    'simulation_mismatch': 'Simulation DLL does not match this server. Use matching build37822 assets.',
}


class AssetError(ValueError):
    """Authored category only; never includes manifest values or OS paths."""
    def __init__(self, code):
        self.code = code
        super().__init__(ASSET_FAILURES[code])


def _manifest_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise AssetError('invalid_manifest')
        result[key] = value
    return result


def verify_assets(directory):
    directory = Path(directory).resolve()
    try:
        manifest = json.loads((directory / 'asset-manifest.json').read_text(encoding='utf-8'),
                              object_pairs_hook=_manifest_pairs)
    except FileNotFoundError:
        raise AssetError('missing_manifest') from None
    except OSError:
        raise AssetError('unreadable_manifest') from None
    except (ValueError, UnicodeError, RecursionError):
        raise AssetError('invalid_manifest') from None
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict):
        raise AssetError('invalid_manifest')
    if (any(type(manifest.get(key)) is not int for key in ('schema', 'game_build', 'asset_format')) or
            (manifest.get('schema'), manifest.get('game_build'), manifest.get('asset_format')) != (1, 37822, 1)):
        raise AssetError('unsupported_manifest')
    if manifest.get('original_gameassembly_sha256') != BUILD_SHA or manifest.get('simulation_sha256') != SIM_SHA:
        raise AssetError('build_mismatch')
    files = manifest['files']
    required = {'Simulation.dll', 'map-1v1.pb.gz', 'unit-catalog.json', 'descriptors/game_pb.proto.json'}
    if not required <= files.keys():
        raise AssetError('incomplete_manifest')
    # Validate the entire inventory before opening any declared file.
    for name, expected in files.items():
        path = PurePosixPath(name)
        if not path.parts or path.is_absolute() or '..' in path.parts or any(c in name for c in ('\\', ':', '\0')):
            raise AssetError('unsafe_path')
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
            raise AssetError('invalid_manifest')
    for name, expected in files.items():
        try:
            target = (directory / name).resolve()
        except (OSError, RuntimeError):
            raise AssetError('unreadable_asset') from None
        if not target.is_relative_to(directory):
            raise AssetError('unsafe_path')
        try:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except FileNotFoundError:
            raise AssetError('missing_asset') from None
        except OSError:
            raise AssetError('unreadable_asset') from None
        if actual != expected:
            raise AssetError('content_mismatch')
    if files['Simulation.dll'] != SIM_SHA:
        raise AssetError('simulation_mismatch')
    cosmetics = None
    if 'cosmetic-catalog.json' in files or 'cosmetic_items' in manifest or 'cosmetic_slots' in manifest:
        if 'cosmetic-catalog.json' not in files:
            raise ValueError('Incomplete cosmetic asset inventory')
        cosmetics = CosmeticCatalog(directory)
        if (cosmetics.sha256 != files['cosmetic-catalog.json'] or
                type(manifest.get('cosmetic_items')) is not int or manifest['cosmetic_items'] != len(cosmetics.items) or
                type(manifest.get('cosmetic_slots')) is not int or manifest['cosmetic_slots'] != len(cosmetics.slots)):
            raise ValueError('Cosmetic catalog count/hash mismatch')
    if 'ai-rules.json' in files or 'ai_dll_sha256' in manifest or 'aiprogram.dll' in files:
        if files.get('aiprogram.dll') != SUPPORTED_AI_SHA256 or manifest.get('ai_dll_sha256') != SUPPORTED_AI_SHA256:
            raise ValueError('AI DLL mismatch or incomplete AI assets')
        rules = RuleBook(directory)
        if manifest.get('ai_profiles') != len(rules.rules) or not rules.files.keys() <= files.keys():
            raise ValueError('Incomplete AI rule inventory')
        if any(hashlib.sha256(data).hexdigest() != files[name] for name, data in rules.files.items()):
            raise ValueError('AI files changed during asset verification')
    bot_files = {'bot-catalog.json', 'map-2v2.pb.gz', 'map-2vai.pb.gz'}
    if bot_files & files.keys() or 'bot_profiles' in manifest or 'map_modes' in manifest:
        if not bot_files | {'ai-rules.json'} <= files.keys() or manifest.get('map_modes') != [1, 2, 5]:
            raise ValueError('Incomplete bot/team asset inventory')
        templates = {}
        for name, mode in (('map-1v1.pb.gz', 1), ('map-2v2.pb.gz', 2), ('map-2vai.pb.gz', 5)):
            templates[mode] = GameTemplate.load(directory/name, catalog_path=directory/'unit-catalog.json',
                                                 descriptors_path=directory/'descriptors')
            if templates[mode].game_mode != mode:
                raise ValueError('Asset map mode mismatch')
        bots = BotCatalog(directory, template=templates[1], rules=rules)
        if manifest.get('bot_profiles') != len(bots.profiles) or hashlib.sha256(bots.raw).hexdigest() != files['bot-catalog.json']:
            raise ValueError('Bot catalog count/hash mismatch')
        if cosmetics and (bots.cosmetic_ids != cosmetics.items.keys() or
                not set(bots.portraits) <= cosmetics.slots[cosmetics.roles['portrait']].compatible_items or
                not set(bots.banners) <= cosmetics.slots[cosmetics.roles['banner']].compatible_items):
            raise ValueError('Bot and cosmetic catalogs disagree')
        for template in templates.values():
            for _, decks in bots.profiles.values():
                for deck in decks: template.validate_deck(deck.units)
    return manifest
