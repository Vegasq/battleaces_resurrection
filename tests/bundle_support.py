"""Small authored catalog/bundle inputs; no shipped game data."""
import base64
import hashlib
import json
from types import SimpleNamespace
from pathlib import Path

from client_patch.patcher import bundle_loading


class AuthoredBundles:
    def __init__(self, root):
        self.root = Path(root)
        self.content = {'1' * 32 + '.bundle': b'authored local bundle one',
                        '2' * 32 + '.bundle': b'authored local bundle two'}
        originals, patched = [], []
        for name, data in self.content.items():
            text = ('{"m_Hash":"' + name[:-7] + '","m_BundleName":"authored",'
                    '"m_Crc":123,"m_BundleSize":' + str(len(data)) + ',"m_UseUWRForLocalBundles":false}')
            originals.append(text.encode('utf-16-le'))
            patched.append(text.replace('"m_Crc":123', '"m_Crc":0  ').encode('utf-16-le'))
        before = b'authored prefix' + b'!'.join(originals) + b'authored suffix'
        after = b'authored prefix' + b'!'.join(patched) + b'authored suffix'
        self.original = json.dumps(dict(m_ExtraDataString=base64.b64encode(before).decode('ascii'),
                                        retained='authored unrelated value'), separators=(',', ':')).encode()
        self.patched = self.original.replace(base64.b64encode(before), base64.b64encode(after))
        self.build = SimpleNamespace(CATALOG_SHA256=hashlib.sha256(self.original).hexdigest(),
                                     CATALOG_PATCHED_SHA256=hashlib.sha256(self.patched).hexdigest(),
                                     BUNDLES={name: (len(data), hashlib.sha256(data).hexdigest())
                                              for name, data in self.content.items()})
        self.catalog = self.root / bundle_loading.CATALOG
        self.catalog.parent.mkdir(parents=True, exist_ok=True)
        self.catalog.write_bytes(self.original)
        for name, data in self.content.items():
            path = self.root / bundle_loading.BUNDLE_DIR / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
