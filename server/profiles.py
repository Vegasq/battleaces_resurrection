"""Local profile deck persistence. Paths never derive from arbitrary input."""
from __future__ import annotations

import json
from pathlib import Path
import os

try:
    from .protocol import KEY, require
except ImportError:
    from protocol import KEY, require


class ProfileStore:
    def __init__(self, path, template):
        self.path, self.template = Path(path), template
        self.path.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id):
        require(KEY.fullmatch(profile_id), "invalid profile key")
        return self.path / (profile_id + ".json")

    def load(self, profile_id, fallback):
        path = self._path(profile_id)
        if not path.exists():
            return list(fallback)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.template.validate_deck(data["deck"])
        return list(data["deck"])

    def save(self, profile_id, deck):
        self.template.validate_deck(deck)
        path = self._path(profile_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"schema": 1, "profile_id": profile_id,
                                          "deck": list(deck)}, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
