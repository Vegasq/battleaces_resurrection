"""Offline strict nested Pathing-child capture qualification. No native execution."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from tools import summarize_native_systems as common

require, integer, stats = common.require, common.integer, common.stats
PARENT_RESIDUAL = 'Pathing parent minus sequential measured children and final pass: unmeasured stubs, dispatch, other parent work and observer overhead.'
STEP_RESIDUAL = 'STEP minus Pathing parent: other native systems, dispatch and observer overhead. Child scopes already belong to parent; never add twice.'


def pointer(value):
    require(isinstance(value,str) and re.fullmatch(r'0x[0-9a-f]+',value) is not None, 'invalid pointer/RVA')
    return int(value,16)


def validate_capture(bundle,evidence_id,session_id,config,script_sha,script_path,expected_count=1562,timestep=50):
    payloads=common.capture_envelope(bundle,evidence_id,session_id,config,script_sha,script_path,expected_count,
                                    schema=2,sensor_kind='pathing-children-v1')
    armed,inv,complete=(payloads[i]['data'] for i in (0,1,-1))
    require(armed['world']==config['world']==inv['world'] and armed['moduleBase']==inv['moduleBase']
            and armed['expectedFrames']==config['expected_frames']==expected_count
            and armed['byteChecks']==len(config['byte_checks']), 'armed world/config differs')
    require(integer(inv['ticksPerSecond'],1) and inv['ticksPerSecond']*120<=2**53-1
            and inv['ticksPerSecond']==armed['ticksPerSecond'] and inv['unit']=='QPC ticks', 'QPC budget/units differ')
    require(integer(inv['moduleSize'],1) and inv['systemCount']==41 and len(inv['systems'])==41, 'exact41 system vector differs')
    for start,end,count in [('systemVectorBegin','systemVectorEnd',41),('childVectorBegin','childVectorEnd',len(inv['children']))]:
        require(pointer(inv[start])>0 and pointer(inv[end])-pointer(inv[start])==8*count,'vector bounds/stride differ')
    require(inv['parentReturnRva']=='0x346d8' and inv['childReturnRva']=='0xf97a9' and inv['finalReturnRva']=='0xf97c8'
            and inv['finalPassRva']=='0xf8f40' and inv['expectedSubpasses']==2
            and inv['cellLayout']==['observedCount','inclusiveTicksOrNull'], 'constant caller/layout differs')
    objects=set()
    for i,system in enumerate(inv['systems']):
        require(integer(system['index']) and system['index']==i and pointer(system['object'])>0
                and system['object'] not in objects,'system index/object differs')
        objects.add(system['object'])
        for field in ('vtableRva','updateRva','checksumRva'):pointer(system[field])
    parent=inv['pathing']
    require(parent==inv['systems'][23] and parent['vtableRva']=='0x391280' and parent['updateRva']=='0xf9540'
            and parent['type']=='.?AVSystemPathing@Uncapped@@','exact Pathing parent differs')
    children=inv['children'];require(1<=len(children)<=64,'child vector outside bound')
    objects=set()
    classes={}
    for i,child in enumerate(children):
        require(integer(child['index']) and child['index']==i and pointer(child['object'])>0 and child['object'] not in objects,'child object/index duplicate')
        objects.add(child['object'])
        pointer(child['vtableRva']);rva=pointer(child['updateRva'])
        require(rva not in (0x14180,0x13890),'child outside capture boundary')
        require(isinstance(child['type'],str) and child['type'].startswith('.?AV'),'unknown child RTTI')
        entry=child['updateEntryHex'];require(isinstance(entry,str) and re.fullmatch('[0-9a-f]{6}',entry),'invalid child entry bytes')
        trivial=entry.startswith('c3') or entry in ('c20000','33c0c3','31c0c3')
        require(type(child['updateTimed']) is bool and child['updateTimed'] is not trivial
                and type(child['expectedTimedCallsPerPositiveStep']) is int
                and child['expectedTimedCallsPerPositiveStep']==(0 if trivial else 2)
                and child['reason']==('exact immediate-return/return-zero leaf; no hook/count observation' if trivial else None),'child exclusion/count classification differs')
        classification=(entry,child['updateTimed'],child['reason'])
        require(rva not in classes or classes[rva]==classification,'shared target classification differs');classes[rva]=classification
    for name in ('parentEntryHex','finalPassEntryHex'):
        entry=inv[name];require(isinstance(entry,str) and re.fullmatch('[0-9a-f]{6}',entry)
            and not (entry.startswith('c3') or entry in ('c20000','33c0c3','31c0c3')),'parent/final must be nontrivial')
    require(complete['frames']==complete['expectedFrames']==expected_count and complete['failed'] is False
            and complete['systemCount']==41 and complete['childCount']==len(children)
            and complete['capturedThrough']==expected_count-1,'completion counts/failure differ')
    frames=[];tid=None
    def cell(value,count,timed):
        require(isinstance(value,list) and len(value)==2 and integer(value[0]) and value[0]==count,'missing/extra observed dispatch')
        require(integer(value[1]) if timed else value[1] is None,'excluded/nonfinite elapsed')
        if timed:
            require(value[1]<=inv['ticksPerSecond']*120 and (count>0 or value[1]==0),'elapsed budget/disabled role differs')
        return value[1] or 0
    for chunk in payloads[2:-1]:
        chunk=chunk['data']
        require(set(chunk)=={'start','rows'} and chunk['start']==len(frames)
                and len(chunk['rows'])==min(60,expected_count-len(frames)),'chunk count/ordering differs')
        for row in chunk['rows']:
            require(set(row)=={'frame','tid','dt','pathing','children','finalPass','stepTicks','returnCode','countsValid','budgetValid'},'frame schema differs')
            require(integer(row['frame']) and row['frame']==len(frames) and integer(row['dt']) and row['dt']==timestep
                    and integer(row['tid'],1),'frame/dt/thread differs')
            tid=row['tid'] if tid is None else tid
            require(row['tid']==tid and row['countsValid'] is True and row['budgetValid'] is True
                    and type(row['returnCode']) is int and row['returnCode']==0,'native return/count/budget/thread failure')
            require(integer(row['stepTicks']) and row['stepTicks']<=inv['ticksPerSecond']*120
                    and len(row['children'])==len(children),'STEP budget/child coverage differs')
            count=int(row['dt']>0);parent_ticks=cell(row['pathing'],count,True);final_ticks=cell(row['finalPass'],count,True)
            child_ticks=sum(cell(c,count*2 if m['updateTimed'] else 0,m['updateTimed']) for c,m in zip(row['children'],children))
            require(child_ticks+final_ticks<=parent_ticks<=row['stepTicks'],'nested timing nonconservation')
            frames.append(row)
    require(len(frames)==expected_count,'frame coverage differs')
    return inv,frames


def validate_image(inv,config,raw):
    pe=common.PE(raw);require(pe.size==inv['moduleSize'],'module size differs')
    required={0x14180,0xf9540,0xf8f40}
    for check in config['byte_checks']:
        require(integer(check['rva']) and re.fullmatch(r'(?:[0-9a-f]{2}){3,}',check['hex']) is not None
                and pe.at(check['rva'],len(check['hex'])//2).hex()==check['hex'],'exact image guard differs')
        required.discard(check['rva'])
    require(not required,'required STEP/parent/final byte check missing')
    for rva,hexbytes in ((0x346d8,'8b0e488b01ff5008'),(0xf97a9,'6f4889457741ffd0'),(0xf97c8,'488bcee878f7ffff')):
        require(pe.at(rva-8,8).hex()==hexbytes,'exact constant caller instruction differs')
    for system in inv['systems']:
        table=pointer(system['vtableRva'])
        for role,offset in [('update',8),('checksum',16)]:
            require(struct.unpack('<Q',pe.at(table+offset,8))[0]==pe.base+pointer(system[role+'Rva']),'changed system method/vtable')
    for method,rva in [('parentEntryHex',0xf9540),('finalPassEntryHex',0xf8f40)]:
        require(pe.at(rva,3).hex()==inv[method],'parent/final original bytes differ')
    def typename(table):
        locator=struct.unpack('<Q',pe.at(table-8,8))[0]-pe.base
        require(struct.unpack('<I',pe.at(locator,4))[0]==1,'RTTI locator differs')
        descriptor=struct.unpack('<I',pe.at(locator+12,4))[0];chars=bytearray()
        for i in range(256):
            char=pe.at(descriptor+16+i,1)
            if char==b'\0':return chars.decode('ascii')
            chars.extend(char)
        raise ValueError('unbounded RTTI')
    require(typename(0x391280)==inv['pathing']['type'],'parent RTTI differs')
    for child in inv['children']:
        table=pointer(child['vtableRva']);rva=pointer(child['updateRva'])
        require(struct.unpack('<Q',pe.at(table+8,8))[0]==pe.base+rva and pe.at(rva,3).hex()==child['updateEntryHex']
                and typename(table)==child['type'],'unknown/changed child vtable/RTTI/method')


def summarize(capture,control,evidence_id,session_id):
    ctx=common.bound_replay(capture,control)
    read,document,bindings,launch,ready,rows,controls=(ctx[k] for k in ('read','document','bindings','launch','ready','rows','controls'))
    script=read(capture/'sensor.js');match=re.search(rb'const config = (\{[^\r\n]+\});',script)
    require(match is not None,'sensor config absent');config=common.strict_json(match[1]);script_sha=hashlib.sha256(script).hexdigest()
    require(config['pid']==ready['pid'] and config['nonce']==ready['nonce'] and config['image']==ready['image']
            and config['dll']==ready['dll'] and config['world']==ready['world_hex'],'sensor/gate identity differs')
    inv,frames=validate_capture(document(capture/'rea-evidence.json'),evidence_id,session_id,config,script_sha,capture/'sensor.js')
    validate_image(inv,config,read(Path(launch['dll'])))
    factor=1000/inv['ticksPerSecond'];perframe=[];phases={}
    for native,actual in zip(frames,rows):
        child_ticks=sum(c[1] or 0 for c in native['children']);parent=native['pathing'][1];final=native['finalPass'][1]
        perframe.append(dict(frame=native['frame'],phase=actual['phase'],step_ms=native['stepTicks']*factor,parent_ms=parent*factor,
            final_ms=final*factor,parent_residual_ms=(parent-final-child_ticks)*factor,step_residual_ms=(native['stepTicks']-parent)*factor,
            child_ms=[c[1]*factor if c[1] is not None else None for c in native['children']]))
    for phase in common.v.c.PHASES:
        selected=[r for r in perframe if r['phase']==phase];ranked=[]
        summary={name:stats([r[name] for r in selected]) for name in ('step_ms','parent_ms','final_ms','parent_residual_ms','step_residual_ms')}
        for i,child in enumerate(inv['children']):
            if child['updateTimed']:
                timing=stats([r['child_ms'][i] for r in selected]);ranked.append(dict(index=i,type=child['type'],rva=child['updateRva'],timings_ms=timing,
                    fraction_parent_mean=timing['mean']/summary['parent_ms']['mean'] if summary['parent_ms']['mean'] else None))
        instrumented=stats([r['step_rpc_ms'] for r in rows if r['phase']==phase]);ordinary=stats([r['step_rpc_ms'] for r in controls if r['phase']==phase])
        phases[phase]=dict(frames=len(selected),**summary,ranked_children=sorted(ranked,key=lambda r:r['timings_ms']['mean'],reverse=True),
            top5percent_parent_frames=sorted(selected,key=lambda r:r['parent_ms'],reverse=True)[:max(1,math.ceil(len(selected)*.05))],
            observer_comparison=dict(instrumented_rpc_ms=instrumented,control_rpc_ms=ordinary,
                mean_delta_ms=instrumented['mean']-ordinary['mean'],p95_delta_ms=instrumented['p95']-ordinary['p95']))
    for name in ('tools/summarize_native_systems.py','tests/test_summarize_native_systems.py','tools/summarize_pathing_children.py','tests/test_summarize_pathing_children.py'):read(common.ROOT/name)
    for path,digest in bindings.items():require(common.helper.sha(path)==digest,'bound evidence changed')
    return dict(schema=2,sensor_kind='pathing-children-v1',passed=True,instrumentation_qualified=True,helper_replay_qualified=True,
        evidence_id=evidence_id,session_id=session_id,sensor_source_sha256=script_sha,evidence_sha256=bindings,helper_sources=ctx['source'],
        inventory=inv,phases=phases,frames=perframe,parent_residual_scope=PARENT_RESIDUAL,step_residual_scope=STEP_RESIDUAL,
        limitations=['One instrumented Windows replay and one ordinary control; no repeated performance or20Hz acceptance.',
            'Inclusive wall scopes contain internal work/waits; no CPU stack, wait reason or Linux timing inference.',
            'RPC delta mixes observer costs with uncontrolled frequency/scheduling/contention; not isolated instrumentation overhead.',
            'Unhooked trivial children have observed count0 and elapsed null; no actual dispatch count or zero cost is inferred.',
            'Child timings are nested in parent; parent is nested in STEP. Sum only children+final+parent residual, or parent+STEP residual.'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('capture','control','output'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('evidence-id','session-id'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv);output=common.helper.fresh_output(args.output)
    result=summarize(args.capture.resolve(),args.control.resolve(),args.evidence_id,args.session_id)
    output.mkdir(parents=True,exist_ok=False);common.helper.write_new(output/'summary.json',result)
    text=['Pathing children qualified. '+PARENT_RESIDUAL,STEP_RESIDUAL]
    for phase,p in result['phases'].items():
        text.append(f"{phase}: parent={p['parent_ms']['mean']:.3f}ms, final={p['final_ms']['mean']:.3f}ms, parent residual={p['parent_residual_ms']['mean']:.3f}ms; STEP residual={p['step_residual_ms']['mean']:.3f}ms")
        text.extend(f"  {r['type']} {r['rva']}: mean={r['timings_ms']['mean']:.3f}ms, p95={r['timings_ms']['p95']:.3f}ms, parent share={r['fraction_parent_mean']:.3%}" for r in p['ranked_children'])
    text.extend(result['limitations']);(output/'summary.txt').write_text('\n'.join(text)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,output=str(output),summary_sha256=common.helper.sha(output/'summary.json'))));return 0


if __name__=='__main__':raise SystemExit(main())
