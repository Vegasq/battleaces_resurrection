"""Own an installed recipe42 menu/Quit run for a read-only cache probe."""
from tools import sdk_expiry_owner476 as owner

owner.GAME = owner.ROOT / 'local/privacy479-game01'
owner.OUT = owner.ROOT / 'local/privacy479-cache-runtime01'
owner.EXPECTED = dict(owner.EXPECTED)
owner.EXPECTED['GameAssembly.dll'] = 'b2192dc107f0bc2c27575d9b3bf7c09265ac2a0148e28a98e33d50572cb52785'

if __name__ == '__main__':
    owner.run()
