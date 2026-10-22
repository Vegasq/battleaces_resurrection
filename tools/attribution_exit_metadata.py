"""Validate a self-TerminateProcess ENTRY;OS completion is separate evidence."""
import re
from tools.frida_attribution_exit import EXIT_APIS, EXIT_HOLD_MS
from tools.frida_cache_startup import OBSERVED


def validate_cache(value):
    if not isinstance(value,dict) or set(value)!={'installed','calls','gcHandles','counts'} or \
            type(value['installed']) is not bool or \
            any(type(value[k]) is not int or not 0<=value[k]<=64 for k in ('calls','gcHandles')) or \
            value['gcHandles']>value['calls'] or not isinstance(value['counts'],dict) or \
            set(value['counts'])!=OBSERVED or \
            any(type(v) is not int or not 0<=v<=64 for v in value['counts'].values()):
        raise ValueError('Invalid typed SDK snapshot')
    return value


def validate(data, *, expected_status, expected_caller=None, cache=None):
    keys={'exitStatus','counts','installed','errors','unknownRelativeRoots','resolvedCwdRoots',
          'overflow','boundaryApi','currentProcessPseudoHandle','transportHoldMs','frames'}
    if cache is not None:keys.add('cache')
    if not isinstance(data,dict) or set(data)!=keys:raise ValueError('Exit snapshot keys differ')
    if type(expected_status) is not int or not 0<=expected_status<2**32 or \
            type(data['exitStatus']) is not int or data['exitStatus']!=expected_status:
        raise ValueError('Exit status differs')
    if data['boundaryApi'] not in EXIT_APIS or data['currentProcessPseudoHandle'] is not True or \
            type(data['transportHoldMs']) is not int or data['transportHoldMs']!=EXIT_HOLD_MS:
        raise ValueError('Unsupported terminal boundary')
    if data['errors']!=[] or data['overflow'] is not False or \
            any(type(data[k]) is not int or data[k]<0 for k in ('unknownRelativeRoots','resolvedCwdRoots')):
        raise ValueError('Incomplete exit metadata')
    counts=data['counts'];installed=data['installed']
    if not isinstance(counts,dict) or not isinstance(installed,list) or \
            any(not isinstance(h,dict) or set(h) not in ({'key'},{'key','aliasOf'}) or
                not isinstance(h['key'],str) for h in installed):
        raise ValueError('Invalid exit counters/hooks')
    names=[h['key'] for h in installed]
    if len(names)!=len(set(names)) or not set(counts)<=set(names) or \
            any(type(v) is not int or not 0<=v<=2**53-1 for v in counts.values()) or \
            type(counts.get(data['boundaryApi'])) is not int or counts[data['boundaryApi']]<1:
        raise ValueError('Uninstalled/missing terminal counter')
    aliases=set()
    for i,h in enumerate(installed):
        if 'aliasOf' not in h:continue
        target=h['aliasOf']
        if not isinstance(target,str) or target not in names[:i] or target in aliases or \
                target.split(':',1)[-1]!=h['key'].split(':',1)[-1] or h['key'] in counts:
            raise ValueError('Invalid hook alias provenance')
        aliases.add(h['key'])
    frames=data['frames']
    if not isinstance(frames,list) or not 1<=len(frames)<=8:raise ValueError('Missing exit caller')
    for f in frames:
        if not isinstance(f,dict) or set(f)!={'module','rva'}:raise ValueError('Exit caller keys differ')
        if f==dict(module=None,rva=None):continue
        if not isinstance(f['module'],str) or not 1<=len(f['module'])<=256 or \
                f['module']!=f['module'].lower() or any(c in f['module'] for c in ('/','\\','\0')) or \
                not isinstance(f['rva'],str) or not re.fullmatch('0x[0-9a-f]{1,16}',f['rva']):
            raise ValueError('Invalid exit caller')
    if expected_caller is not None and expected_caller not in frames:raise ValueError('Exit route differs')
    if cache is not None and validate_cache(data['cache'])!=validate_cache(cache):raise ValueError('Final cache counters differ')
    return dict(api=data['boundaryApi'],exit_status=data['exitStatus'],transport_hold_ms=EXIT_HOLD_MS,
                frames=frames,scope='Self-TerminateProcess entry;not completed OS termination.')
