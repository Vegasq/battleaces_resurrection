"""Own an installed recipe43 menu/Quit for a read-only JSON-reader probe."""
from tools import sdk_expiry_owner476 as owner

owner.GAME = owner.ROOT / 'local/privacy482-game01'
owner.OUT = owner.ROOT / 'local/privacy483-json-runtime01'
owner.EXPECTED = dict(owner.EXPECTED)
owner.EXPECTED['GameAssembly.dll'] = '9224d2c64dd4a2602f61955b5c32629850d254e226c1dcbeb07db3bcd3c63d50'

if __name__ == '__main__':
    owner.run()
