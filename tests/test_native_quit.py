"""Diagnostic false-pass regressions; authored fixtures, no game execution."""
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import Mock, patch

from tools import verify_native_quit as quit_probe


class NativeQuitVerifierTests(unittest.TestCase):
    def test_replay_game_spawn_scope_does_not_intercept_shared_subprocess_users(self):
        import subprocess
        from tools.verify_native_replay_menu import scoped_spawn_module
        from tools import helper_provenance
        original=subprocess.Popen;spawn=Mock()
        scoped=scoped_spawn_module(subprocess,spawn)
        self.assertIs(scoped.Popen,spawn)
        self.assertIs(scoped.STARTUPINFO,subprocess.STARTUPINFO)
        self.assertIs(subprocess.Popen,original)
        self.assertIs(helper_provenance.subprocess.Popen,original)

    def test_frozen_helper_requires_explicit_exact_source_pin(self):
        from tools import helper_provenance as provenance
        root=quit_probe.ROOT/'local'/('quit-frozen-'+uuid.uuid4().hex)
        (root/'client_patch/src').mkdir(parents=True);(root/'game').mkdir()
        self.addCleanup(shutil.rmtree,root)
        old={'client_patch/build.ps1':b'old build source\n','client_patch/src/helper.cpp':b'old helper source\n'}
        for name in old:(root/name).write_bytes(b'new source\n')
        helper=root/'game/BattleAcesOffline.dll';helper.write_bytes(b'authored non-executable helper')
        receipt=dict(schema=1,sources_unchanged_during_build=True,source_sha256={n:hashlib.sha256(b).hexdigest() for n,b in old.items()},
                     helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),compiler_path='authored compiler',compiler_sha256='a'*64,sdk_version='10.0.0.0')
        path=root/'helper-build.json';path.write_text(json.dumps(receipt))
        with patch.object(quit_probe,'ROOT',root),patch.object(provenance,'git_sources',return_value=('f'*40,old)):
            with self.assertRaisesRegex(AssertionError,'current sources'):quit_probe.verify_build_receipt(root/'game',path)
            report=quit_probe.verify_build_receipt(root/'game',path,source_revision='f'*40)
            self.assertEqual(report['receipt'],receipt)
            self.assertEqual(report['source_binding']['source'],dict(mode='pinned-git',revision='f'*40))
            for invalid in ('HEAD','','--all'):
                with self.subTest(pin=invalid),self.assertRaises(AssertionError):quit_probe.verify_build_receipt(root/'game',path,source_revision=invalid)
            helper.write_bytes(b'changed helper')
            with self.assertRaisesRegex(AssertionError,'pinned sources'):quit_probe.verify_build_receipt(root/'game',path,source_revision='f'*40)

    def test_practice_rejects_supply_and_commands_without_same_entity_movement(self):
        match='a'*32;pid=123
        temp_root=(quit_probe.ROOT/'local').resolve()
        self.assertTrue(temp_root.is_relative_to(quit_probe.ROOT.resolve()))
        temp_root.mkdir(exist_ok=True)
        for moved,ordered,target,accepted in ((True,True,101,True),(False,True,101,False),
                                             (True,False,101,False),(True,True,102,False)):
            with self.subTest(moved=moved,ordered=ordered,target=target):
                # Inherit workspace ACLs;Python3.14's mode0700 temporary dirs
                # cannot be reopened by the Windows automation token.
                folder=temp_root/('native-quit-movement-'+uuid.uuid4().hex)
                self.assertEqual(folder.resolve().parent,temp_root)
                folder.mkdir()
                try:
                    game=folder/'game';output=folder/'output';output.mkdir()
                    runtime=game/'investigation/runtime';runtime.mkdir(parents=True)
                    (runtime/f'lan-resources-{pid}-{match}.tsv').write_text('viewer\tarmy\tcurrent_supply\n1\t1\t14\n')
                    lines=[f'Practice requested: match={match} ', 'Practice AI join captured:',
                           'Practice AI JoinedGame delivered:',
                           'PRACTICE SMOKE original EditDeck mode4 callback: owned=1 visible=1 interactable=1 preamble=1',
                           'Practice original JoinArmy: '+json.dumps({'deck':{'units':[1]}}),
                           'Practice original JoinArmy: '+json.dumps({'deck':{'units':[34]}})]
                    lines+=['Practice AI action: case=1']*5
                    lines+=['Practice AI entity: frame=1 army=1 id=101 type=34 position=(1,0,1)',
                            f'Practice AI entity: frame=2 army=1 id=101 type=34 position=({2 if moved else 1},0,1)']
                    if ordered:lines+=['Practice AI protobuf: '+json.dumps({'executeCommand':{
                        'commandData':{'targetGroundCommandData':{}},'entityTypeData':[{'abilityId':12,'entityIds':[target]}]}})]
                    lines+=['Practice native EndOfGameResponse delivered;','PRACTICE SMOKE native Continue (automated)',
                            'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1',
                            'NATIVE QUIT owned menu verified:']
                    if accepted:
                        result=quit_probe.practice_evidence(game,output,pid,'\n'.join(lines))
                        self.assertEqual(result['produced_bot_units_with_orders_and_position_change'],[101])
                    else:
                        with self.assertRaisesRegex(AssertionError,'correlated native movement'):
                            quit_probe.practice_evidence(game,output,pid,'\n'.join(lines))
                finally:
                    self.assertEqual(folder.resolve().parent,temp_root)
                    shutil.rmtree(folder)

    def telemetry_fixture(self,*,practice=False):
        from tests.test_telemetry_audit import fixture,SHA
        path=('startup-after-engine-init','menu')
        if practice:path+=('ingame','postgame','menu')
        path+=('pre-quit-confirm',)
        count=len(path)
        lines=fixture(path)+[
            '[110] TELEMETRY PREQUIT boundary: thread=17 samplesBefore='+str(count-1)+' samplesAfter='+str(count)+' readOnly=1 originalConfirmNext=1',
            '[111] NATIVE QUIT original confirmation dispatch: thread=17 worldIdle=1 assetLoadingCount=0 naturalExitDeadlineSeconds=60']
        return '\n'.join(lines),[dict(event='OnConfirm.dispatch',tick=111,thread=17)],SHA

    def test_telemetry_pre_quit_boundary_precedes_same_thread_original_confirmation(self):
        text,rows,sha=self.telemetry_fixture()
        self.assertTrue(quit_probe.telemetry_evidence(text,rows,sha)['same_original_quit_thread'])
        self.assertTrue(quit_probe.telemetry_evidence(text.replace('[111] NATIVE QUIT','[112] NATIVE QUIT'),rows,sha)['passed'])
        for changed in (text.replace('thread=17 samplesBefore','thread=18 samplesBefore'),
                        text.replace('[110] TELEMETRY PREQUIT','[112] TELEMETRY PREQUIT'),
                        text.replace('samplesBefore=2','samplesBefore=1')):
            with self.subTest(changed=changed[-240:]),self.assertRaises(AssertionError):
                quit_probe.telemetry_evidence(changed,rows,sha)

    def test_practice_telemetry_needs_result_and_returned_menu_before_quit(self):
        text,rows,sha=self.telemetry_fixture(practice=True)
        self.assertTrue(quit_probe.telemetry_evidence(text,rows,sha,after_practice=True)['passed'])
        text,rows,sha=self.telemetry_fixture()
        with self.assertRaises(AssertionError):quit_probe.telemetry_evidence(text,rows,sha,after_practice=True)

    def test_device_probe_requires_one_matching_guarded_call_before_quit(self):
        text,rows,sha=self.telemetry_fixture()
        call='[102] TELEMETRY DEVICE probe passed: version=1 thread=17 calls=1 returned=0 mainStable=1 disabledFieldsUnchanged=1 rawHeaderUnchanged=1 markerBefore=0 markerAfter=0 configCount=0 payloadRead=0'
        identity='[102] TELEMETRY IDENTITY probe passed: version=1 thread=17 calls=2 borrowedUnreadable=1 mainStable=1 emptySsoMetadataUnchanged=1 identityPayloadRead=0'
        ads='[102] TELEMETRY ADS probe passed: version=1 thread=17 calls=1 authoredInput=1 retainedEmpty=1 tracking=1 dirty=1 state=0 borrowedUnchanged=1 retainedPayloadRead=0'
        events='[102] TELEMETRY EVENTS probe passed: version=1 thread=17 calls=3 returnedDisabled=3 borrowedUnreadable=1 sampledStateUnchanged=1 payloadRead=0'
        controls='[102] TELEMETRY EVENTCONTROL probe passed: version=1 thread=17 calls=9 returnedDisabled=9 borrowedUnreadable=1 sampledStateUnchanged=1 payloadRead=0'
        custom='[102] TELEMETRY CUSTOMDATA probe passed: version=1 thread=17 creates=1 adds=7 addFalse=7 destroys=1 realNativeOwner=1 emptyMetadataUnchanged=1 borrowedUnreadable=1 borrowedPayloadRead=0'
        continuous='[102] TELEMETRY CONTINUOUS probe passed: version=1 thread=17 calls=5 returnedDisabled=5 borrowedUnreadable=1 sampledStateUnchanged=1 borrowedPayloadRead=0'
        # Place the active probe in the menu,not inside the final sample.
        text=text.replace('[103] Telemetry audit',call+'\n'+identity+'\n'+ads+'\n'+events+'\n'+controls+'\n'+custom+'\n'+continuous+'\n[103] Telemetry audit',1)
        self.assertTrue(quit_probe.telemetry_evidence(text,rows,sha,device_probe=True)['device_api_guarded_false_and_sampled_config_unchanged'])
        self.assertTrue(quit_probe.telemetry_evidence(text,rows,sha,device_probe=True)['identity_setters_guarded_void_and_metadata_unchanged'])
        self.assertTrue(quit_probe.telemetry_evidence(text,rows,sha,device_probe=True)['ads_callback_copy_guard_and_progress_qualified'])
        self.assertTrue(quit_probe.telemetry_evidence(text,rows,sha,device_probe=True)['event_apis_guarded_disabled_before_input_access'])
        self.assertTrue(quit_probe.telemetry_evidence(text,rows,sha,device_probe=True)['event_control_apis_guarded_disabled_before_input_access'])
        self.assertTrue(quit_probe.telemetry_evidence(text,rows,sha,device_probe=True)['custom_event_data_empty_native_lifetime_and_add_false_qualified'])
        self.assertTrue(quit_probe.telemetry_evidence(text,rows,sha,device_probe=True)['continuous_event_inputs_guarded_disabled_before_registration'])
        for changed in (text.replace(call,''),text.replace(call,call+'\n'+call),
                        text.replace('returned=0','returned=1'),text.replace('markerBefore=0','markerBefore=1'),
                        text.replace('calls=1 returned','calls=2 returned'),
                        text.replace(call,call.replace('[102]','[104]')),
                        text.replace('thread=17 calls','thread=18 calls'),text.replace(identity,''),
                        text.replace(identity,identity+'\n'+identity),text.replace('identityPayloadRead=0','identityPayloadRead=1'),
                        text.replace('emptySsoMetadataUnchanged=1','emptySsoMetadataUnchanged=0'),text.replace(ads,''),
                        text.replace(ads,ads+'\n'+ads),text.replace('retainedEmpty=1','retainedEmpty=0'),
                        text.replace('dirty=1 state=0','dirty=0 state=0'),text.replace('retainedPayloadRead=0','retainedPayloadRead=1'),
                        text.replace(events,''),text.replace(events,events+'\n'+events),
                        text.replace('returnedDisabled=3','returnedDisabled=2'),text.replace('sampledStateUnchanged=1','sampledStateUnchanged=0'),
                        text.replace(events,events.replace('payloadRead=0','payloadRead=1')),
                        text.replace(controls,''),text.replace(controls,controls+'\n'+controls),
                        text.replace('returnedDisabled=9','returnedDisabled=8'),text.replace('calls=9','calls=8'),
                        text.replace(controls,controls.replace('payloadRead=0','payloadRead=1')),
                        text.replace(custom,''),text.replace(custom,custom+'\n'+custom),
                        text.replace('destroys=1','destroys=0'),text.replace('realNativeOwner=1','realNativeOwner=0'),
                        text.replace('emptyMetadataUnchanged=1','emptyMetadataUnchanged=0'),
                        text.replace(continuous,''),text.replace(continuous,continuous+'\n'+continuous),
                        text.replace('returnedDisabled=5','returnedDisabled=4'),text.replace('calls=5','calls=4'),
                        text.replace(continuous,continuous.replace('borrowedPayloadRead=0','borrowedPayloadRead=1'))):
            with self.subTest(changed=changed[-240:]),self.assertRaises(AssertionError):
                quit_probe.telemetry_evidence(changed,rows,sha,device_probe=True)

    def test_old_process_trace_cannot_start_current_quit_deadline(self):
        row=dict(pid=42,tick=1000,event='OnConfirm.dispatch',thread=9)
        raw=(json.dumps(row)+'\n').encode()
        with self.assertRaisesRegex(AssertionError,'another process/run'):
            quit_probe.current_trace_rows(raw,43,1001)
        with self.assertRaisesRegex(AssertionError,'another process/run'):
            quit_probe.current_trace_rows(raw,42,1001)
        self.assertEqual(quit_probe.current_trace_rows(raw,42,999),[row])
        self.assertEqual(quit_probe.current_trace_rows(raw[:-1],42,999),[])

    def test_restart_refuses_existing_trace_before_launch(self):
        root=Path(__file__).resolve().parents[1]/'local'/('quit-trace-'+uuid.uuid4().hex)
        root.mkdir();self.addCleanup(shutil.rmtree,root)
        target=root/'quit-trace.jsonl'
        quit_probe.require_fresh_trace(target)
        target.write_text('{"event":"OnConfirm.dispatch","pid":42,"tick":1000}\n')
        with self.assertRaisesRegex(AssertionError,'fresh trace path'):
            quit_probe.require_fresh_trace(target)
        self.assertIn('OnConfirm.dispatch',target.read_text())

    def test_already_exited_process_cannot_pass_after_the_deadline(self):
        with self.assertRaisesRegex(AssertionError,'within60s'):
            quit_probe.observe_exit(Mock(poll=Mock(return_value=0)),1000,lambda:61000)

    def test_exit_poll_crossing_deadline_is_rejected(self):
        clock = Mock(side_effect=[60999,61000])
        with self.assertRaisesRegex(AssertionError,'observation exceeded60s'):
            quit_probe.observe_exit(Mock(poll=Mock(return_value=0)),1000,clock)

    def test_timely_exit_and_still_running_are_distinct(self):
        self.assertEqual(quit_probe.observe_exit(Mock(poll=Mock(return_value=0)),1000,lambda:1200),1200)
        self.assertIsNone(quit_probe.observe_exit(Mock(poll=Mock(return_value=None)),1000,lambda:1200))

    def test_build_receipt_rejects_stale_helper_source_and_incomplete_scope(self):
        parent = Path(__file__).resolve().parents[1]/'local'
        parent.mkdir(exist_ok=True)
        root = parent/('quit-receipt-'+uuid.uuid4().hex)
        root.mkdir()
        self.addCleanup(shutil.rmtree,root)
        if root.is_dir():
            (root/'client_patch/src').mkdir(parents=True)
            (root/'game').mkdir()
            for name in ('client_patch/build.ps1','client_patch/src/helper.cpp','client_patch/src/header.hpp'):
                (root/name).write_bytes(b'authored source')
            helper = root/'game/BattleAcesOffline.dll'
            helper.write_bytes(b'authored non-executable helper')
            sources = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (root/'client_patch').rglob('*') if p.is_file()}
            receipt = dict(schema=1,sources_unchanged_during_build=True,source_sha256=sources,
                           helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest())
            path = root/'helper-build.json'
            path.write_text(json.dumps(receipt),encoding='utf-8')
            with patch.object(quit_probe,'ROOT',root):
                self.assertEqual(quit_probe.verify_build_receipt(root/'game',path)['receipt'],receipt)
                for change in ('helper','source','missing-header','changed-during-build'):
                    with self.subTest(change=change):
                        changed = json.loads(json.dumps(receipt))
                        if change=='helper': changed['helper_sha256']='0'*64
                        if change=='source': changed['source_sha256']['client_patch/src/helper.cpp']='0'*64
                        if change=='missing-header': del changed['source_sha256']['client_patch/src/header.hpp']
                        if change=='changed-during-build': changed['sources_unchanged_during_build']=False
                        path.write_text(json.dumps(changed),encoding='utf-8')
                        with self.assertRaisesRegex(AssertionError,'does not bind'):
                            quit_probe.verify_build_receipt(root/'game',path)
