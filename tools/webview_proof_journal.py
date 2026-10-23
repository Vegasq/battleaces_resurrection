"""Read complete immutable WebView diagnostic publications from an owned profile.

The producer closes its temporary before renaming to a fresh numbered name.
Readers never require replacement of an already-open publication. No producer
file is written or deleted here, and malformed/latest evidence is not skipped.
"""
import json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PHASES={'configured','waiting_initialization','initialized','page_loaded','stop_requested','completed','failed'}

def latest(profile,pid):
    profile=Path(profile).resolve()
    if not profile.is_relative_to(ROOT/'local') or profile.parent.name!='profiles' or profile.parent.parent.name!='.battleaces-resurrection' or \
            not re.fullmatch('nativestest_[a-z0-9_-]{1,34}',profile.name) or type(pid) is not int or not 0<pid<2**32:
        raise ValueError('Owned profile and actual process PID required')
    publications=[]
    for p in profile.glob(f'webview-proof-{pid}-*.json'):
        if len(publications)>=256:raise ValueError('WebView publication bound exceeded')
        publications.append(p)
    if not publications:return None
    numbered=[]
    for p in publications:
        m=re.fullmatch(r'webview-proof-'+str(pid)+r'-([1-9][0-9]{0,5})\.json',p.name)
        if not m:raise ValueError('Malformed WebView publication name')
        numbered.append((int(m.group(1)),p))
    ordinal,path=max(numbered);raw=path.read_bytes()
    if not 0<len(raw)<=65536:raise ValueError('WebView publication size differs')
    data=json.loads(raw)
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data['schema']!=1 or \
            type(data.get('pid')) is not int or data['pid']!=pid or type(data.get('publication')) is not int or \
            data['publication']!=ordinal or data.get('phase') not in PHASES:
        raise ValueError('WebView publication identity differs')
    return path,data
