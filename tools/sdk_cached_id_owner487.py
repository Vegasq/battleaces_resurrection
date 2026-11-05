"""Own a recipe44 game for a loaded cached-device-ID getter check."""
from tools import sdk_expiry_owner476 as owner

owner.GAME = owner.ROOT / 'local/privacy487-game01'
owner.OUT = owner.ROOT / 'local/privacy487-cached-id-runtime01'
owner.EXPECTED = dict(owner.EXPECTED)
owner.EXPECTED['GameAssembly.dll'] = '8a5595e068785af102e65cbb9a6179dec226c9129b629ea9180376427d1448e9'

if __name__ == '__main__':
    owner.run()
