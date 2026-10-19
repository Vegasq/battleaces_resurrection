"""Authored, bounded codec fault inputs. Contains no client bytes or recording."""
import hashlib
from pathlib import Path
import zlib
from server.protobuf_wire import encode_varint

LIMIT=16*1024*1024
CASES=('invalid-deflate','invalid-wire','truncated-field','recursion-limit','size-limit','empty-recording')


def payloads():
    def compressed(raw):
        writer=zlib.compressobj(9,wbits=-zlib.MAX_WBITS)
        return writer.compress(raw)+writer.flush()
    # The recursive group and blob are otherwise complete wire encodings; their
    # limits, rather than a truncation elsewhere, must stop the original parser.
    sources={'invalid-wire':b'\x0f','truncated-field':b'\x0a\x01',
             'recursion-limit':b'\x7b'*66+b'\x7c'*66,
             'size-limit':b'\x7a'+encode_varint(LIMIT+1)+bytes(LIMIT+1),
             'empty-recording':b''}
    return {'invalid-deflate':b'\x07'}|{case:compressed(raw) for case,raw in sources.items()}


def prepare(folder,owned_root):
    folder=Path(folder).resolve();owned_root=Path(owned_root).resolve()
    if not (folder.is_relative_to(owned_root) and folder.name=='AutoSaveReplays' and
            folder.parent.name.startswith('nativestest_packaged_') and not folder.exists()):
        raise AssertionError('codec fixtures require a fresh owned packaged profile')
    folder.mkdir(parents=True,exist_ok=False)
    files={}
    for case,raw in payloads().items():
        assert 0<len(raw)<=64*1024
        name='authored-codec-'+case+'.case'
        with (folder/name).open('xb') as stream:stream.write(raw)
        files[name]=dict(case=case,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    return dict(authored=True,game_bytes=False,files=files,size_limit=LIMIT,recursion_limit=64)


def verify(folder,fixture):
    for name,expected in fixture['files'].items():
        path=Path(folder)/name
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise AssertionError('codec fixture changed type')
        raw=path.read_bytes()
        if len(raw)!=expected['bytes'] or hashlib.sha256(raw).hexdigest()!=expected['sha256']:
            raise AssertionError('codec fixture changed bytes')
    return dict(files=len(fixture['files']),all_bytes_unchanged=True)
