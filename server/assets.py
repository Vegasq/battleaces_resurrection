"""Verify completeness and accidental changes in a locally imported asset bundle."""
import hashlib
import json
from pathlib import Path, PurePosixPath
from .protocol import BUILD_SHA, SIM_SHA
from .ai_rules import RuleBook, SUPPORTED_AI_SHA256


def verify_assets(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'asset-manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('schema'), manifest.get('game_build'), manifest.get('asset_format')) != (1, 37822, 1):
        raise ValueError('Unsupported asset manifest')
    if manifest.get('original_gameassembly_sha256') != BUILD_SHA or manifest.get('simulation_sha256') != SIM_SHA:
        raise ValueError('Asset build mismatch')
    files = manifest.get('files', {})
    required = {'Simulation.dll', 'map-1v1.pb.gz', 'unit-catalog.json', 'descriptors/game_pb.proto.json'}
    if not required <= files.keys():
        raise ValueError('Incomplete asset manifest')
    for name, expected in files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe manifest path')
        target = (directory / name).resolve()
        if not target.is_relative_to(directory):
            raise ValueError('Asset path escapes bundle')
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError('Asset content mismatch: ' + name)
    if files['Simulation.dll'] != SIM_SHA:
        raise ValueError('Simulation DLL mismatch')
    if 'ai-rules.json' in files or 'ai_dll_sha256' in manifest or 'aiprogram.dll' in files:
        if files.get('aiprogram.dll') != SUPPORTED_AI_SHA256 or manifest.get('ai_dll_sha256') != SUPPORTED_AI_SHA256:
            raise ValueError('AI DLL mismatch or incomplete AI assets')
        rules = RuleBook(directory)
        if manifest.get('ai_profiles') != len(rules.rules) or not rules.files.keys() <= files.keys():
            raise ValueError('Incomplete AI rule inventory')
        if any(hashlib.sha256(data).hexdigest() != files[name] for name, data in rules.files.items()):
            raise ValueError('AI files changed during asset verification')
    return manifest
