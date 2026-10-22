"""Authored clock/control mutations; no runtime/API/packet observation."""
from copy import deepcopy
import hashlib
import json
import unittest
from tests.test_attribution_control import fixture as legacy_fixture,IMAGE,FOLDER,RUN
from tools.frida_attribution_clock import build_source,control_request,CLOCK_KEY,PROFILE,CLOCK_KEY_KERNEL32,PROFILE_KERNEL32
from tools.verify_attribution_control import verify


def fixture():
    value=legacy_fixture();config,request=control_request(IMAGE,FOLDER,RUN)
    source=build_source(config).encode();inputs=value['inputs']
    inputs.update(config=config,request=request,source_sha256=hashlib.sha256(source).hexdigest(),observer_profile=PROFILE)
    value['source']=source;e=value['result']['structuredContent'];n=e['normalized_result']
    e['parameters'].update({k:request[k] for k in ('mode','device_id','program','argv')})
    n['source_sha256']=inputs['source_sha256'];messages=n['messages']
    for message in messages:
        data=message['payload']['data']
        if 'installed' in data:data['installed']=data['installed']+[dict(key=CLOCK_KEY)]
        if 'counts' in data:data['counts'][CLOCK_KEY]=8
    final=messages.pop();final['payload']['elapsedMs']=4000
    ticks=[]
    for index in range(8):
        elapsed=200+300*index;tick=50000+elapsed;ticks.append(tick)
        row=dict(schema=1,seq=0,runId=RUN,pid=100,tid=200,elapsedMs=elapsed,kind='clock-anchor',data=dict(tickMs=tick))
        messages.append(dict(script_id='script',type='send',payload=row))
    messages.append(final)
    for seq,message in enumerate(messages,1):message['payload']['seq']=seq
    value['positive']['clockTicks']=ticks
    return value


def check(value,*,clocked=True):
    value=deepcopy(value)
    value['result']['content']=[dict(type='text',text=json.dumps(value['result']['structuredContent']))]
    return verify(**value,clocked=clocked)


class AttributionClockTests(unittest.TestCase):
    def test_two_export_profile_requires_both_positive_hooks_and_receipt(self):
        value=fixture();config,request=control_request(IMAGE,FOLDER,RUN,include_kernel32=True)
        value['inputs'].update(config=config,request=request,observer_profile=PROFILE_KERNEL32)
        value['source']=build_source(config,include_kernel32=True).encode()
        sha=hashlib.sha256(value['source']).hexdigest();value['inputs']['source_sha256']=sha
        evidence=value['result']['structuredContent'];evidence['parameters']['argv']=request['argv']
        evidence['normalized_result']['source_sha256']=sha
        value['positive']['clockModules']=['kernelbase.dll','kernel32.dll']*4
        messages=evidence['normalized_result']['messages']
        for message in messages:
            data=message['payload']['data']
            if 'installed' in data:data['installed']=data['installed']+[dict(key=CLOCK_KEY_KERNEL32)]
            if 'counts' in data:data['counts'][CLOCK_KEY_KERNEL32]=4
        self.assertTrue(check(value)['passed'])
        broken=deepcopy(value);broken['positive']['clockModules']=['kernelbase.dll']*8
        self.assertFalse(check(broken)['passed'])
        broken=deepcopy(value);broken['result']['structuredContent']['normalized_result']['messages'][-1]['payload']['data']['counts'][CLOCK_KEY_KERNEL32]=0
        self.assertFalse(check(broken)['passed'])

    def test_clocked_control_retains_narrow_scope_and_legacy_stays_separate(self):
        result=check(fixture());self.assertTrue(result['passed'],result)
        self.assertEqual(result['clock_anchor_count'],8)
        self.assertTrue(result['native_clock_return_anchors_qualified'])
        self.assertFalse(result['game_stage_alignment_qualified'])
        self.assertFalse(result['analytics_removal_qualified'])
        self.assertFalse(check(fixture(),clocked=False)['passed'])
        self.assertFalse(check(legacy_fixture())['passed'])

    def test_source_observes_existing_clock_returns_without_target_calls(self):
        value=fixture();source=value['source'].decode()
        self.assertIn("if(name==='GetTickCount64')",source)
        self.assertIn("emit('clock-anchor',{tickMs})",source)
        self.assertIn('if(!clockReady)return;',source)
        for forbidden in ('new NativeFunction','Interceptor.replace','retval.replace','rpc.exports'):
            self.assertNotIn(forbidden,source)
        compile(value['inputs']['request']['argv'][3],'<authored clock control>','exec')

    def test_rejects_missing_mismatched_or_nonmonotonic_clock_receipts_and_rows(self):
        for mode in ('missing','missing_anchor','missing_hook','wrong_tick','decreasing','elapsed_drift','bool_tick','bool_receipt','extra_data','wrong_profile','clock_not_called'):
            value=fixture();messages=value['result']['structuredContent']['normalized_result']['messages']
            anchors=[m['payload'] for m in messages if m['payload']['kind']=='clock-anchor']
            if mode=='missing':value['positive'].pop('clockTicks')
            elif mode=='missing_anchor':anchors[0]['kind']='heartbeat';anchors[0]['data']=deepcopy(messages[-1]['payload']['data'])
            elif mode=='missing_hook':
                for message in messages:
                    data=message['payload']['data']
                    if 'installed' in data:data['installed']=[h for h in data['installed'] if h['key']!=CLOCK_KEY]
            elif mode=='wrong_tick':value['positive']['clockTicks'][0]+=1
            elif mode=='decreasing':anchors[1]['data']['tickMs']=1
            elif mode=='elapsed_drift':anchors[1]['elapsedMs']+=200
            elif mode=='bool_tick':anchors[0]['data']['tickMs']=True
            elif mode=='bool_receipt':value['positive']['clockTicks'][0]=True
            elif mode=='extra_data':anchors[0]['data']['private']='unexpected'
            elif mode=='wrong_profile':value['inputs']['observer_profile']='legacy'
            elif mode=='clock_not_called':messages[-1]['payload']['data']['counts'][CLOCK_KEY]=0
            with self.subTest(mode=mode):self.assertFalse(check(value)['passed'])


if __name__=='__main__':unittest.main()
