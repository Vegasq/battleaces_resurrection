"""Own an installed recipe47 client for a loaded Unity post-entry probe."""
from tools import sdk_expiry_owner476 as owner

owner.GAME = owner.ROOT / 'local/privacy512-game01'
owner.OUT = owner.ROOT / 'local/privacy513-postprobe01'
owner.EXPECTED = {
    'Battle Aces.exe': '0ae4c67586e0aced96641e8e06c0b845d2d6d77c0cfb5b7533b9afee89eb77f6',
    'GameAssembly.dll': '99ffb3f723ccb6f48e89eb8f3cff3ed1675978cfec092be19b8f4d06ee5edb6e',
    'UnityPlayer.dll': '935c78e7a1b7fae3f0bc6892e390d521e5d24cf40539112559d64312df6107e4',
    'BattleAcesOffline.dll': '549136ce31ec01d216678dc484d3852ba7e93bdee5333d4b500c601499095993',
}

if __name__ == '__main__':
    owner.run()
