"""Verify the authored hardware-watchpoint control and its owned lifetime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import PE

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'local/adswatch_471000000002'
FIRST = 0x315977471
SECOND = 0x315977472


def review() -> dict:
    read = lambda name: json.loads((FOLDER/name).read_bytes())
    build, owner, ready, wrote, finished, rea = map(read,
        ('build.json','owner.json','ready.json','wrote.json','finished.json','rea-status.json'))
    source = ROOT/'tests/fixtures/ads_watch471/host.cpp'
    image = FOLDER/'WatchControl.exe'
    assert build == dict(authored_fixture=True,game_code=False,
                         source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                         exe_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    assert owner['authored_fixture'] is True and owner['game_executed'] is False
    assert owner['build'] == build and owner['passed'] is True and owner['exit_code'] == 0
    assert owner['ready'] == ready and owner['wrote'] == wrote and owner['finished'] == finished
    assert owner['launch']['pid'] == ready['pid'] and owner['launch']['tid'] == ready['tid']
    assert owner['launch']['forced_cleanup'] is False and owner['launch']['owned_process_reaped'] is True
    assert owner['tracker']['complete'] is True and owner['tracker']['final_accounting'] == \
           dict(total=2,active=0,terminated=0)
    assert wrote == dict(value=FIRST,tid=ready['tid'])
    assert finished == dict(value=SECOND,tid=ready['tid'])
    assert rea['provider']['id'] == 'frida' and rea['confidence'] == 'observed'
    assert rea['operation'] == 'frida_session_status'
    result = rea['normalized_result']
    assert result['pid'] == ready['pid'] and result['state'] == 'running'
    assert result['messages_truncated'] is False and len(result['scripts']) == 1
    assert len(result['messages']) == 2
    assert all(row['type'] == 'send' and row['script_id'] == result['scripts'][0]['script_id']
               for row in result['messages'])
    initial, hit = [row['payload'] for row in result['messages']]
    assert initial == dict(kind='watch-ready',pid=ready['pid'],tid=ready['tid'],
                           address=hex(int(ready['address'],16)),initial='0')
    assert (hit['kind'],hit['pid'],hit['tid'],hit['type'],hit['count'],hit['value']) == \
           ('watch-hit',ready['pid'],ready['tid'],'single-step',1,str(FIRST))
    image_base = int(ready['address'],16) - 0x23b28
    assert int(hit['address'],16) == image_base + 0x114f
    raw = image.read_bytes()
    pe = PE(raw)
    assert raw[pe.offset(pe.base+0x1148):pe.offset(pe.base+0x114f)] == bytes.fromhex('488905d9290200')
    displacement = struct.unpack_from('<i',raw,pe.offset(pe.base+0x114b))[0]
    assert 0x114f + displacement == 0x23b28
    assert hashlib.sha256((FOLDER/'watch.js').read_bytes()).hexdigest() == \
           '22f90cf565cc98533dab9643effff5141cb0dad7ba0bf1e6ff7e6c14a65ede5b'
    return dict(passed=True,scope='authored x64 write watchpoint and owned natural exit',
                pid=ready['pid'],tid=ready['tid'],hit_rva='0x114f',slot_rva='0x23b28',
                rea_evidence_id=rea['evidence_id'],image_sha256=build['exe_sha256'])


if __name__ == '__main__':
    print(review())
