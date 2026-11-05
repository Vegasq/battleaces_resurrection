"""Static206 asset-manager unload chain; not safe cancellation/runtime proof."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import PE, Metadata, checked_input, GAME_ASSEMBLY_SHA256, METADATA_SHA256
from tools.review_analytics_listener import parse_assembly
from tools.review_map_loading import require

ROOTS = {0x3b217e0:0x3b21914,0x3b21920:0x3b21b19,0x3b210e0:0x3b21355,
         0x137e760:0x137ece5,0x2aba6d0:0x2aba8cb,0x3b21cb0:0x3b21d10,
         0x458bf40:0x458c038,0x45987d0:0x45989a6,0x4598a80:0x4598c05,
         0x4598c10:0x4598e3d,0x4598e40:0x4599004,0x459c8e0:0x459c9ef,
         0x459c9f0:0x459ca59,0x4ceaf80:0x4ceb287}
METHODS = {1352:{0x3b217e0:'LoadSceneAsset',0x3b21920:'UnloadSceneAsset',0x3b210e0:'ReleaseBucket'},
           1350:{0x3b21cb0:'<LoadSceneAsset>g__SceneLoadFunc|0'},
           20475:{0x458bf40:'UnloadSceneAsync'},
           20508:{0x45987d0:'UnloadSceneAsync',0x4598a80:'CreateUnloadSceneWithChain',
                  0x4598c10:'CreateUnloadSceneWithChain',0x4598e40:'InternalUnloadScene'},
           20492:{0x459c8e0:'<CreateUnloadSceneWithChain>b__0'},
           20493:{0x459c9f0:'<CreateUnloadSceneWithChain>b__0'},19802:{0x4ceaf80:'Execute'}}
# Usage location -> method-spec index and exact method-definition/class/method instantiation.
SPECS = {0x6aed9a8:(235870,6107,-1,1064,'LoadAssetHelper'),
         0x6aeda08:(24804,6117,1064,-1,'RemoveScene'),
         0x6b386a8:(21284,162345,1064,-1,'get_IsRunning'),
         0x6b38880:(244864,161737,-1,1064,'CreateChainOperation'),
         0x6b38688:(244868,161736,-1,13332,'CreateChainOperation'),
         0x6b323d0:(21742,162437,1064,-1,'Release')}
ANCHORS = {0x3b21aa1:'mov r8, rbp',0x2aba7a1:'call 0x182d50600 <il2cpp+0x26a1600>',
           0x2aba832:'mov r8b, 0x1',0x4598839:'mov ecx, 0xe',
           0x4598845:'jne 0x184598957 <il2cpp+0x3ee9957>',
           0x45988de:'cmp byte ptr [rax + 0x70], 0x0',
           0x4598911:'jne 0x184598922 <il2cpp+0x3ee9922>',
           0x4ceb039:'mov esi, dword ptr [rdi + 0xa0]',
           0x4ceb066:'je 0x184ceb1ab <il2cpp+0x463c1ab>',
           0x4ceb14a:'call 0x1850834b0 <il2cpp+0x49d44b0>'}
EDGES = {0x3b218d7:0x137e760,0x3b21aa7:0x2aba6d0,0x2aba83e:0x458bf40,
         0x458c00a:0x45987d0,0x459891b:0x4598e40,0x4598927:0x4598c10,
         0x459898f:0x4598a80,0x4598bca:0x158ea00,0x4598e03:0x158f560,
         0x459c9b5:0x4598e40,0x459ca37:0x4598e40,0x4598ed2:0x4ce72d0,
         0x4ceb110:0x50ae4b0,0x4ceb252:0x2a2840}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def review(original, installed, evidence):
    original, installed, evidence = map(Path,(original,installed,evidence))
    data = checked_input(original/'GameAssembly.dll',GAME_ASSEMBLY_SHA256)
    raw_md = checked_input(original/'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat',METADATA_SHA256)
    current = (installed/'GameAssembly.dll').read_bytes()
    pe,md = PE(data),Metadata(raw_md)
    bindings=[]
    tables={}
    for index, expected in METHODS.items():
        record=md.types[index]
        im,=[im for im in md.images if im[2]<=index<im[2]+im[3]]
        image=md.string(im[0])
        methods=md.methods_for_type(record)
        if image not in tables:
            tables[image]=pe.module(image,max(m[6]&0xffffff for m in methods))
        count,table=tables[image]
        found=set()
        for m in methods:
            token=m[6]&0xffffff
            require(0<token<=count,'method token out of range')
            address,=struct.unpack_from('<Q',data,pe.offset(table+(token-1)*8,8))
            rva=address-pe.base
            if rva in expected:
                require(md.string(m[0])==expected[rva],'method binding differs')
                bindings.append(dict(type=index,name=expected[rva],token=hex(m[6]),rva=hex(rva)))
                found.add(rva)
        require(found==set(expected),'method binding missing')
    reg=struct.unpack_from('<16Q',data,pe.offset(0x186198290,128))
    specs=[]
    for location,(ix,mi,ci,fi,name) in SPECS.items():
        usage,=struct.unpack_from('<Q',data,pe.offset(pe.base+location,8))
        require(usage==((6<<29)|(ix<<1)|1),'generic usage differs')
        require(ix<reg[8],'generic index out of range')
        actual=struct.unpack_from('<3i',data,pe.offset(reg[9]+ix*12,12))
        require(actual==(mi,ci,fi) and md.string(md.methods[mi][0])==name,'generic binding differs')
        specs.append(dict(location=hex(location),index=ix,method=name,class_inst=ci,method_inst=fi))
    # The shared scene instantiation is a single SceneInstance value type.
    inst,=struct.unpack_from('<Q',data,pe.offset(reg[3]+1064*8,8))
    count,args=struct.unpack_from('<2Q',data,pe.offset(inst,16))
    require(count==1,'scene generic arity differs')
    ptr,=struct.unpack_from('<Q',data,pe.offset(args,8))
    index,bits=struct.unpack_from('<QI',data,pe.offset(ptr,12))
    require(index==19790 and (bits>>16)&255==17 and md.string(md.types[index][0])=='SceneInstance',
            'scene generic type differs')
    interface=md.methods_for_type(md.types[19823])
    require(md.string(interface[14][0])=='get_IsRunning','operation interface slot differs')
    offset=pe.offset(0x1856f8c40)
    literal=data[offset:data.index(0,offset)]
    require(literal==b'UnityEngine.SceneManagement.Scene::GetIsLoadedInternal(System.Int32)',
            'loaded-scene predicate differs')
    rows,bodies={},[]
    for start,end in ROOTS.items():
        require(pe.function_ends.get(pe.base+start)==pe.base+end,'unwind extent differs')
        raw=(evidence/f'game-{start:x}.asm').read_bytes()
        parsed=parse_assembly(raw,pe,data,start,end);rows.update(parsed)
        offset=pe.offset(pe.base+start,end-start);body=data[offset:offset+end-start]
        require(current[offset:offset+end-start]==body,'installed bytes differ')
        bodies.append(dict(start=hex(start),end=hex(end),instructions=len(parsed),
                           body_sha256=sha(body),assembly_sha256=sha(raw)))
    for address,expected in ANCHORS.items():
        require(rows[address]['text']==expected,f'semantic anchor differs at {address:x}')
    for address,target in EDGES.items():
        code=rows[address]['code']
        require(len(code)==5 and code[0]==0xe8 and address+5+struct.unpack('<i',code[1:])[0]==target,
                'direct call differs')
    return dict(passed=True,scope=__doc__,original_sha256=sha(data),metadata_sha256=sha(raw_md),
                installed_sha256=sha(current),methods=bindings,generics=specs,bodies=bodies,
                instructions=sum(b['instructions'] for b in bodies),running_unload_uses_chain=True,
                safe_cancellation_proved=False,callback_suppression_proved=False,runtime_recovery_proved=False)


PROVIDER_ROOTS = {0x4ce9f80:0x4cea58e,0x4cea590:0x4cea8af,
                  0x4cea9c0:0x4ceaa5e,0x4ceab60:0x4ceadc1,0x85c0a0:0x85c12c}
PROVIDER_ANCHORS = {
    0x4cea46d:'movzx edx, byte ptr [r15 + 0xa0]',
    0x4cea4a9:'movups xmmword ptr [r15 + 0xa8], xmm0',
    0x4cea766:'movzx edx, byte ptr [rsp + 0xb8]',
    0x4cea771:'call rax',0x4cea7b9:'mov qword ptr [r8], rbx',
    0x4ceaa10:'mov rdi, qword ptr [rbx + 0xd0]',
    0x4ceaa35:'mov eax, dword ptr [rbx + 0xd8]',
    0x4ceaa47:'lea rcx, [rbx + 0xd0]',
    0x4ceabb3:'mov rdi, qword ptr [rbx + 0xb0]',
    0x4ceabf2:'jne 0x184ceac65 <il2cpp+0x463bc65>',
    0x4ceac33:'jne 0x184cead7c <il2cpp+0x463bd7c>',
    0x4ceac5f:'je 0x184cead7c <il2cpp+0x463bd7c>',
    0x4cead51:'mov r8b, 0x1',0x4cead6a:'mov byte ptr [rsp + 0x20], 0x1',
    0x85c0e7:'subss xmm1, xmm6',0x85c0f1:'maxss xmm6, xmm7',
    0x85c11c:'comiss xmm6, xmm1',0x85c124:'seta al',
}


def review_provider(original,installed,evidence):
    """207: verify only new provider bodies; reuse pinned206 unload evidence."""
    original,installed,evidence=map(Path,(original,installed,evidence))
    prior=(evidence.parent/'loading206-assets01/verification01.json').read_bytes()
    require(sha(prior)=='ab5fa849f9bc1c9c470edd8c910413341c7d9c653e83cb34212357cc4341038b',
            'prior unload evidence differs')
    data=checked_input(original/'GameAssembly.dll',GAME_ASSEMBLY_SHA256)
    raw_md=checked_input(original/'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat',METADATA_SHA256)
    current=(installed/'GameAssembly.dll').read_bytes()
    pe,md=PE(data),Metadata(raw_md)
    record=md.types[19801]
    require(md.string(record[0])=='SceneOp','provider type differs')
    im,=[im for im in md.images if im[2]<=19801<im[2]+im[3]]
    methods=md.methods_for_type(record)
    count,table=pe.module(md.string(im[0]),max(m[6]&0xffffff for m in methods))
    expected={0x4ce9f80:'Execute',0x4cea590:'InternalLoadScene',0x4cea9c0:'Destroy',
              0x4ceab60:'UnityEngine.ResourceManagement.IUpdateReceiver.Update'}
    found=set()
    for m in methods:
        token=m[6]&0xffffff
        require(0<token<=count,'provider token out of range')
        ptr,=struct.unpack_from('<Q',data,pe.offset(table+(token-1)*8,8))
        rva=ptr-pe.base
        if rva in expected:
            require(md.string(m[0])==expected[rva],'provider method differs');found.add(rva)
    require(found==set(expected),'provider method missing')
    offsets,=struct.unpack_from('<Q',data,pe.offset(0x1869bcde0+19801*8,8))
    fields={}
    for i in range(record[18]):
        ni,=struct.unpack_from('<i',raw_md,md.header[24]+(record[8]+i)*12)
        fields[md.string(ni)]=struct.unpack_from('<i',data,pe.offset(offsets+i*4,4))[0]
    require(all(fields.get(k)==v for k,v in {'m_ActivateOnLoad':0xa0,'m_Inst':0xa8,
                'm_DepOp':0xd0,'m_ResourceManager':0xf0}.items()),'provider fields differ')
    literals={0x56f0bd8:b'UnityEngine.AsyncOperation::get_isDone()',
              0x56f0aa8:b'UnityEngine.AsyncOperation::get_allowSceneActivation()',
              0x56f0ae0:b'UnityEngine.AsyncOperation::set_allowSceneActivation(System.Boolean)'}
    for address,literal in literals.items():
        offset=pe.offset(pe.base+address,len(literal)+1)
        require(data[offset:offset+len(literal)+1]==literal+b'\0','provider icall differs')
    require(data[pe.offset(0x1864e4440,4):pe.offset(0x1864e4440,4)+4]==struct.pack('<f',0.9),
            'pre-activation threshold differs')
    reg=struct.unpack_from('<16Q',data,pe.offset(0x186198290,128))
    for location,ix,expected_spec,name in [
        (0x6b32380,21232,(162374,1064,-1),'Complete'),
        (0x6afbe80,278767,(162437,1059,-1),'Release')]:
        usage,=struct.unpack_from('<Q',data,pe.offset(pe.base+location,8))
        spec=struct.unpack_from('<3i',data,pe.offset(reg[9]+ix*12,12))
        require(usage==((6<<29)|(ix<<1)|1) and spec==expected_spec and
                md.string(md.methods[spec[0]][0])==name,'provider generic binding differs')
    rows,bodies={},[]
    for start,end in PROVIDER_ROOTS.items():
        require(pe.function_ends.get(pe.base+start)==pe.base+end,'provider unwind differs')
        raw=(evidence/f'game-{start:x}.asm').read_bytes()
        parsed=parse_assembly(raw,pe,data,start,end);rows.update(parsed)
        offset=pe.offset(pe.base+start,end-start);body=data[offset:offset+end-start]
        require(current[offset:offset+end-start]==body,'installed provider differs')
        bodies.append(dict(start=hex(start),end=hex(end),instructions=len(parsed),
                           body_sha256=sha(body),assembly_sha256=sha(raw)))
    for address,text in PROVIDER_ANCHORS.items():
        require(rows[address]['text']==text,f'provider anchor differs at {address:x}')
    for address,target in {0x4cea4a1:0x4cea590,0x4cea72d:0x50af7f0,
                           0x4ceaa4e:0x279e330,0x4ceac4b:0x5083250,
                           0x4ceac58:0x85c0a0,0x4ceac83:0x4ccd0b0,
                           0x4cead6f:0x2674290}.items():
        code=rows[address]['code']
        require(len(code)==5 and code[0]==0xe8 and address+5+struct.unpack('<i',code[1:])[0]==target,
                'provider edge differs')
    return dict(passed=True,scope='Static207 pre-activation completion/dependency destruction; no runtime proof',
                original_sha256=sha(data),metadata_sha256=sha(raw_md),installed_sha256=sha(current),
                prior_report_sha256=sha(prior),bodies=bodies,instructions=sum(b['instructions'] for b in bodies),
                completion_before_activation=True,destroy_releases_dependency=True,
                safe_cancellation_proved=False,runtime_recovery_proved=False)


QUIT_BODIES = {
    'assets-cctor': (0x3e93230, 0x3e933e9),
    'assets-wantsquit': (0x3e933f0, 0x3e934a6),
    'assets-quit': (0x3e934b0, 0x3e9352a),
    'menu-quit': (0x3d06f50, 0x3d06f95),
    'application-quit': (0x5021ad0, 0x5021b4e),
}
QUIT_METHODS = {
    ('Uncapped', 'AsyncAssetTables'): {
        0x060014f8: ('.cctor', 0x3e93230),
        0x060014f9: ('Application_wantsToQuit', 0x3e933f0),
        0x060014fa: ('Quit', 0x3e934b0)},
    ('Uncapped.UI', 'UIQuitButton'): {0x06003450: ('Quit', 0x3d06f50)},
    ('Uncapped.UI', 'UILoginFlowController'): {0x06002e5f: ('OnQuitApplication', 0x3d06f50)},
    ('UnityEngine', 'Application'): {
        0x060001a5: ('Quit', 0x5021ad0),
        0x060001c8: ('add_wantsToQuit', 0x50231a0),
        0x060001ca: ('add_quitting', 0x5023540)},
}
QUIT_ANCHORS = {
    0x3e9345d: 'c6400c01',       # WantsToQuit = true
    0x3e9346f: '837908007f07',   # LoadingCount > 0 branches past true return
    0x3e93475: 'b0014883c428c3', # true and return
    0x3e9349f: '32c04883c428c3', # false and return
    0x3e933b5: 'e886011901',     # Application.add_quitting
    0x3e933e4: 'e9b7fd1801',     # Application.add_wantsToQuit
    0x3d06f90: 'e93bab3101',     # shared UI tail call to Application.Quit()
}


def review_quit_admission(original, installed, evidence):
    """Bind retained Quit analysis to raw metadata and the installed code bodies.

    This checks byte anchors, not a new whole-function disassembly or runtime.
    Asset LoadingCount and GameServer.mapLoading are separate state variables.
    """
    original, installed, evidence = map(Path, (original, installed, evidence))
    data = checked_input(original/'GameAssembly.dll', GAME_ASSEMBLY_SHA256)
    raw_md = checked_input(original/'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat', METADATA_SHA256)
    current = (installed/'GameAssembly.dll').read_bytes()
    pe, current_pe, md = PE(data), PE(current), Metadata(raw_md)
    bindings, asset_record, asset_index = [], None, None
    for qualified, expected in QUIT_METHODS.items():
        matches = [(i, t) for i, t in enumerate(md.types)
                   if (md.string(t[1]), md.string(t[0])) == qualified]
        require(len(matches) == 1, 'quit type binding differs')
        index, record = matches[0]
        im, = [im for im in md.images if im[2] <= index < im[2]+im[3]]
        count, table = pe.module(md.string(im[0]), max(t & 0xffffff for t in expected))
        methods = {m[6]: m for m in md.methods_for_type(record)}
        for token, (name, rva) in expected.items():
            row = methods.get(token)
            require(row is not None and md.string(row[0]) == name, 'quit method binding differs')
            require(0 < token & 0xffffff <= count, 'quit token out of range')
            address, = struct.unpack_from('<Q', data, pe.offset(table+((token & 0xffffff)-1)*8, 8))
            require(address == pe.base+rva, 'quit method address differs')
            bindings.append(dict(type='.'.join(qualified), name=name, token=hex(token), rva=hex(rva)))
        if qualified == ('Uncapped', 'AsyncAssetTables'):
            asset_record, asset_index = record, index
    offsets, = struct.unpack_from('<Q', data, pe.offset(0x1869bcde0+asset_index*8, 8))
    fields = {}
    for i in range(asset_record[18]):
        ni, = struct.unpack_from('<i', raw_md, md.header[24]+(asset_record[8]+i)*12)
        fields[md.string(ni)] = struct.unpack_from('<i', data, pe.offset(offsets+i*4, 4))[0]
    require(all(fields.get(k) == v for k, v in {'LoadingHandle': 0, 'LoadingCount': 8,
                                              'WantsToQuit': 12}.items()), 'quit field offsets differ')
    prior = (evidence/'slices.json').read_bytes()
    slices, bodies = json.loads(prior), []
    for name, (start, end) in QUIT_BODIES.items():
        require(pe.function_ends.get(pe.base+start) == pe.base+end, 'quit unwind differs')
        saved = slices[name]
        saved_end = int(saved['end_rva'], 16)
        require(saved['binary_sha256'] == GAME_ASSEMBLY_SHA256 and
                int(saved['start_rva'], 16) == start and end <= saved_end <= end+16,
                'retained quit range differs')
        offset = pe.offset(pe.base+start, saved_end-start)
        require(sha(data[offset:offset+saved_end-start]) == saved['code_sha256'],
                'retained quit bytes differ')
        body = data[offset:offset+end-start]
        current_offset = current_pe.offset(current_pe.base+start, end-start)
        require(current[current_offset:current_offset+end-start] == body, 'installed quit body differs')
        bodies.append(dict(name=name, start=hex(start), end=hex(end), body_sha256=sha(body),
                           retained_assembly_sha256=sha((evidence/(name+'.asm')).read_bytes())))
    for rva, expected in QUIT_ANCHORS.items():
        code = bytes.fromhex(expected)
        offset = pe.offset(pe.base+rva, len(code))
        require(data[offset:offset+len(code)] == code, 'quit semantic anchor differs')
    return dict(passed=True, scope='Static231 retained Quit applicability; no native run',
                original_sha256=sha(data), metadata_sha256=sha(raw_md), installed_sha256=sha(current),
                prior_slices_sha256=sha(prior), bindings=bindings, asset_field_offsets=fields,
                bodies=bodies, instructions=0, byte_anchors=len(QUIT_ANCHORS),
                positive_asset_loading_count_vetoes_quit=True,
                asset_count_equals_map_loading_proved=False, safe_cancellation_proved=False,
                pending_load_quit_proved=False, runtime_recovery_proved=False)


ASSET_QUIT_BODIES = {0x1381620:0x1381a25, 0x166c650:0x166c949, 0x3e19c60:0x3e19cc8}
ASSET_QUIT_ANCHORS = {
    0x1381771:'jns 0x181381a06 <il2cpp+0xcd2a06>',
    0x138179d:'inc dword ptr [rax + 0x8]',
    0x1381959:'mov r8, qword ptr [r8 + 0x30]',
    0x13819fd:'mov r8, qword ptr [r8 + 0x40]',
    0x166c70d:'dec dword ptr [rax + 0x8]',
    0x166c71e:'cmp byte ptr [rax + 0xc], 0x0',
    0x166c722:'je 0x18166c76f <il2cpp+0xfbd76f>',
    0x166c740:'cmp dword ptr [rax + 0x8], 0x0',
    0x166c744:'jg 0x18166c76f <il2cpp+0xfbd76f>',
    0x3e19ca2:'mov rbx, qword ptr [rbx + 0x18]',
    0x3dfea37:'mov rbx, qword ptr [rbx + 0x18]',
}


def review_asset_quit_retry(original, installed, evidence):
    """Static233 genuine audio-table load and completion-driven Quit retry.

    Complete loader/callback bodies; only an explicit window of patched startup.
    Generic bindings come from the original registration/rgctx tables, not names
    guessed from shared native addresses. No callback/thread/runtime claim.
    """
    original,installed,evidence=map(Path,(original,installed,evidence))
    data=checked_input(original/'GameAssembly.dll',GAME_ASSEMBLY_SHA256)
    raw_md=checked_input(original/'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat',METADATA_SHA256)
    current=(installed/'GameAssembly.dll').read_bytes()
    require(sha(current)=='f9e14f0b45134eb96e51c4cd7c3965049ae317a64734a364e43ab8325f35d3fa',
            'qualified installed recipe23 required')
    pe,md=PE(data),Metadata(raw_md)
    reg=struct.unpack_from('<16Q',data,pe.offset(0x186198290,128))
    code=struct.unpack_from('<17Q',data,pe.offset(0x18563d9e0,136))
    bindings=[]
    for table_index,spec_index,method_index,name,pointer_index,rva in (
        (215016,235893,10672,'LoadTableInBackground',214539,0x1381620),
        (815,1075,10678,'<LoadTableInBackground>b__5_0',816,0x166c650)):
        entry=struct.unpack_from('<4i',data,pe.offset(reg[5]+table_index*16,16))
        require(entry[0]==spec_index and entry[1]==pointer_index and 0<=entry[1]<code[2],
                'asset generic pointer index differs')
        spec=struct.unpack_from('<3i',data,pe.offset(reg[9]+spec_index*12,12))
        expected=(method_index,-1,127) if table_index==215016 else (method_index,127,-1)
        require(spec==expected and md.string(md.methods[method_index][0])==name,
                'asset generic method binding differs')
        address,=struct.unpack_from('<Q',data,pe.offset(code[3]+pointer_index*8,8))
        require(address==pe.base+rva, 'asset generic method address differs')
        bindings.append(dict(name=name,table_index=table_index,spec_index=spec_index,
                             pointer_index=pointer_index,rva=hex(rva)))
    # Method-generic object sharing and the actual LargeGroupAudioTable use.
    for index,kind,type_index in ((127,28,None),(970,18,1728)):
        inst,=struct.unpack_from('<Q',data,pe.offset(reg[3]+index*8,8))
        count,args=struct.unpack_from('<QQ',data,pe.offset(inst,16))
        require(count==1, 'asset generic arity differs')
        arg,=struct.unpack_from('<Q',data,pe.offset(args,8))
        value,bits=struct.unpack_from('<QI',data,pe.offset(arg,12))
        require((bits>>16)&255==kind and (type_index is None or value==type_index),
                'asset generic type differs')
    require(md.string(md.types[1728][0])=='LargeGroupAudioTable', 'audio table type differs')
    concrete=struct.unpack_from('<3i',data,pe.offset(reg[9]+293112*12,12))
    usage,=struct.unpack_from('<Q',data,pe.offset(0x186ad8b10,8))
    require(concrete==(10672,-1,970) and usage==((6<<29)|(293112<<1)|1),
            'concrete audio load binding differs')
    # RGame module's method-generic context: load, callback and subscription.
    module=struct.unpack_from('<17Q',data,pe.offset(0x18633b500,136))
    require(md.string(next(im[0] for im in md.images if im[2]<=2194<im[2]+im[3]))=='RGame.dll',
            'asset image differs')
    ranges=[struct.unpack_from('<3I',data,pe.offset(module[9]+i*12,12)) for i in range(module[8])]
    require([r for r in ranges if r[0]==0x060014f7]==[(0x060014f7,494,10)], 'asset rgctx range differs')
    contexts=[]
    for slot,spec_index,definition,name in (
        (1,217644,(167705,-1,1097),'LoadAssetAsync'),
        (6,1068,(10678,1097,-1),'<LoadTableInBackground>b__5_0'),
        (8,21457,(162420,1097,-1),'add_Completed')):
        kind,pointer=struct.unpack_from('<QQ',data,pe.offset(module[11]+(494+slot)*16,16))
        actual,=struct.unpack_from('<I',data,pe.offset(pointer,4))
        spec=struct.unpack_from('<3i',data,pe.offset(reg[9]+spec_index*12,12))
        require(kind==3 and actual==spec_index and spec==definition and
                md.string(md.methods[spec[0]][0])==name, 'asset completion context differs')
        contexts.append(dict(slot=slot,spec_index=spec_index,method=name))
    count,table=pe.module('RGame.dll',0xdf2)
    for index,token,name,rva in ((1684,0x06000b50,'MoveNext',0x3dfe460),
                               (1833,0x06000df2,'LoadInBackground',0x3e19c60)):
        methods=[m for m in md.methods_for_type(md.types[index]) if m[6]==token]
        require(len(methods)==1 and md.string(methods[0][0])==name, 'audio loader method token differs')
        address,=struct.unpack_from('<Q',data,pe.offset(table+((token&0xffffff)-1)*8,8))
        require(address==pe.base+rva, 'audio loader method address differs')
    record=md.types[1833]
    require(md.string(record[0])=='RGameRequiredTables', 'required tables type differs')
    offsets,=struct.unpack_from('<Q',data,pe.offset(0x1869bcde0+1833*8,8))
    fields={md.string(struct.unpack_from('<i',raw_md,md.header[24]+(record[8]+i)*12)[0]):
            struct.unpack_from('<i',data,pe.offset(offsets+i*4,4))[0] for i in range(record[18])}
    require(fields['LargeGroupAudioTable']==0x18, 'audio table field differs')
    rows,bodies={},[]
    windows=ASSET_QUIT_BODIES | {0x3dfe9f8:0x3dfea5f}
    for start,end in windows.items():
        whole=start in ASSET_QUIT_BODIES
        if whole:require(pe.function_ends.get(pe.base+start)==pe.base+end, 'asset quit unwind differs')
        raw=(evidence/f'game-{start:x}.asm').read_bytes()
        parsed=parse_assembly(raw,pe,data,start,end);rows.update(parsed)
        offset=pe.offset(pe.base+start,end-start);body=data[offset:offset+end-start]
        require(current[offset:offset+end-start]==body, 'installed asset quit body/window differs')
        bodies.append(dict(start=hex(start),end=hex(end),full_body=whole,instructions=len(parsed),
                           body_sha256=sha(body),assembly_sha256=sha(raw)))
    for address,expected in ASSET_QUIT_ANCHORS.items():
        require(rows[address]['text']==expected, 'asset quit semantic anchor differs')
    for address,target in {0x166c76a:0x5021ad0,0x13817c8:0x789d0,
                           0x1381a01:0x279ca00,0x3e19cc3:0x1381620,0x3dfea5a:0x1381620}.items():
        raw=rows[address]['code']
        require(len(raw)==5 and raw[0] in (0xe8,0xe9) and
                address+5+struct.unpack('<i',raw[1:])[0]==target, 'asset quit edge differs')
    return dict(passed=True,scope='Static233 asset completion retries requested Quit; no native execution',
                original_sha256=sha(data),metadata_sha256=sha(raw_md),installed_sha256=sha(current),
                generic_bindings=bindings,completion_contexts=contexts,bodies=bodies,
                instructions=sum(b['instructions'] for b in bodies),
                counter_increment_on_new_load=True,completion_decrements_counter=True,
                retry_requires_wants_to_quit_and_nonpositive_count=True,
                concrete_background_load='LargeGroupAudioTable',
                startup_whole_body_unchanged=False,positive_counter_runtime_recovery_proved=False,
                safe_cancellation_proved=False,hung_engine_recovery_proved=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('original','installed','evidence','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--provider-only',action='store_true')
    mode.add_argument('--quit-admission',action='store_true')
    mode.add_argument('--asset-quit-retry',action='store_true')
    args=parser.parse_args()
    reviewer = review_asset_quit_retry if args.asset_quit_retry else review_quit_admission if args.quit_admission else review_provider if args.provider_only else review
    result=reviewer(args.original,args.installed,args.evidence)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'passed':True,'instructions':result['instructions'],'bodies':len(result['bodies'])}))
