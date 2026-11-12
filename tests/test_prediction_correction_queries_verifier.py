"""Pure verifier/CLI controls; no original engine or child process is started."""
import copy
import io
import struct
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from tests.test_prediction_corrections import view
from tools import verify_prediction_correction_queries as v


def packet(*, entity=11, kind=1):
    return struct.pack('<IQiiQI',1,7,311,310,1,1)+struct.pack('<IIIQfff',entity,kind,1,5,1.25,0.,-.5)


def reports():
    hashes = {'ordinary/view1.bin':'a'*64,'executed-inputs.json':'d'*64,'terminal31.bin':'e'*64}
    common = dict(passed=True,observer_enabled=False,available_own_comparisons=362,terminal_full_comparisons=1,
                  query_audit=dict(ordinary_own_frames=372,terminal_full_frames=1,diagnostic_queries_during_gameplay=0),raw_observation_sha256=hashes,
                  repair_boundary_ns=12345,metadata_request_ns=None,native_calls_including_cleanup=1000)
    disabled = dict(copy.deepcopy(common),role='disabled',added_pair_ns=[],metadata=None,corrected_head_own_reference_checked=None)
    enabled = dict(copy.deepcopy(common),role='enabled',added_pair_ns=[123],metadata=v.metadata(packet(),7,311),
                   native_calls_including_cleanup=1002,metadata_request_ns=45,corrected_head_own_reference_checked=True)
    return disabled,enabled


class QueryControlTests(unittest.TestCase):
    def test_literal_wire_fields_native_zero_identity_and_negative_cases(self):
        row=v.metadata(packet(entity=0,kind=0),7,311)
        self.assertEqual(row['entries'][0],dict(entity=0,type=0,army=1,incarnation=5,delta=[1.25,0.,-.5]))
        for raw in (b'',packet()[:-1],packet()+b'x',struct.pack('<IQiiQI',2,7,311,310,1,0),
                    struct.pack('<IQiiQI',1,7,311,310,1,1)+struct.pack('<IIIQfff',11,1,1,0,1.,0.,0.),
                    struct.pack('<IQiiQI',1,7,311,310,1,1)+struct.pack('<IIIQfff',11,1,1,5,float('nan'),0.,0.)):
            with self.subTest(size=len(raw)),self.assertRaises(AssertionError):v.metadata(raw,7,311)
        with self.assertRaises(AssertionError):v.metadata(packet(),8,311)
        with self.assertRaises(AssertionError):v.metadata(packet(),7,312)

    def test_native_delta_is_same_H_with_no_normal_next_step(self):
        raw=lambda f,x:view(f,{11:(x,0.,0.)},identities={11:(1,1)},viewer=1)
        self.assertEqual(v.expected_delta(raw(310,4.),raw(310,1.),11),[-3.,0.,0.])
        with self.assertRaisesRegex(AssertionError,'same own native H'):
            v.expected_delta(raw(310,4.),raw(311,2.),11)
        with self.assertRaises(AssertionError):v.expected_delta(raw(310,4.),view(310,{11:(1.,0.,0.)},viewer=0),11)

    def test_enabled_disabled_exact_bytes_inputs_head_and_query_count(self):
        disabled,enabled=reports();result=v.compare_roles(disabled,enabled)
        self.assertTrue(result['passed']);self.assertEqual(result['enabled_added_own_pairs'],1)
        self.assertIn('one sample',result['timing_scope'].lower())
        mutations=[lambda r:r.update(passed=False),lambda r:r.update(observer_enabled=True),
            lambda r:r.update(available_own_comparisons=361),lambda r:r['raw_observation_sha256'].update({'ordinary/view1.bin':'f'*64}),
            lambda r:r['raw_observation_sha256'].update({'executed-inputs.json':'f'*64}),
            lambda r:r['raw_observation_sha256'].update({'terminal31.bin':'f'*64}),
            lambda r:r.update(added_pair_ns=[1,2]),lambda r:r.update(native_calls_including_cleanup=1003),
            lambda r:r.update(corrected_head_own_reference_checked=False),
            lambda r:r['metadata'].update(entries=[])]
        for mutate in mutations:
            bad=copy.deepcopy(enabled);mutate(bad)
            with self.subTest(mutation=mutate),self.assertRaises(AssertionError):v.compare_roles(disabled,bad)

    def test_no_diagnostic_query_inside_replay_or_any_gameplay_phase(self):
        for phase in ('startup','prefix','pending','repair','continuations'):
            with self.subTest(phase=phase),self.assertRaisesRegex(AssertionError,'contaminate'):
                v.admit_query(31,phase)
            v.admit_query(1,phase)
        pairs=[dict(phase='startup',frame=0xffffffff,viewer=1)]
        for frame in range(372):
            if frame==311:pairs.append(dict(phase='repair',frame=310,viewer=1))
            pairs.append(dict(phase='prefix'if frame<=300 else 'pending'if frame<=310 else 'continuations',frame=frame,viewer=1))
        pairs.append(dict(phase='terminal_full_state',frame=371,viewer=31))
        self.assertEqual(v.audit_queries(pairs,'enabled')['diagnostic_queries_during_gameplay'],0)
        bad=copy.deepcopy(pairs);bad.insert(313,dict(phase='repair',frame=310,viewer=31))
        with self.assertRaises(AssertionError):v.audit_queries(bad,'enabled')
        bad=copy.deepcopy(pairs);bad[-1]['frame']=370
        with self.assertRaises(AssertionError):v.audit_queries(bad,'enabled')

    def test_coordinator_overrides_baseline_all_view_warm_and_observe(self):
        with tempfile.TemporaryDirectory()as directory:
            c=object.__new__(v.Coordinator);c.output=Path(directory);c.raw_streams={};c.observations={};c.observer_seconds=0
            viewers=[]
            def dispatch(op,payload):
                if op==5:return 0,struct.pack('<Q',7)
                if op==64:return 0,b''
                self.assertEqual(op,9)
                world,viewer,_=struct.unpack('<QII',payload);self.assertEqual(world,7);viewers.append(viewer)
                raw=view(0,{11:(1.,0.,0.)},identities={11:(1,1)},viewer=viewer)
                return 0,struct.pack('<IiI',len(raw),0,len(raw))+raw
            c.dispatch=dispatch;c.success=lambda op,payload=b'':dispatch(op,payload)[1];c.metrics=lambda world:dict(captures=1)
            self.assertEqual(c.create(b'authored'),7)
            observed=c.observe(7,0,'prefix');self.assertEqual(observed['state']['local_alliance'],1)
            self.assertEqual(viewers,[1,1])
            for stream in [*c.raw_streams.values(),*c.observations.values()]:stream.close()

    def test_available_own_view_reference_comparison_does_not_invent_hidden_rows(self):
        from server.native_simulation import decode_snapshot
        from tools.verify_prediction_combat_fixture import entity_states
        from tools.verify_prediction_worker_reconcile import normalized
        full=view(310,{11:(4.,0.,0.),10:(20.,0.,0.)},identities={11:(1,1),10:(0,1)},viewer=31)
        reference={310:dict(state=decode_snapshot(full,31,include_entities=True),modes=normalized(entity_states(full)))}
        def observed(raw):return normalized(dict(state=decode_snapshot(raw,1,include_entities=True),entity_states=entity_states(raw)))
        own=view(310,{11:(4.,0.,0.)},identities={11:(1,1)},viewer=1)
        v.compare_own(observed(own),reference,310)
        for raw in (view(310,{11:(5.,0.,0.)},identities={11:(1,1)},viewer=1),view(310,{},viewer=1)):
            with self.assertRaises(AssertionError):v.compare_own(observed(raw),reference,310)

    def test_default_mode_is_file_only_prepare_and_inputs_are_explicit(self):
        with patch.object(v,'prepare',return_value={'output':'fresh'})as prepare,patch.object(v,'run_prepared')as run, \
                patch.object(v.sys,'stdout',io.StringIO()):
            self.assertEqual(v.main(['--output','fresh','--reference','closed','--original-dll','Simulation.dll',
                '--heap-helper','BAHeap.dll','--cooperative','PredictionCooperative.dll']),0)
        prepare.assert_called_once();run.assert_not_called()
        self.assertEqual(prepare.call_args.args[0].reference,Path('closed'))
        with patch.object(v,'prepare')as prepare,patch.object(v.sys,'stderr',io.StringIO()),self.assertRaises(SystemExit):
            v.main(['--output','fresh','--prepare-only'])
        prepare.assert_not_called()

    def test_fresh_ignored_output_refusal_precedes_reference_or_native_access(self):
        from types import SimpleNamespace
        args=SimpleNamespace(output=v.ROOT/'tools',reference=Path('unused'))
        with patch.object(v,'references')as reference,self.assertRaises(AssertionError):v.prepare(args)
        reference.assert_not_called()

    def test_child_cannot_start_without_role_and_retained_owner_barrier(self):
        with patch.object(v.sys,'stdin',type('Input',(),{'buffer':io.BytesIO(b'NOT_OWNED\n')})()), \
                patch.object(v.base,'verify_prepared')as verify,self.assertRaises(AssertionError):
            v.child(Path('unused'),'enabled')
        verify.assert_not_called()


if __name__=='__main__':unittest.main()
