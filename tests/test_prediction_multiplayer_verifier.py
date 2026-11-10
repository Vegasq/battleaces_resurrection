"""File-only preparation, ownership faults and authored feel evidence controls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from client_patch.patcher import prediction_actor_repair, prediction_worker
from server.game_data import decode_player_input, encode_identity, encode_player_input
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint
from tools import verify_prediction_multiplayer as verifier


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'local/prediction-runtime/game'
        self.assets = self.root / 'assets'
        self.game.mkdir(parents=True); self.assets.mkdir()
        self.source = self.root / 'control.py'; self.source.write_text('FROZEN = True\n')
        self.sources = {'control.py': verifier.sha(self.source)}
        for name in ('client_patch/build.ps1', 'client_patch/src/owned.cpp', 'client_patch/checkpoint/owned.hpp'):
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('// authored\n')
            self.sources[name] = verifier.sha(path)
        for name in ('game.exe', 'helper.dll', 'assembly.dll', 'python.exe'):
            (self.root / name).write_bytes(b'MZ' + name.encode())
        helper = b'MZ' + b' '.join((b'BA_RESURRECTION_MOVEMENT_PIPELINE_V1',
            b'BA_RESURRECTION_NATIVE_WORKER_PROXY_V1', b'BA_RESURRECTION_ORIGINAL_COMMAND_SCHEDULING_V1'))
        hooks = prediction_worker.CALL_HOOKS + prediction_actor_repair.CALL_HOOKS
        helper += b' '.join(h['name'].encode() + b'\0' for h in hooks)
        (self.game / 'BattleAcesOffline.dll').write_bytes(helper)
        (self.game / 'Battle Aces.exe').write_bytes(b'MZgame')
        (self.game / 'GameAssembly.dll').write_bytes(b'MZassembly')
        self.sim = b'MZoriginal-simulation-fixture'
        plugins = self.game / 'Battle Aces_Data/Plugins/x86_64'; plugins.mkdir(parents=True)
        (plugins / 'Simulation.dll').write_bytes(self.sim)
        state = self.game / '.battleaces-resurrection'; state.mkdir()
        (state / 'patch-manifest.json').write_text(json.dumps(dict(
            helper_sha256=verifier.sha(self.game / 'BattleAcesOffline.dll'),
            patched_sha256=verifier.sha(self.game / 'GameAssembly.dll'), call_hooks=hooks)))
        build_receipt = self.root / 'helper-build.json'
        build_receipt.write_text(json.dumps(dict(schema=1, sources_unchanged_during_build=True,
            helper_sha256=verifier.sha(self.game / 'BattleAcesOffline.dll'),
            source_sha256={k: v for k, v in self.sources.items() if k.startswith('client_patch/')})))
        self.helpers = {}
        for name in ('heap_helper', 'cooperative'):
            folder = self.root / name; folder.mkdir()
            path = folder / ('BAHeap.dll' if name == 'heap_helper' else 'cooperative.dll')
            path.write_bytes(b'MZ' + name.encode())
            (folder / 'build.json').write_text(json.dumps(dict(experimental=True,
                dll_sha256=verifier.sha(path), source_sha256='0' * 64, page_source_sha256='1' * 64)))
            self.helpers[name] = path
        (self.assets / 'descriptors').mkdir()
        assets = {'Simulation.dll': self.sim, 'map-1v1.pb.gz': b'map',
            'unit-catalog.json': b'{}', 'cosmetic-catalog.json': b'{}',
            'descriptors/game_pb.proto.json': b'{}'}
        for name, data in assets.items(): (self.assets / name).write_bytes(data)
        (self.assets / 'asset-manifest.json').write_text(json.dumps(dict(schema=1, game_build=37822,
            simulation_sha256=verifier.digest(self.sim), files={n: verifier.digest(d) for n, d in assets.items()})))
        self.args = argparse.Namespace(game=self.game, assets=self.assets, output=self.root / 'local/prepare01',
            module_root=self.root, python=self.root / 'python.exe', **self.helpers,
            helper_build_receipt=build_receipt, expected_helper_sha256=verifier.sha(self.game / 'BattleAcesOffline.dll'),
            expected_gameassembly_sha256=verifier.sha(self.game / 'GameAssembly.dll'),
            frames=None, scenario='startup', lifecycle='natural', timeout=180, rtt_ms=(130, 475), move_slot=0)
        self.addCleanup(patch.stopall)
        patch.object(verifier, 'ROOT', self.root).start()
        patch.object(verifier, 'SUPPORTED_SIM_SHA256', verifier.digest(self.sim)).start()
        patch.object(verifier, 'source_hashes', return_value=self.sources).start()

    def snapshot_game(self):
        return {str(p.relative_to(self.game)): verifier.sha(p) for p in self.game.rglob('*') if p.is_file()}

    def test_default_prepare_never_spawns_and_does_not_mutate_game(self):
        before = self.snapshot_game()
        with patch.object(verifier.subprocess, 'Popen', side_effect=AssertionError('must not spawn')):
            plan = verifier.prepare(self.args)
        self.assertFalse(plan['native_executed'])
        self.assertFalse(plan['full_feature_accepted'])
        self.assertEqual((plan['frames'], plan['expected_matches'], plan['surrender_frame']), (200, 2, 260))
        self.assertEqual(plan['rtt_ms'], [130, 475])
        self.assertEqual(before, self.snapshot_game())
        self.assertEqual(verifier.verify_prepared(self.args.output)['source_sha256'], self.sources)

    def worker_package_fixture(self):
        import shutil
        package = self.root / 'local/private-package'
        values = {
            'program/client-helper/BattleAcesOffline.dll': self.game / 'BattleAcesOffline.dll',
            'program/runtime/python.exe': self.args.python,
            'program/prediction/heap/BAHeap.dll': self.args.heap_helper,
            'program/prediction/heap/build.json': self.args.heap_helper.with_name('build.json'),
            'program/prediction/cooperative/PredictionCooperative.dll': self.args.cooperative,
            'program/prediction/cooperative/build.json': self.args.cooperative.with_name('build.json'),
        }
        for name, source in values.items():
            target = package / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        module = package / 'program/app/client_patch/prediction_worker/__main__.py'
        module.parent.mkdir(parents=True); module.write_text('# authored frozen worker\n')
        profile = package / 'program/prediction/prediction-profile.json'
        profile.write_text(json.dumps(dict(schema=1, profile='private-custom-movement-prediction-v1')))
        members = {p.relative_to(package).as_posix(): dict(bytes=p.stat().st_size, sha256=verifier.sha(p))
                   for p in package.rglob('*') if p.is_file()}
        (package / 'package-manifest.json').write_text(json.dumps(dict(schema=1, product='client', files=members)))
        self.args.worker_package = package
        self.args.python = package / 'program/runtime/python.exe'
        self.args.heap_helper = package / 'program/prediction/heap/BAHeap.dll'
        self.args.cooperative = package / 'program/prediction/cooperative/PredictionCooperative.dll'
        return package, module

    def test_packaged_worker_is_pinned_and_uses_frozen_import_path(self):
        package, module = self.worker_package_fixture()
        plan = verifier.prepare(self.args)
        self.assertEqual(plan['worker_module_root'], str(package / 'program/app'))
        self.assertIn('-prediction-worker-module-root=' + str(package / 'program/app'),
                      verifier.command_extra(plan, 0, self.args.output / 'run'))
        self.assertTrue(any(r['path'] == str(module) for r in plan['files'].values()))
        module.write_text('# changed after preparation\n')
        with self.assertRaisesRegex(AssertionError, 'changed'):
            verifier.verify_prepared(self.args.output)

    def test_same_bytes_in_global_python_do_not_qualify_bundled_runtime(self):
        self.worker_package_fixture()
        self.args.python = self.root / 'python.exe'
        with self.assertRaisesRegex(AssertionError, 'exact bundled path'):
            verifier.prepare(self.args)
        self.assertFalse(self.args.output.exists())

    def test_preexisting_output_is_rejected_without_writes(self):
        self.args.output.mkdir(parents=True); sentinel = self.args.output / 'failure.json'; sentinel.write_text('old')
        with self.assertRaisesRegex(AssertionError, 'output already exists'):
            verifier.prepare(self.args)
        self.assertEqual(list(self.args.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), 'old')

    def test_manual_copy_and_parent_output_are_forbidden(self):
        self.args.game = self.root / 'local/pw/game'
        with self.assertRaisesRegex(AssertionError, 'independent'):
            verifier.prepare(self.args)
        self.args.game = self.game; self.args.output = self.game.parent
        with self.assertRaisesRegex(AssertionError, 'separate'):
            verifier.prepare(self.args)

    def test_wrong_explicit_binary_pin_fails_before_output_creation(self):
        self.args.expected_helper_sha256 = '0' * 64
        with self.assertRaisesRegex(AssertionError, 'differs from explicit pins'):
            verifier.prepare(self.args)
        self.assertFalse(self.args.output.exists())

    def test_missing_optional_call_hook_is_not_accepted(self):
        path = self.game / '.battleaces-resurrection/patch-manifest.json'
        value = json.loads(path.read_text()); value['call_hooks'].pop(); path.write_text(json.dumps(value))
        with self.assertRaisesRegex(AssertionError, 'lacks movement hook'):
            verifier.prepare(self.args)
        self.assertFalse(self.args.output.exists())

    def test_source_binary_asset_or_snapshot_drift_prevents_execution(self):
        verifier.prepare(self.args)
        for path in (self.game / 'GameAssembly.dll', self.assets / 'map-1v1.pb.gz',
                     self.args.output / 'source-at-prepare/control.py'):
            old = path.read_bytes(); path.write_bytes(old + b'changed')
            with self.subTest(path=path), self.assertRaisesRegex(AssertionError, 'changed'):
                verifier.verify_prepared(self.args.output)
            path.write_bytes(old)
        with patch.object(verifier, 'source_hashes', return_value={'control.py': '0' * 64}):
            with self.assertRaisesRegex(AssertionError, 'source changed'):
                verifier.verify_prepared(self.args.output)

    def test_consumed_descriptor_drift_fails_preparation(self):
        (self.assets / 'descriptors/game_pb.proto.json').write_text('changed')
        with self.assertRaisesRegex(AssertionError, 'consumed authority asset differs'):
            verifier.prepare(self.args)

    def test_helper_receipt_must_bind_complete_current_native_sources(self):
        value = json.loads(self.args.helper_build_receipt.read_text())
        value['source_sha256'].pop('client_patch/checkpoint/owned.hpp')
        self.args.helper_build_receipt.write_text(json.dumps(value))
        with self.assertRaisesRegex(AssertionError, 'main helper build receipt differs'):
            verifier.prepare(self.args)
        self.assertFalse(self.args.output.exists())

    def test_bounds_and_movement_scenario_are_explicit(self):
        for rtts in ((130, float('nan')), (-1, 475), (130, 501)):
            self.args.rtt_ms = rtts
            with self.subTest(rtts=rtts), self.assertRaisesRegex(AssertionError, 'bounded timeout'):
                verifier.prepare(self.args)
        self.args.rtt_ms = (130, 475); self.args.scenario = 'movement'
        plan = verifier.prepare(self.args)
        self.assertEqual((plan['frames'], plan['surrender_frame']), (600, 700))
        extra = verifier.command_extra(plan, 0, self.args.output / 'run')
        self.assertIn('-prediction-movement-smoke', extra)
        self.assertIn('-community-match-leave-quit-smoke', extra)
        self.assertNotIn('-dedicated-auto-ready', extra)

    def test_movement_slot_forwarded_to_both_clients_without_changing_startup(self):
        self.args.scenario = 'movement'; self.args.move_slot = 1
        plan = verifier.prepare(self.args)
        self.assertEqual((plan['frames'],plan['surrender_frame']), (600,700))
        for client in (0,1):
            extra = verifier.command_extra(plan,client,self.args.output/'run')
            self.assertIn('-prediction-movement-smoke-slot='+str(client),extra)
            self.assertIn('-prediction-movement-smoke-start-frame='+str(440 if client==1 else 460),extra)
        plan['scenario']='startup'
        self.assertFalse(any(flag.startswith('-prediction-movement-smoke')for flag in
            verifier.command_extra(plan,0,self.args.output/'run')))

    def test_actor_fixture_is_explicit_prepared_metadata_not_an_ordinary_default(self):
        self.args.actor_correction = True
        with self.assertRaisesRegex(AssertionError, 'natural movement'):
            verifier.prepare(self.args)
        self.args.scenario = 'movement'
        plan = verifier.prepare(self.args)
        self.assertEqual(plan['actor_fixture'], verifier.actor_fixture_metadata())
        self.assertEqual(plan['actor_fixture']['safe_canonical_frames'], [152,153,154])
        for index in (0,1):
            self.assertIn('-prediction-actor-correction-smoke',
                          verifier.command_extra(plan,index,self.args.output/'run'))

    def test_changing_rtt_is_explicit_ordinary650_frame_fixture(self):
        self.args.changing_rtt=True;self.args.scenario='movement'
        plan=verifier.prepare(self.args)
        self.assertEqual(plan['frames'],650)
        self.assertEqual(plan['changing_pose_clock'],'sampled_us')
        self.assertIsNone(plan['actor_fixture']);self.assertFalse(plan['actor_correction'])
        for index in (0,1):
            flags=verifier.command_extra(plan,index,self.args.output/'run')
            self.assertEqual('-prediction-movement-smoke-distance=48' in flags,index==0)
            self.assertIn('-frame-timing-frames=650',flags)

    def test_changing_rtt_rejects_other_modes_actor_confound_or_wrong_topology(self):
        self.args.changing_rtt=True;self.args.scenario='movement'
        for key,value in (('scenario','startup'),('lifecycle','prefix'),('actor_correction',True),
                          ('move_slot',1),('rtt_ms',(475,130)),('frames',600)):
            old=getattr(self.args,key,None);setattr(self.args,key,value)
            with self.subTest(key=key),self.assertRaisesRegex(AssertionError,'changing RTT requires'):
                verifier.prepare(self.args)
            setattr(self.args,key,old)
        self.assertFalse(self.args.output.exists())

    def test_transition_orders_require_changing_and_only_flag_subject(self):
        self.args.transition_orders=True
        with self.assertRaisesRegex(AssertionError,'require explicit changing'):verifier.prepare(self.args)
        self.args.changing_rtt=True;self.args.scenario='movement'
        plan=verifier.prepare(self.args)
        for index in (0,1):
            flags=verifier.command_extra(plan,index,self.args.output/'run')
            gate=[flag for flag in flags if flag.startswith('-prediction-movement-smoke-transition-gates=')]
            self.assertEqual(len(gate),1 if index==0 else 0)
        self.assertTrue(plan['transition_orders'])
        self.assertEqual(plan['transition_phase_source'],'decision')

    def test_cli_parses_exact_optin_and_preserves_ordinary_defaults_without_running(self):
        base=[]
        for name in ('game','assets','output','python','module-root','heap-helper','cooperative','helper-build-receipt'):
            base+=['--'+name,str(self.root/name)]
        base+=['--expected-helper-sha256','a'*64,'--expected-gameassembly-sha256','b'*64]
        with (patch.object(verifier,'prepare',return_value=dict(output='owned',scenario='movement')) as prepare,
              patch('builtins.print')):
            self.assertEqual(verifier.main(base+['--scenario','movement','--lifecycle','natural','--changing-rtt',
                '--transition-orders','--frames','650','--timeout','240','--rtt-ms','130','475','--move-slot','0']),0)
            parsed=prepare.call_args[0][0]
            self.assertTrue(parsed.transition_orders and parsed.changing_rtt)
            self.assertEqual((parsed.frames,parsed.timeout,parsed.move_slot),(650,240,0))
            self.assertEqual(parsed.rtt_ms,[130,475])
            verifier.main(base)
            parsed=prepare.call_args[0][0]
            self.assertFalse(parsed.transition_orders or parsed.changing_rtt or parsed.actor_correction)


class OwnedSpawnTests(unittest.TestCase):
    def fixture(self):
        events = []
        class Handle:
            def Close(self): events.append('handle-close')
        class Process:
            _handle = Handle(); stdin = stdout = stderr = None
            def __init__(self): self.returncode = None
            def poll(self): return self.returncode
            def terminate(self): events.append('terminate-retained'); self.returncode = 92
            def wait(self, timeout): events.append('wait'); return self.returncode
        process = Process()
        class Job:
            def __init__(self, child):
                self.child = child; events.append(('assigned', child._handle))
            def terminate_owned(self): events.append('job-terminate'); self.child.returncode = 92
            def close(self): events.append('job-close')
        def popen(command, **kw):
            self.assertTrue(kw['creationflags'] & verifier.CREATE_SUSPENDED)
            events.append('created-suspended'); return process
        return events, process, Job, popen

    def test_exact_retained_child_is_assigned_before_resume(self):
        events, process, job, popen = self.fixture()
        child, owned = verifier.spawn_owned(['fixture'], job_type=job, popen=popen,
            before_resume=lambda p: events.append(('fresh-check', p._handle)),
            resume_child=lambda p: events.append(('resume', p._handle)))
        self.assertIs(child, process)
        self.assertEqual([e if isinstance(e, str) else e[0] for e in events],
                         ['created-suspended', 'assigned', 'fresh-check', 'resume'])
        self.assertIs(events[1][1], events[2][1]); self.assertIs(events[2][1], events[3][1])

    def test_pre_assignment_failure_terminates_and_reaps_exact_suspended_child(self):
        events, process, _, popen = self.fixture()
        def failed(_): raise RuntimeError('assignment failed')
        with self.assertRaisesRegex(RuntimeError, 'assignment failed'):
            verifier.spawn_owned(['fixture'], job_type=failed, popen=popen,
                resume_child=lambda _: self.fail('must not resume'))
        self.assertEqual(events, ['created-suspended', 'terminate-retained', 'wait', 'handle-close'])

    def test_pre_resume_refusal_closes_job_and_retained_handle(self):
        events, process, job, popen = self.fixture()
        def failed(_): raise RuntimeError('stale diagnostic')
        with self.assertRaisesRegex(RuntimeError, 'stale diagnostic'):
            verifier.spawn_owned(['fixture'], job_type=job, popen=popen, before_resume=failed,
                resume_child=lambda _: self.fail('must not resume'))
        self.assertIn('job-terminate', events); self.assertIn('job-close', events)
        self.assertEqual(events[-1], 'handle-close')


class OwnedJobDrainTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, active=(1,0)):
        events=[];handle=object()
        snapshots=[dict(total=2,active=value,terminated=0) for value in active]
        job=verifier.ObservedJob.__new__(verifier.ObservedJob)
        job.handle=handle;job.forced=False;job.final_accounting=None
        def accounting():
            events.append('accounting')
            value=snapshots.pop(0) if len(snapshots)>1 else snapshots[0]
            return dict(value)
        def terminate(actual, code):
            self.assertIs(actual,handle);self.assertEqual(code,92);events.append('terminate-owned-job')
            snapshots[:]=[dict(total=2,active=0,terminated=1)];return 1
        def physical_close(actual):
            self.assertIs(actual,handle);events.append('physical-close');return 1
        job.accounting=accounting
        job.kernel=SimpleNamespace(TerminateJobObject=terminate,CloseHandle=physical_close)
        clock=SimpleNamespace(value=0.)
        async def sleep(duration):clock.value+=duration;events.append('drain-wait')
        return job,events,clock,sleep

    async def test_successful_real_worker_cleanup_defers_job_close_until_descendants_drain(self):
        from server.worker_client import SimulationWorker
        job,events,clock,sleep=self.fixture()
        class Stream:
            def close(self):events.append('stream-close')
        class Process:
            stdin,stdout,stderr=Stream(),Stream(),Stream()
            def poll(self):return 0
            def wait(self,timeout):events.append('retained-main-wait');return 0
            def terminate(self):raise AssertionError('already-exited child must not be terminated')
        worker=SimulationWorker.__new__(SimulationWorker)
        worker.process=Process();worker.failure=None;worker.close_timeout=.1
        lease=verifier.WorkerJobLease(job,worker);worker._job=lease
        worker._stderr_thread=SimpleNamespace(join=lambda timeout:events.append('stderr-join'))
        worker._io=SimpleNamespace(shutdown=lambda **kw:events.append('io-shutdown'))
        await worker._cleanup()  # Actual production cleanup; no process is spawned.
        self.assertTrue(lease.close_requested);self.assertIsNotNone(job.handle)
        self.assertNotIn('physical-close',events);self.assertFalse(job.forced)
        await verifier.close_owned_job(job,.03,clock=lambda:clock.value,sleep=sleep)
        self.assertIsNone(job.handle);self.assertFalse(job.forced)
        self.assertEqual(job.final_accounting,dict(total=2,active=0,terminated=0))
        self.assertNotIn('terminate-owned-job',events);self.assertIn('drain-wait',events)
        self.assertEqual(events.count('physical-close'),1)

    async def test_abort_immediately_kills_only_retained_job_before_io_cleanup(self):
        for code,failure in ((None,None),(1,None),(0,'invalid worker response')):
            with self.subTest(code=code,failure=failure):
                job,events,_,_=self.fixture((1,))
                worker=SimpleNamespace(process=SimpleNamespace(poll=lambda:code),failure=failure)
                lease=verifier.WorkerJobLease(job,worker);lease.close();lease.close()
                self.assertTrue(job.forced);self.assertIsNone(job.handle)
                self.assertEqual(events.count('terminate-owned-job'),1)
                self.assertEqual(events.count('physical-close'),1)

    async def test_stuck_owned_descendant_exhausts_deadline_then_is_forced(self):
        job,events,clock,sleep=self.fixture((1,))
        await verifier.close_owned_job(job,.03,clock=lambda:clock.value,sleep=sleep)
        self.assertTrue(job.forced);self.assertIsNone(job.handle)
        self.assertEqual(job.final_accounting,dict(total=2,active=0,terminated=1))
        self.assertGreaterEqual(clock.value,.03);self.assertLess(clock.value,.05)
        self.assertEqual(events.count('terminate-owned-job'),1)

    async def test_already_drained_job_closes_without_poll_sleep_or_force(self):
        job,events,clock,sleep=self.fixture((0,))
        await verifier.close_owned_job(job,.03,clock=lambda:clock.value,sleep=sleep)
        self.assertFalse(job.forced);self.assertEqual(clock.value,0)
        self.assertNotIn('drain-wait',events);self.assertNotIn('terminate-owned-job',events)

    async def test_accounting_error_still_closes_retained_kill_on_close_handle(self):
        job,events,clock,sleep=self.fixture((1,))
        def failed():raise RuntimeError('authored Job accounting failed')
        job.accounting=failed
        with self.assertRaisesRegex(RuntimeError,'authored Job accounting failed'):
            await verifier.close_owned_job(job,.03,clock=lambda:clock.value,sleep=sleep)
        self.assertIsNone(job.handle);self.assertEqual(events.count('physical-close'),1)


class RetainedStartupReanalysisTests(unittest.TestCase):
    def fixture(self):
        sources={'parser.py':'a'*64};invocation='b'*64
        plan=dict(scenario='startup',lifecycle='natural',frames=200,expected_matches=2,source_sha256=sources)
        jobs=[dict(index=i,pid=i+10,exit_code=0,reaped=True,assigned_before_resume=True,
            retained_handle_closed=True,natural_game_exit=True,job=dict(total=3,active=0,terminated=0))for i in range(2)]
        previous=dict(passed=False,error="AssertionError('one actual Job-owned movement worker route required')",
            scenario='startup',lifecycle='natural',invocation_sha256=invocation,source_unchanged=True,
            files_unchanged=True,source_sha256_at_start=sources,source_sha256_at_finish=sources,
            forced_cleanup=False,clients=[],game_cleanup=jobs,authority_workers=[dict(exit_code=0,
                assigned_before_resume=True,job=dict(total=2,active=0,terminated=0),forced=False,failure=None)for _ in range(2)],
            cleanup_errors=[dict(step='close private bridge',error='ConnectionResetError: [WinError 64] peer exited')for _ in range(2)],
            matches=[dict(match=str(i)*32,canonical_frames=200,exact_bridge_and_native_authority_receipts=True)for i in (1,2)])
        return previous,plan,invocation

    def test_whole_fresh_reader_keeps_early_route_and_utf8_completed_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fresh.log'
            prefix='[1] Native worker movement route active: pid=42\n[2] Offline initial state: menu\n[3] café\n'
            path.write_bytes(prefix.encode('utf-8')+b'partial\xc3')
            self.assertEqual(verifier.read_fresh_native_log(path),prefix)
            path.write_bytes(b'bad\xff\n')
            with self.assertRaises(UnicodeDecodeError):verifier.read_fresh_native_log(path)
            self.assertEqual(verifier.read_fresh_native_log(Path(directory)/'missing'),'')

    def test_only_known_connection_reset_after_normal_peer_quit_is_classified(self):
        for code in (64,10054):
            error=ConnectionResetError('authored');error.winerror=code
            self.assertTrue(verifier.normal_peer_eof(error,natural=True,exited_zero=True))
            self.assertFalse(verifier.normal_peer_eof(error,natural=False,exited_zero=True))
            self.assertFalse(verifier.normal_peer_eof(error,natural=True,exited_zero=False))
        for error in (OSError('other'),TimeoutError('late'),ConnectionResetError('unclassified')):
            error.winerror=64 if not isinstance(error,ConnectionResetError) else 109
            self.assertFalse(verifier.normal_peer_eof(error,natural=True,exited_zero=True))

    def test_exact_prior_parser_failure_and_natural_jobs_are_required(self):
        previous,plan,invocation=self.fixture()
        self.assertEqual(verifier.startup_failure_scope(previous,plan,invocation),['1'*32,'2'*32])
        for change in ('error','force','source','cleanup','bridge','exit','terminated','passed','scope'):
            old,p,iv=deepcopy(previous),deepcopy(plan),invocation
            if change=='error':old['error']='another unexplained failure'
            elif change=='force':old['forced_cleanup']=True
            elif change=='source':old['source_sha256_at_finish']={}
            elif change=='cleanup':old['cleanup_errors'][0]['error']='OSError: [WinError 64] wrong type'
            elif change=='bridge':old['matches'][0]['exact_bridge_and_native_authority_receipts']=False
            elif change=='exit':old['game_cleanup'][0]['exit_code']=1
            elif change=='terminated':old['authority_workers'][0]['job']['terminated']=1
            elif change=='passed':old['passed']=True
            else:p['scenario']='movement'
            with self.subTest(change=change),self.assertRaises(AssertionError):
                verifier.startup_failure_scope(old,p,iv)

    def test_existing_reanalysis_output_is_never_overwritten_or_launched(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(verifier,'ROOT',Path(directory)),patch.object(verifier.subprocess,'Popen')as popen:
            source=Path(directory)/'local/startup';source.mkdir(parents=True)
            output=source/'reanalysis';output.mkdir();sentinel=output/'verification.json';sentinel.write_text('preserve')
            with self.assertRaisesRegex(AssertionError,'fresh separate'):
                verifier.reanalyze_startup(source,output,expected_failed_report_sha256='a'*64,expected_invocation_sha256='b'*64)
            self.assertEqual(sentinel.read_text(),'preserve');popen.assert_not_called()


class FeelEvidenceTests(unittest.TestCase):
    def fixture(self,unit_type=75):
        match = 'a' * 32
        position = field_uint(1, 8 * 2**32) + field_uint(2, 0) + field_uint(3, 0)
        group = field_uint(1, unit_type) + field_uint(2, 12) + field_packed_uint(3, [91])
        action = field_bytes(1, field_bytes(1, group) + field_bytes(3, field_bytes(3, field_bytes(1, position))))
        body = encode_player_input(encode_identity(1, 'Owned host'), [action])
        common = dict(schema=1, match=match, world=7, entity=91,unit_type=unit_type, incarnation=340, move_id=1)
        def row(event, tick, **fields): return dict(common, event=event, tick_ms=tick, **fields)
        rows = [row('transform', tick, source=verifier.FEEL_CONTRACT['transform_source'], position=[0, 0, 0])
            for tick in (700,800,900,1000,1099)]
        rows += [row('command_created', 1100, original_callback='Uncapped.ExecuteTargetGroundCommand..ctor',
                ability=12, target=[8, 0, 0], action_sha256=verifier.digest(action)),
            row('batch_registered', 1102, sequence=2, speculative_frame=445,
                body_sha256=verifier.digest(body), action_sha256=verifier.digest(action)),
            row('transform', 1130, source=verifier.FEEL_CONTRACT['transform_source'], position=[.1, 0, 0]),
            row('authority_received', 1230, frame=445, action_sha256=verifier.digest(action))]
        worker=[]
        for frame in range(466):
            promoted=frame>=443
            worker.append(dict(schema=1,event='confirmed_native_state',world=7,frame=frame,
                parsed_state_sha256=('a'if frame<443 else 'b'if frame<=445 else 'c')*64,
                confirmed_frontier=445 if 443<=frame<=445 else frame,
                corrections=int(promoted),corrections_delta=int(frame==443),
                replayed_frames_total=8 if promoted else 0,replayed_frames_delta=8 if frame==443 else 0,
                tick_ms=1190 if frame<443 else 1235 if frame<=445 else 1240+frame-446))
        args = dict(match=match, slot=0, commits=[dict(match=match, slot=0, sequence=2, frame=445)],
            raw_bodies={(match, 0, 2): body}, journal=[dict(frame=445, players={0: [action], 1: []})],
            canonical_states={445: 'b' * 64, **{i: 'c' * 64 for i in range(446, 466)}},
            worker_states=worker,bridge_frames=[dict(match=match,frame=445,received_tick_ms=1220)],
            catalog_units={unit_type:{}},entity_abilities={unit_type:{12,14,88}},built_units=[unit_type])
        return rows, args

    def test_authored_full_contract_passes_without_native_execution(self):
        rows, args = self.fixture()
        result = verifier.evaluate_feel(rows, **args)
        self.assertTrue(result['passed']); self.assertEqual(result['continuation_frames'], 20)
        self.assertEqual(result['command_to_visible_ms'], 30)
        self.assertEqual(result['visibility_before_authority_ms'], 100)
        self.assertEqual(result['visibility_before_bridge_ms'], 90)
        self.assertEqual(result['promotion_group_replayed_delta'],8)
        self.assertEqual(result['frontier_row_replayed_delta'],0)
        self.assertEqual(result['frontier_row_index'],445)
        self.assertEqual(result['promotion_group_row_indices'],[443,444,445])
        self.assertIn('decoration only',result['worker_actor_join']['kind'])
        self.assertEqual((result['baseline_samples'],result['baseline_span_ms']),(5,399))
        self.assertAlmostEqual(result['target_distance_reduction'],.1)
        self.assertEqual(result['speculative_minus_canonical_frames'],0)
        self.assertAlmostEqual(result['maximum_transform_sample_displacement']['displacement'],.1)

    def test_actual_opening_unit_types_use_metadata_not_crab_constant(self):
        for unit in (1,6,75):
            rows,args=self.fixture(unit)
            with self.subTest(unit=unit):self.assertTrue(verifier.evaluate_feel(rows,**args)['passed'])

    def test_bad_type_missing_move_or_unbuilt_type_fails(self):
        for change in ('different','unknown','no_move','unbuilt'):
            rows,args=self.fixture()
            if change=='different':
                for row in rows:row['unit_type']=1
                args.update(catalog_units={1:{}},entity_abilities={1:{12}},built_units=[1])
            elif change=='unknown':args['catalog_units']={}
            elif change=='no_move':args['entity_abilities']={75:{14}}
            else:args['built_units']=[1]
            with self.subTest(change=change),self.assertRaises(AssertionError):
                verifier.evaluate_feel(rows,**args)

    def test_phase9_is_recorded_red_despite_visible_motion_and_native_parity(self):
        rows,args=self.fixture();rows[6]['speculative_frame']=454
        result=verifier.evaluate_feel(rows,**args)
        self.assertFalse(result['passed']);self.assertEqual(result['missing_gates'],['command_phase'])
        self.assertEqual(result['speculative_minus_canonical_frames'],9)
        self.assertEqual(result['continuation_frames'],20)
        for delta in (-1,1):
            rows[6]['speculative_frame']=445+delta
            self.assertTrue(verifier.evaluate_feel(rows,**args)['passed'])

    def test_accepted_event_is_not_a_second_commit_and_build_parser_uses_real_format(self):
        rows,args=self.fixture()
        args['commits'][0]['event']='command_batch_committed'
        args['commits'].append(dict(args['commits'][0],event='command_batch_accepted'))
        self.assertTrue(verifier.evaluate_feel(rows,**args)['passed'])
        line='[640403578] LAN NORMAL BUILD smoke frame300 slot0 army0 HQ0 deckSlot0 unitType1 ability34 cost=(50,0) prerequisite=1 queued=1 commandQueueDelta=1 presentedFrame=293'
        self.assertEqual(verifier.normal_build_units(line,0),[1])
        self.assertEqual(verifier.normal_build_units(line,1),[])

    def test_no_feel_rows_reports_missing_gates_instead_of_pacing_pass(self):
        _, args = self.fixture()
        args['worker_states']=None
        result = verifier.evaluate_feel([], **args)
        self.assertFalse(result['passed'])
        self.assertEqual(set(result['missing_gates']), set(verifier.FEEL_CONTRACT['events'])|
            {'confirmed_state','continuation_state'})

    def test_worker_position_or_after_authority_transform_is_not_visible_prediction(self):
        for changes in (dict(source='native SimFrame.position'), dict(tick_ms=1230),dict(tick_ms=1225)):
            rows, args = self.fixture(); rows[7].update(changes)
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                verifier.evaluate_feel(rows, **args)

    def test_wrong_actor_replayed_intent_or_target_is_rejected(self):
        for index, changes in ((7, dict(entity=92)), (7, dict(incarnation=0)),
                               (5, dict(target=[9, 0, 0])), (6, dict(body_sha256='0' * 64))):
            rows, args = self.fixture(); rows[index].update(changes)
            with self.subTest(index=index, changes=changes), self.assertRaises(AssertionError):
                verifier.evaluate_feel(rows, **args)

    def test_canonical_loss_duplicate_or_wrong_commit_is_rejected(self):
        rows, args = self.fixture()
        for changed in ('duplicate', 'loss', 'wrong_frame'):
            actual = deepcopy(args)
            if changed == 'duplicate': actual['journal'][0]['players'][0] *= 2
            elif changed == 'loss': actual['journal'][0]['players'][0].clear()
            else: actual['commits'][0]['frame'] += 1
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                verifier.evaluate_feel(rows, **actual)

    def test_missing_reference_none_hash_or_noncontiguous_tail_never_passes(self):
        for changed in ('missing', 'none', 'tail', 'different'):
            rows, args = self.fixture()
            if changed == 'missing': args['canonical_states'].pop(445)
            elif changed == 'none': args['canonical_states'][445] = None; args['worker_states'][445]['parsed_state_sha256'] = None
            elif changed == 'tail': args['worker_states'][-1]['frame'] += 1
            elif changed == 'different': args['worker_states'][-1]['parsed_state_sha256'] = '0' * 64
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                verifier.evaluate_feel(rows, **args)

    def test_perfect_own_confirmation_requires_no_unnecessary_replay(self):
        rows,args=self.fixture()
        for actual in args['worker_states']:
            for key in ('corrections','corrections_delta','replayed_frames_total','replayed_frames_delta'):actual[key]=0
        result=verifier.evaluate_feel(rows,**args)
        self.assertTrue(result['passed']);self.assertFalse(result['correction_required'])
        self.assertEqual(result['promotion_group_replayed_delta'],0)

    def test_bridge_missing_duplicate_wrong_frame_or_invalid_order_cannot_pass(self):
        for changed in ('missing','duplicate','wrong_frame','early','late'):
            rows,args=self.fixture();bridge=args['bridge_frames']
            if changed=='missing':bridge.clear()
            elif changed=='duplicate':bridge.append(dict(bridge[0]))
            elif changed=='wrong_frame':bridge[0]['frame']+=1
            elif changed=='early':bridge[0]['received_tick_ms']=1101
            else:bridge[0]['received_tick_ms']=1231
            with self.subTest(changed=changed),self.assertRaises(AssertionError):
                verifier.evaluate_feel(rows,**args)

    def test_replay_group_must_wholly_follow_matching65(self):
        rows,args=self.fixture()
        args['worker_states'][443]['tick_ms']=1229
        with self.assertRaisesRegex(AssertionError,'no actual confirmed native replay group'):
            verifier.joined_worker_evidence(args['worker_states'],world=7,authority=rows[8],
                canonical_states=args['canonical_states'],require_replay=True)

    def test_actor_diagnostics_cannot_replace_real_worker_state_file(self):
        rows,args=self.fixture();args['worker_states']=None
        result=verifier.evaluate_feel(rows,**args)
        self.assertEqual(result['missing_gates'],['confirmed_state','continuation_state'])
        fake=dict(rows[0],event='corrected_state',confirmed_frame=445,parsed_state_sha256='b'*64,replayed_frames=8)
        with self.assertRaisesRegex(AssertionError,'unknown feel'):
            verifier.feel_rows(verifier.FEEL_PREFIX+json.dumps(fake))

    def test_idle_moving_baseline_or_wrong_direction_cannot_explain_prediction(self):
        for change in ('few','short','moving','away','sideways','no_closer'):
            rows,args=self.fixture()
            if change=='few':rows.pop(0)
            elif change=='short':
                for index in range(5):rows[index]['tick_ms']=1060+index*9
            elif change=='moving':rows[0]['position']=[.031,0,0]
            elif change=='away':rows[7]['position']=[-.1,0,0]
            elif change=='sideways':rows[7]['position']=[0,.1,0]
            else:rows[7]['position']=[.01,1,0]
            with self.subTest(change=change),self.assertRaises(AssertionError):
                verifier.evaluate_feel(rows,**args)

    def test_feel_parser_rejects_unknown_schema_and_nonfinite_clock(self):
        rows, _ = self.fixture()
        log = '\n'.join('[100] ' + verifier.FEEL_PREFIX + json.dumps(r) for r in rows)
        self.assertEqual(verifier.feel_rows(log), rows)
        for change in (dict(schema=2), dict(tick_ms=float('nan')), dict(world=0)):
            row = dict(rows[0], **change)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                verifier.feel_rows(verifier.FEEL_PREFIX + json.dumps(row))


class IndependentRemoteCorrectionTests(unittest.TestCase):
    def fixture(self):
        own,base=FeelEvidenceTests().fixture()
        match=base['match'];remote,_=FeelEvidenceTests().fixture(6)
        position=field_uint(1,8*2**32)+field_uint(2,0)+field_uint(3,0)
        group=field_uint(1,6)+field_uint(2,12)+field_packed_uint(3,[92])
        action=field_bytes(1,field_bytes(1,group)+field_bytes(3,field_bytes(3,field_bytes(1,position))))
        body=encode_player_input(encode_identity(2,'Owned guest'),[action])
        for row in remote:
            row.update(world=9,entity=92,tick_ms=row['tick_ms']+180)
            if 'action_sha256'in row:row['action_sha256']=verifier.digest(action)
        remote[6].update(body_sha256=verifier.digest(body),speculative_frame=465)
        remote[8].update(frame=465,tick_ms=1350)
        worker=base['worker_states']
        # Perfect own confirmation has no replay. Only a later real remote input
        # creates a new promotion-group correction on the subject client.
        for row in worker:
            for key in ('corrections','corrections_delta','replayed_frames_total','replayed_frames_delta'):row[key]=0
        for frame in range(463,486):
            row=dict(worker[-1])if frame>=466 else worker[frame]
            row.update(frame=frame,confirmed_frontier=465 if frame<=465 else frame,
                corrections=1,corrections_delta=int(frame==463),replayed_frames_total=8,
                replayed_frames_delta=8 if frame==463 else 0,tick_ms=1305 if frame<=465 else 1310+frame-466,
                parsed_state_sha256=('c'if frame<=465 else'd')*64)
            if frame>=466:worker.append(row)
        canonical=dict(base['canonical_states'],**{})
        canonical.update({frame:'d'*64 for frame in range(466,486)})
        base['raw_bodies'][match,1,2]=body
        base['commits'].append(dict(match=match,slot=1,sequence=2,frame=465))
        base['journal'].append(dict(frame=465,players={0:[],1:[action]},input_sha256='a'*64))
        receipt=dict(schema=1,world=7,match=match,frame=465,tick_ms=1300,
            canonical_sha256='f'*64,wire_sha256='e'*64)
        args=dict(match=match,slot=1,host_world=7,host_authorities=[receipt],host_worker_states=worker,
            host_bridge_frames=[dict(match=match,frame=465,received_tick_ms=1295,payload_sha256='e'*64)],
            canonical_payloads={465:'e'*64},canonical_states=canonical,commits=base['commits'],
            raw_bodies=base['raw_bodies'],journal=base['journal'],catalog_units={6:{}},entity_abilities={6:{12}},built_units=[6])
        return own,base,remote,args

    def test_perfect_own_and_separate_remote_native_replay_are_both_qualified(self):
        own,base,remote,args=self.fixture()
        subject=verifier.evaluate_feel(own,**base)
        result=verifier.evaluate_remote_correction(remote,**args)
        self.assertTrue(subject['passed']);self.assertEqual(subject['promotion_group_replayed_delta'],0)
        self.assertTrue(result['passed']);self.assertTrue(result['correction_required'])
        self.assertEqual(result['confirmed_state_frame'],465)
        self.assertEqual(result['promotion_group_replayed_delta'],8)
        self.assertEqual(result['continuation_frames'],20)
        self.assertEqual((result['host_world']if 'host_world'in result else result['actor_join']['host_world']),7)

    def test_remote_replay_missing_or_before_receipt_cannot_substitute(self):
        for change in ('none','early'):
            _,_,remote,args=self.fixture()
            if change=='none':
                for row in args['host_worker_states']:
                    for key in ('corrections','corrections_delta','replayed_frames_total','replayed_frames_delta'):row[key]=0
            else:args['host_authorities'][0]['tick_ms']=1306
            with self.subTest(change=change),self.assertRaises(AssertionError):
                verifier.evaluate_remote_correction(remote,**args)

    def test_remote_binding_missing_duplicate_wrong_world_wire_commit_or_state_fails(self):
        for change in ('missing','duplicate','world','wire','bridge','commit','state','action'):
            _,_,remote,args=self.fixture()
            if change=='missing':args['host_authorities'].clear()
            elif change=='duplicate':args['host_authorities']*=2
            elif change=='world':args['host_authorities'][0]['world']=9
            elif change=='wire':args['host_authorities'][0]['wire_sha256']='0'*64
            elif change=='bridge':args['host_bridge_frames'][0]['received_tick_ms']=1301
            elif change=='commit':args['commits'][-1]['frame']=466
            elif change=='state':args['host_worker_states'][-1]['parsed_state_sha256']='0'*64
            else:args['journal'][-1]['players'][1].clear()
            with self.subTest(change=change),self.assertRaises(AssertionError):
                verifier.evaluate_remote_correction(remote,**args)

    def test_generic_receipt_parser_is_strict_and_keeps_wire_and_worker_hash_distinct(self):
        _,_,_,args=self.fixture();row=args['host_authorities'][0]
        log='[1300] MOVEMENT AUTHORITY '+json.dumps(row)
        self.assertEqual(verifier.authority_rows(log),[row])
        for change in ('duplicate','wire','frame','field','schema','world','clock'):
            actual=dict(row)
            if change=='duplicate':text=log+'\n'+log
            else:
                if change=='wire':actual['wire_sha256']=None
                elif change=='frame':actual['frame']=-1
                elif change=='field':actual['fake']=1
                elif change=='schema':actual['schema']=2
                elif change=='world':actual['world']=0
                else:actual['tick_ms']=True
                text='MOVEMENT AUTHORITY '+json.dumps(actual)
            with self.subTest(change=change),self.assertRaises(AssertionError):verifier.authority_rows(text)


class WorkerStateEvidenceTests(unittest.TestCase):
    def fixture(self):
        return FeelEvidenceTests().fixture()[1]['worker_states']

    def test_closed_file_roundtrip_and_sequential_rematch_world(self):
        rows=self.fixture()
        rematch=dict(rows[0],world=8,tick_ms=1300)
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'canonical-state.jsonl'
            path.write_text(''.join(json.dumps(row)+'\n'for row in rows+[rematch]),encoding='utf-8')
            self.assertEqual(verifier.read_worker_states(path),rows+[rematch])
            path.write_text(json.dumps(rows[0]),encoding='utf-8')
            with self.assertRaisesRegex(AssertionError,'partial'):
                verifier.read_worker_states(path)

    def test_duplicate_gap_bad_hash_counter_clock_or_group_are_rejected(self):
        for change in ('duplicate','gap','hash','counter','delta','clock','group','frontier','negative','bool','field'):
            rows=self.fixture()
            if change=='duplicate':rows.insert(5,dict(rows[4]))
            elif change=='gap':rows.pop(5)
            elif change=='hash':rows[5]['parsed_state_sha256']='b'*63
            elif change=='counter':rows[445]['replayed_frames_total']=7
            elif change=='delta':rows[444]['replayed_frames_delta']=8
            elif change=='clock':rows[445]['tick_ms']=1234
            elif change=='group':rows.pop(445)
            elif change=='frontier':rows[5]['confirmed_frontier']=4
            elif change=='negative':rows[5]['corrections']=-1
            elif change=='bool':rows[5]['frame']=True
            else:rows[5]['invented']=0
            with self.subTest(change=change),self.assertRaises(AssertionError):
                verifier.validate_worker_states(rows)

    def test_wrong_rpc_world_and_interleaved_world_cannot_be_actor_joined(self):
        rows,args=FeelEvidenceTests().fixture()
        for actual in args['worker_states']:actual['world']=8
        with self.assertRaisesRegex(AssertionError,'lacks selected RPC world'):
            verifier.evaluate_feel(rows,**args)
        actual=self.fixture();actual.insert(2,dict(actual[0],world=8))
        with self.assertRaisesRegex(AssertionError,'interleaved/reused'):
            verifier.validate_worker_states(actual)


class AuthorityDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_full_snapshot_replaces_only_state_and_last_state(self):
        from server.worker_client import FrameResult
        calls=[];old=FrameResult(7,350,dict(frame=7,viewer=31,summary=True))
        actual=dict(frame=7,viewer=31,entities=[dict(entity=91,health=40)],raw_sha256='x')
        async def frame(actions,dt_ms):calls.append(('step',actions,dt_ms));return old
        async def state(viewer,**kwargs):calls.append(('state',viewer,kwargs));return actual
        worker=SimpleNamespace(state=state,last_state=old.state)
        result=await verifier.full_authority_frame(worker,frame,b'canonical',50)
        self.assertEqual((result.frame,result.game_time_seconds),(7,350))
        self.assertIs(result.state,actual);self.assertIs(worker.last_state,actual)
        self.assertIsNot(result,old)
        self.assertEqual(calls,[('step',b'canonical',50),('state',31,dict(include_entities=True))])

    async def test_wrong_actual_frame_cannot_replace_authority_result(self):
        from server.worker_client import FrameResult
        old=FrameResult(7,350,{});worker=SimpleNamespace(last_state=old.state)
        async def frame(actions,dt_ms):return old
        async def state(*args,**kwargs):return dict(frame=6,viewer=31,entities=[])
        worker.state=state
        with self.assertRaisesRegex(AssertionError,'actual frame'):
            await verifier.full_authority_frame(worker,frame,b'canonical')
        self.assertIs(worker.last_state,old.state)


class PredictedTimingCutoffTests(unittest.TestCase):
    @staticmethod
    def prefix(arrivals=600, applied=600):
        return ([dict(event='arrival', frame=n) for n in range(arrivals)] +
                [dict(event='apply', frame=n) for n in range(applied)])

    def check(self, rows, **kwargs):
        return verifier.timing_prefix_counts(rows, 600, prediction=True,
            complete_delivery_proven=True, **kwargs)

    def test_actual_slow_peer_tail_is_reported_without_synthetic_timings(self):
        result = self.check(self.prefix(593))
        self.assertEqual(result['trace_arrival_frames'], 593)
        self.assertEqual(result['missing_trailing_arrival_timings'], 7)
        self.assertEqual(result['synthetic_timing_rows'], 0)

    def test_all_timing_rows_remain_accepted(self):
        self.assertEqual(self.check(self.prefix())['missing_trailing_arrival_timings'], 0)

    def test_missing_middle_arrival_cannot_be_reclassified(self):
        rows = self.prefix(593)
        rows = [r for r in rows if r != dict(event='arrival', frame=120)]
        with self.assertRaisesRegex(AssertionError, 'noncontiguous'):
            self.check(rows)

    def test_tail_beyond_prediction_budget_refused(self):
        with self.assertRaisesRegex(AssertionError, 'budget'):
            self.check(self.prefix(587))

    def test_missing_physical_frame_refused(self):
        with self.assertRaisesRegex(AssertionError, 'physical'):
            self.check(self.prefix(593, 599))

    def test_complete_independent_delivery_is_mandatory(self):
        with self.assertRaisesRegex(AssertionError, 'independent complete'):
            verifier.timing_prefix_counts(self.prefix(593), 600, prediction=True,
                complete_delivery_proven=False)

    def test_ordinary_path_still_requires_every_arrival_timing(self):
        with self.assertRaisesRegex(AssertionError, 'budget'):
            verifier.timing_prefix_counts(self.prefix(593), 600, prediction=False,
                complete_delivery_proven=True)


class ActorCorrectionFixtureTests(unittest.TestCase):
    """Authored positive/negative witnesses, never a native actor acceptance claim."""
    def setUp(self):
        self.match = 'c' * 32
        self.metadata = verifier.actor_fixture_metadata()
        names = ['original_hq_selection_established', 'original_dead_hq_retained',
                 'original_hq_restored_and_admitted', 'hq_selection_correction_passed']
        self.rows = [dict(schema=1, event=name, world=2, match=self.match, entity=5, army=1, unit_type=3,
            frame=frame, tick_ms=tick, original_actor='000001A0', current_actor=pointer,
            focus_retained_at_death=False, original_focus_supported=False,
            original_group_supported=False, physicalUI=False)
            for name, frame, tick, pointer in zip(names, (130, 156, 157, 159),
                (1000, 2100, 2200, 2300), ('000001A0', '000001A0', '000002B0', '000002B0'))]
        position = b''.join(field_uint(n, int(value * 2**32) & (2**64-1))
            for n, value in enumerate(self.metadata['target'], 1))
        group = field_uint(1, 1) + field_uint(2, 12) + field_packed_uint(3, [10])
        self.action = field_bytes(1, field_bytes(1, group) +
            field_bytes(3, field_bytes(3, field_bytes(1, position))))
        self.body = encode_player_input(encode_identity(1, 'Owned attacker'), [self.action])
        self.order = dict(schema=1, event='original_escape_move', world=1, match=self.match, army=0,
            entity=10, unit_type=1, ability=12, frame=152, tick_ms=2000,
            action_sha256=verifier.digest(self.action), originalCtor=True, physicalUI=False)
        self.commits = [dict(event='command_batch_committed', match=self.match, slot=0,
                            sequence=2, frame=153, probe_tick_ms=2070)]
        self.authority = dict(schema=1, world=2, match=self.match, frame=153, tick_ms=2150,
                              canonical_sha256='a'*64, wire_sha256='b'*64)
        self.bridge = [dict(match=self.match, frame=153, received_tick_ms=2140, payload_sha256='b'*64)]
        self.journal = [dict(frame=153, players={0:[self.action], 1:[]})]
        self.worker = [dict(schema=1, event='confirmed_native_state', world=2, frame=frame,
            parsed_state_sha256='d'*64, confirmed_frontier=frame,
            corrections=int(frame>=153), corrections_delta=int(frame==153),
            replayed_frames_total=3 if frame>=153 else 0, replayed_frames_delta=3 if frame==153 else 0,
            tick_ms=1000+frame*5 if frame<153 else 2160+(frame-153)*10) for frame in range(174)]
        self.states = {frame:'d'*64 for frame in range(176)}
        self.native = [dict(frame=frame, parsed_state_sha256='d'*64,
            core=dict(id=5, army=1, type=3, max_health=100, current_damage=0 if frame<144 else 50),
            attacker=dict(id=10, army=0, type=1), game_state=dict(complete=False)) for frame in range(130,176)]
        self.pool = ('[2180] Prediction actor retired: world=2 match='+self.match+
            ' entity=5 actor=000001A0 oldType=3 oldArmy=1 correctedType=3 correctedArmy=1 '
            'selectionBatch=1 releasedMulticast=1 originalPool=1 oldMembershipRemoved=1 retainedHQ=1')
        self.focus = ''

    def attacker_log(self):
        return ('ACTOR ORDER '+json.dumps(self.order)+'\n'
            'Movement local batch registered: sequence=2 speculativeFrame=153 tick=2001 match='+self.match+'\n'
            'Original command batch submitted: match='+self.match+' sequence=2 actions=1 bytes='+str(len(self.body))+
            ' body_sha256='+verifier.digest(self.body)+' sendTick=2002 sourceNextFrame=150\n')

    def victim_log(self):
        return ('\n'.join('ACTOR CORRECTION '+json.dumps(row) for row in self.rows)+'\n'+
                'MOVEMENT AUTHORITY '+json.dumps(self.authority)+'\n'+self.pool+'\n'+self.focus)

    def evaluate(self, **changes):
        args = dict(attacker_log=self.attacker_log(), match=self.match, commits=self.commits,
            raw_bodies={(self.match,0,2):self.body}, journal=self.journal, bridge_frames=self.bridge,
            canonical_payloads={153:'b'*64}, canonical_states=self.states, native_states=self.native,
            worker_states=self.worker)
        args.update(changes)
        return verifier.actor_correction_evidence(self.victim_log(), **args)

    def test_original_move_drives_actual_death_retraction_and_replay_twenty(self):
        result = self.evaluate()
        self.assertTrue(result['passed'])
        self.assertEqual(result['escape']['canonical_commit_frame'], 153)
        self.assertEqual(result['promotion_group_replayed_delta'], 3)
        self.assertEqual(result['continuation_frames'], 20)
        self.assertFalse(result['repair_focus_cancellation_exercised'])
        self.assertFalse(result['control_group_cleanup_exercised'])
        self.assertTrue(result['hq_selection_retraction_exercised'])
        self.assertIn('not exercised', result['focus_cancellation_scope'])
        self.assertNotIn('actual_packet_hold', result)

    def coalesced_promotion(self):
        self.worker[153]['confirmed_frontier'] = 154
        self.worker[154]['confirmed_frontier'] = 154
        row = dict(self.worker[-1], frame=174, confirmed_frontier=174, tick_ms=2370)
        self.worker.append(row)

    def test_canonical_move_row_in_real_coalesced_promotion_group_is_accepted(self):
        self.coalesced_promotion()
        result = self.evaluate()
        self.assertTrue(result['passed'])
        self.assertEqual(result['confirmed_state_frame'],154)
        self.assertEqual(result['promotion_group_row_indices'],[153,154])
        self.assertEqual(result['promotion_group_replayed_delta'],3)

    def test_later_replay_group_without_canonical_move_row_cannot_explain_restore(self):
        self.coalesced_promotion()
        self.worker[153].update(confirmed_frontier=153, corrections=0, corrections_delta=0,
                               replayed_frames_total=0, replayed_frames_delta=0)
        self.worker[154].update(corrections_delta=1, replayed_frames_delta=3)
        with self.assertRaisesRegex(AssertionError,'own native replay group'): self.evaluate()

    def test_coalesced_replay_with_other_commands_cannot_be_attributed_to_escape(self):
        self.coalesced_promotion()
        other = field_bytes(5,field_bytes(1,b''))
        self.journal.append(dict(frame=154,players={0:[],1:[other]}))
        with self.assertRaisesRegex(AssertionError,'group input'): self.evaluate()

    def test_original_hq_cannot_claim_focus_or_control_group_support(self):
        for key in ('original_focus_supported','original_group_supported','focus_retained_at_death'):
            self.rows[1][key] = True
            with self.subTest(key=key),self.assertRaisesRegex(AssertionError, 'eligibility'): self.evaluate()
            self.rows[1][key] = False

    def test_core_focus_cancellation_claim_is_rejected(self):
        self.focus = '[2170] Prediction actor focus cancelled: group=4 affectedActorOnly=1 originalAPI=1'
        with self.assertRaisesRegex(AssertionError, 'cannot claim'): self.evaluate()

    def test_original_actor_address_can_be_reused_by_original_pool(self):
        for row in self.rows: row['current_actor'] = row['original_actor']
        self.assertTrue(self.evaluate()['passed'])

    def test_concede_cannot_replace_original_move(self):
        self.order['ability'] = 8
        with self.assertRaisesRegex(AssertionError, 'identity/frame'): self.evaluate()

    def test_missing_duplicate_and_wrong_source_order_fail(self):
        for change in ('missing','duplicate','entity','army','type','physical_ui','physical_frame'):
            with self.subTest(change=change):
                original = deepcopy(self.order)
                log = self.attacker_log()
                if change=='missing': log = '\n'.join(log.splitlines()[1:])
                elif change=='duplicate': log += 'ACTOR ORDER '+json.dumps(self.order)+'\n'
                else:
                    key = dict(type='unit_type', physical_ui='physicalUI', physical_frame='frame').get(change, change)
                    self.order[key] = True if change=='physical_ui' else 9
                    log = self.attacker_log()
                with self.assertRaises(AssertionError): self.evaluate(attacker_log=log)
                self.order = original

    def test_wrong_body_hash_missing67_and_missing72_fail(self):
        for change in ('body','67','72'):
            log = self.attacker_log()
            if change=='body': log = log.replace(verifier.digest(self.body), 'e'*64)
            else: log = '\n'.join(line for line in log.splitlines() if
                ('Movement local batch registered:' if change=='67' else 'Original command batch submitted:') not in line)
            with self.subTest(change=change), self.assertRaises(AssertionError): self.evaluate(attacker_log=log)

    def test_missing_and_duplicate_exact72_action_fail(self):
        with self.assertRaisesRegex(AssertionError, 'submitted72'): self.evaluate(raw_bodies={})
        with self.assertRaisesRegex(AssertionError, 'submitted72'):
            self.evaluate(raw_bodies={(self.match,0,2):self.body,(self.match,0,3):self.body})

    def test_rehashed_wrong_source_ability_queue_or_target_still_fails(self):
        from server.protobuf_wire import get_bytes, replace_fields
        original = self.action
        for change in ('ability','entity','queued','target'):
            execute = get_bytes(original,1)
            if change in ('ability','entity'):
                group = get_bytes(execute,1)
                group = replace_fields(group, {2:[field_uint(2,8)]} if change=='ability' else
                                             {3:[field_packed_uint(3,[11])]})
                execute = replace_fields(execute,{1:[field_bytes(1,group)]})
            elif change=='queued': execute = replace_fields(execute,{2:[field_uint(2,1)]})
            else:
                position = field_uint(1,8*2**32)
                execute = replace_fields(execute,{3:[field_bytes(3,field_bytes(3,field_bytes(1,position)))]})
            self.action = field_bytes(1,execute)
            self.body = encode_player_input(encode_identity(1,'Owned attacker'),[self.action])
            self.order['action_sha256'] = verifier.digest(self.action)
            self.journal = [dict(frame=153,players={0:[self.action],1:[]})]
            with self.subTest(change=change),self.assertRaisesRegex(AssertionError,'source/ability|target differs'):
                self.evaluate()

    def test_commit_must_be_once_before_death_in_qualified_margin(self):
        for frame in (151,155,156,700):
            self.commits[0]['frame'] = frame
            with self.subTest(frame=frame), self.assertRaisesRegex(AssertionError, 'margin'): self.evaluate()
        self.commits[0]['frame'] = 153; self.commits.append(dict(self.commits[0]))
        with self.assertRaisesRegex(AssertionError, 'margin'): self.evaluate()

    def test_commit_and_canonical_action_must_agree_without_duplicate(self):
        for journal in ([dict(frame=154, players={0:[self.action],1:[]})],
                        self.journal+self.journal, [dict(frame=153, players={0:[],1:[self.action]})]):
            with self.subTest(journal=journal), self.assertRaisesRegex(AssertionError, 'journal'):
                self.evaluate(journal=journal)

    def test_death_must_precede_both_actual_receipts(self):
        for receipt in (self.authority,self.bridge[0]):
            key = 'tick_ms' if receipt is self.authority else 'received_tick_ms'
            original = receipt[key]; receipt[key] = 2090
            with self.assertRaisesRegex(AssertionError, 'death must precede'): self.evaluate()
            receipt[key] = original
        self.rows[2]['tick_ms'] = 2145
        with self.assertRaisesRegex(AssertionError, 'restoration must follow'): self.evaluate()

    def test_different_peer_lead_can_present_future_death_before_order_creation(self):
        self.rows[1]['tick_ms'] = 1990
        self.assertTrue(self.evaluate()['passed'])

    def test_wrong_native65_or_bridge_payload_cannot_pass(self):
        self.bridge[0]['payload_sha256'] = 'f'*64
        with self.assertRaisesRegex(AssertionError, 'wire binding'): self.evaluate()

    def test_missing_focus_at_death_witness_cannot_be_inferred(self):
        self.rows[1].pop('focus_retained_at_death')
        with self.assertRaisesRegex(AssertionError, 'focus-at-death'): self.evaluate()

    def test_wrong_world_entity_army_type_or_pointer_fail(self):
        for key, value in (('world',3),('entity',0),('army',0),('unit_type',1),('current_actor','0')):
            old=self.rows[2][key];self.rows[2][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(AssertionError, 'binding'): self.evaluate()
            self.rows[2][key]=old

    def test_missing_restoration_and_dead_prediction_cannot_pass(self):
        self.rows.pop(2)
        with self.assertRaisesRegex(AssertionError, 'incomplete'): self.evaluate()

    def test_actual_native_canonical_survival_not_fixture_metadata_is_required(self):
        for change in ('missing','dead','army','hash','health'):
            rows=deepcopy(self.native)
            if change=='missing': rows.pop()
            elif change=='dead': rows[25]['game_state']['complete']=True
            elif change=='army': rows[25]['core']['army']=0
            elif change=='health': rows[25]['core']['current_damage']=100
            else: rows[25]['parsed_state_sha256']='f'*64
            with self.subTest(change=change),self.assertRaises(AssertionError): self.evaluate(native_states=rows)

    def test_real_replay_and_twenty_matching_continuations_required(self):
        for change in ('no_replay','late_unrelated_replay','wrong_tail','missing_tail'):
            rows=deepcopy(self.worker)
            if change=='no_replay':
                for row in rows: row.update(replayed_frames_delta=0,replayed_frames_total=0)
            elif change=='late_unrelated_replay':
                for row in rows[153:]: row['tick_ms']+=100
            elif change=='wrong_tail': rows[170]['parsed_state_sha256']='f'*64
            else: rows.pop()
            with self.subTest(change=change),self.assertRaises(AssertionError): self.evaluate(worker_states=rows)

    def test_wrong_pool_lifetime_or_unproven_retained_path_cannot_pass(self):
        for change in ('actor=000001A0','originalPool=1','retainedHQ=1','oldArmy=1'):
            old=self.pool;self.pool=self.pool.replace(change,change.split('=')[0]+'=0')
            with self.subTest(change=change),self.assertRaisesRegex(AssertionError, 'pool'):self.evaluate()
            self.pool=old


class ActorTemplateRoutingTests(unittest.TestCase):
    def test_only_explicit_actor_flag_transforms_template_before_match_build(self):
        original, fixture = object(), object()
        with patch('tools.prediction_actor_fixture.make_template',return_value=fixture) as transform:
            self.assertIs(verifier.match_template(original,Path('assets'),actor_correction=False),original)
            transform.assert_not_called()
            self.assertIs(verifier.match_template(original,Path('assets'),actor_correction=True),fixture)
            transform.assert_called_once_with(original,Path('assets'))

    def test_actor_flag_goes_to_both_clients_and_no_packet_hold_flag(self):
        plan=dict(scenario='movement',lifecycle='natural',frames=600,move_slot=0,surrender_frame=700,
            module_root='app',actor_correction=True,
            files={name:dict(path=name)for name in ('python','heap_helper','cooperative')})
        for index in (0,1):
            args=verifier.command_extra(plan,index,Path('run'))
            self.assertIn('-prediction-actor-correction-smoke',args)
            self.assertFalse(any('hold' in arg or 'concede' in arg.lower()for arg in args))
        plan['actor_correction']=False
        self.assertNotIn('-prediction-actor-correction-smoke',verifier.command_extra(plan,1,Path('run')))


class ChangingRttControllerTests(unittest.TestCase):
    def setUp(self):
        self.match='a'*32;self.clock=1000
        test=self
        class Relay:
            def __init__(self):self.changes=[]
            def set_rtt_ms(self,rtt,*,tick):
                self.changes.append(rtt)
                return dict(revision=len(self.changes),configured_rtt_ms=rtt,
                    requested_tick_ms=tick(),effective_tick_ms=tick(),
                    requested_perf_counter_ns=test.clock*1_000_000,effective_perf_counter_ns=test.clock*1_000_000)
        self.relay=Relay()
        self.control=verifier.ChangingRttController(lambda:self.clock,lambda:self.clock*1_000_000)
        self.control.begin(self.match,self.relay)
        self.rows=[self.pose(1400,0,438),self.command(),self.pose(1650,1,449),self.pose(1700,2,450)]
        self.rtt=''

    def common(self,event,tick,**fields):
        return dict(schema=1,event=event,match=self.match,world=7,entity=91,unit_type=1,incarnation=1,
                    move_id=1,tick_ms=tick,**fields)

    def command(self):
        return self.common('command_created',1500,original_callback='Uncapped.ExecuteTargetGroundCommand..ctor',
                           ability=12,target=[48,0,0],action_sha256='a'*64)

    def pose(self,tick,x,frame):
        return self.common('transform',tick,source=verifier.FEEL_CONTRACT['transform_source'],position=[x,0,0],
                           presented_frame=frame,completed_frame=frame-1)

    @staticmethod
    def sample(request,sent,*,raw=475,estimate=475,generation=1,accepted=1,refresh=1,kind=55):
        return (f'[{sent}] Movement RTT refresh sent: generation={generation} request={request} sent_us={sent*1000} wire_bytes=9 interval_us=2000000\n'
            f'[{sent+raw}] Movement RTT sample: generation={generation} kind={kind} request={request} sent_us={sent*1000} '
            f'received_us={(sent+raw)*1000} accepted={accepted} min_us={estimate*1000} samples=2 refresh={refresh} '
            'directory_bytes_seen=168 BA_RESURRECTION_MOVEMENT_PACING_V1\n')

    def update(self,tick):
        self.clock=tick
        log='\n'.join('MOVEMENT FEEL '+json.dumps(row)for row in self.rows)+'\n'+self.rtt+getattr(self,'extra_log','')
        self.control.update(log,self.relay)

    def rise(self):
        self.update(1700);self.assertEqual(self.relay.changes,[130,475])

    def fall_ready(self):
        self.rtt=self.sample(1,1800,estimate=130)+self.sample(2,3800)
        self.rows.extend([self.pose(5600,19,528),self.pose(5700,20,530)])

    def test_real450_pose_then_four_seconds_two_own_high_acks_then_low_recovery(self):
        self.rows[-1]['presented_frame']=449;self.update(1690)
        self.assertEqual(self.relay.changes,[130])
        self.rows[-1]['presented_frame']=450;self.rise();self.fall_ready()
        self.update(5699);self.assertEqual(self.relay.changes,[130,475])
        self.update(5700);self.assertEqual(self.relay.changes,[130,475,130])
        self.assertEqual(self.control.worlds[-1]['stage'],'low')
        self.rtt+=self.sample(3,5800,raw=130,estimate=130);self.update(6000)
        self.assertEqual(self.control.worlds[-1]['stage'],'complete')
        self.assertEqual(self.control.worlds[-1]['high_held_perf_ns'],4_000_000_000)

    def test_configured_high_alone_or_one_sample_does_not_prove_acquisition(self):
        self.rise();self.fall_ready();self.rtt=self.sample(1,1800)
        self.update(5700);self.assertEqual(self.relay.changes,[130,475])
        self.update(7701)
        self.assertEqual(self.control.worlds[-1]['stage'],'failed')
        self.assertIn('within6seconds',self.control.worlds[-1]['error'])
        self.control.begin('b'*32,self.relay)
        self.assertEqual(self.relay.changes[-1],130)

    def test_old_inflight_sample_and_stale_low_estimate_cannot_count_as_high(self):
        self.rise();self.fall_ready()
        for rtt in (self.sample(1,1600)+self.sample(2,3800),
                    self.sample(1,1800,estimate=130)+self.sample(2,3800,estimate=130),
                    self.sample(1,1800,raw=300)+self.sample(2,3800)):
            self.rtt=rtt;self.update(5700)
            self.assertEqual(self.relay.changes,[130,475])

    def test_duplicate_or_different_generation_ack_cannot_manufacture_two_samples(self):
        for change in ('duplicate','generation'):
            self.setUp();self.rise();self.fall_ready()
            self.rtt=self.sample(1,1800)*2 if change=='duplicate' else self.sample(1,1800)+self.sample(2,3800,generation=2)
            with self.subTest(change=change),self.assertRaises(AssertionError):self.update(5700)

    def test_unaccepted_nonrefresh_or_uncorrelated_sample_is_not_evidence(self):
        for flags in (dict(accepted=0),dict(refresh=0),dict(kind=70)):
            self.assertEqual(verifier.refresh_round_trips(self.sample(1,1800,**flags)),[])
        with self.assertRaisesRegex(AssertionError,'matching validated'):
            verifier.refresh_round_trips(self.sample(1,1800).split('\n',1)[1])
        self.assertEqual(len(verifier.refresh_round_trips(self.sample(1,1800).replace('\n','\r\n'))),1)

    def test_both_transitions_need_unfinished_actual_movement(self):
        for change in ('stationary','finished','missing_counter'):
            self.setUp()
            if change=='stationary':
                for row in self.rows:
                    if row['event']=='transform':row['position']=[0,0,0]
            elif change=='finished':self.rows[-1]['position']=[48,0,0]
            else:self.rows[-1].pop('completed_frame')
            with self.subTest(change=change):
                if change=='missing_counter':
                    with self.assertRaises(AssertionError):self.update(1700)
                else:
                    self.update(1700);self.assertEqual(self.control.worlds[-1]['stage'],'failed')
        self.setUp();self.rise();self.fall_ready();self.rows[-1]['position']=[48,0,0]
        self.update(5700);self.assertIn('already reached',self.control.worlds[-1]['error'])

    def test_clock_regression_and_premature_rematch_fail(self):
        self.rise()
        with self.assertRaisesRegex(AssertionError,'clock regressed'):self.update(1600)
        self.setUp()
        with self.assertRaisesRegex(AssertionError,'prior match'):self.control.begin('b'*32,self.relay)

    def test_short_rematch_resets_owned_delay_and_does_not_reuse_high_samples(self):
        self.rise();self.fall_ready();self.update(5700)
        self.rtt+=self.sample(3,5800,raw=130,estimate=130);self.update(6000)
        self.control.begin('b'*32,self.relay)
        self.assertEqual(self.relay.changes,[130,475,130,130])
        self.assertEqual(self.control.worlds[-1]['high_samples'],[])

    def test_low_config_is_not_proof_of_measured_recovery(self):
        self.rise();self.fall_ready();self.update(5700)
        self.update(11701);self.assertIn('low estimate',self.control.worlds[-1]['error'])


class ChangingRttObservationTests(unittest.TestCase):
    def fixture(self,*,publication_stall=False,pose_stall=False):
        control=ChangingRttControllerTests();control.setUp()
        command=control.command();poses=[]
        for tick in range(1000,11981,20):
            frame=(tick-1000)//50+430
            if publication_stall:
                if 2500<=tick<2900:frame=459
                elif 2900<=tick<3300:frame=460+(tick-2900)//25
            x=max(0,(frame-440)*.15)
            if pose_stall and 6600<=tick<7000:x=(542-440)*.15
            poses.append(control.pose(tick,x,frame))
        log='\n'.join('MOVEMENT FEEL '+json.dumps(row)for row in [command,*poses])
        state=dict(match=control.match,world=7,stage='complete',command=command,
                   rise=dict(effective_tick_ms=2000),fall=dict(effective_tick_ms=6500))
        return log,dict(worlds=[state]),[control.match]

    def test_continuous_counters_and_motion_report_scope_without_fake_times(self):
        result=verifier.changing_rtt_evidence(*self.fixture())
        self.assertTrue(result['passed']);self.assertEqual(result['worlds'][0]['maximum_actual_presented_frame'],649)
        self.assertIn('unmeasured',result['scope'])
        self.assertIn('minimum_publication_observation_gap_ms',result['worlds'][0])
        self.assertIn('transition_to_baseline_peak_speed_ratio',result['worlds'][0])

    def test_expected_400ms_publication_stall_is_red_but_measurements_survive(self):
        result=verifier.changing_rtt_evidence(*self.fixture(publication_stall=True))
        self.assertFalse(result['passed'])
        self.assertGreater(result['worlds'][0]['maximum_publication_observation_gap']['gap_ms'],100)
        self.assertIn('maximum_observed_speed',result['worlds'][0])

    def test_unfinished_pose_stall_is_red_even_if_publications_continue(self):
        result=verifier.changing_rtt_evidence(*self.fixture(pose_stall=True))
        self.assertFalse(result['passed'])
        self.assertGreater(result['worlds'][0]['maximum_unfinished_pose_gap']['gap_ms'],100)

    def test_incomplete_tail_or_acquisition_cannot_be_marked_smooth(self):
        log,control,matches=self.fixture();control['worlds'][0]['stage']='high'
        result=verifier.changing_rtt_evidence(log,control,matches)
        self.assertFalse(result['passed']);self.assertEqual(len(result['missing_gates']),1)
        log,control,matches=self.fixture();log='\n'.join(log.splitlines()[:100])
        with self.assertRaisesRegex(AssertionError,'poses through'):verifier.changing_rtt_evidence(log,control,matches)


class NativePoseQpcTests(unittest.TestCase):
    def fixture(self,**kwargs):
        log,control,matches=ChangingRttObservationTests().fixture(**kwargs)
        rows=[json.loads(line.split('MOVEMENT FEEL ',1)[1])for line in log.splitlines()]
        for row in rows:
            if row['event']=='transform':row['sampled_us']=row['tick_ms']*1000+123456
        for state in control['worlds']:
            for name in ('rise','fall'):
                state[name]['effective_perf_counter_ns']=(state[name]['effective_tick_ms']*1000+123456)*1000
        return rows,control,matches

    @staticmethod
    def log(rows):
        return '\n'.join('MOVEMENT FEEL '+json.dumps(row)for row in rows)

    def test_checked_qpc_is_selected_and_raw_sample_anchors_remain_visible(self):
        rows,control,matches=self.fixture()
        result=verifier.changing_rtt_evidence(self.log(rows),control,matches,require_sampled_us=True)
        self.assertTrue(result['passed'])
        world=result['worlds'][0]
        self.assertEqual(world['pose_clock'],'sampled_us');self.assertFalse(world['pose_timing_approximate'])
        self.assertIn('from_sampled_us',world['maximum_transform_displacement'])
        self.assertIn('not exact publication',world['pose_timing_scope'])

    def test_qpc_pair_interval_prevents_coarse_tick_speed_quantization(self):
        a=dict(position=[0,0,0],tick_ms=15,sampled_us=100000)
        b=dict(position=[.105,0,0],tick_ms=31,sampled_us=116667)
        field,scale,approximate=verifier.pose_metric_clock([a,b])
        pair=verifier.pose_pair(a,b,field,scale)
        self.assertFalse(approximate);self.assertAlmostEqual(pair['interval_ms'],16.667)
        self.assertAlmostEqual(pair['displacement']*1000/pair['interval_ms'],6.3,places=3)
        self.assertNotEqual(pair['interval_ms'],b['tick_ms']-a['tick_ms'])
        self.assertEqual(pair['from_tick_ms'],15)

    def test_old_gettick_file_analysis_is_explicitly_approximate_and_not_upscaled(self):
        log,control,matches=ChangingRttObservationTests().fixture(publication_stall=True)
        result=verifier.changing_rtt_evidence(log,control,matches,require_sampled_us=False)
        self.assertFalse(result['passed']);world=result['worlds'][0]
        self.assertTrue(world['pose_timing_approximate']);self.assertEqual(world['pose_clock'],'tick_ms')
        self.assertNotIn('from_sampled_us',world['maximum_transform_displacement'])
        with self.assertRaisesRegex(AssertionError,'requires native QPC'):
            verifier.changing_rtt_evidence(log,control,matches,require_sampled_us=True)

    def test_new_controller_fails_closed_without_qpc_but_empty_startup_is_live(self):
        fixture=ChangingRttControllerTests();fixture.setUp()
        fixture.control=verifier.ChangingRttController(lambda:fixture.clock,lambda:fixture.clock*1_000_000,
                                                      require_sampled_us=True)
        fixture.control.begin(fixture.match,fixture.relay)
        fixture.control.update('',fixture.relay)
        self.assertEqual(fixture.control.worlds[-1]['stage'],'waiting_for450')
        with self.assertRaisesRegex(AssertionError,'requires native QPC'):fixture.update(1700)

    def test_mixed_regressed_invalid_or_moving_duplicate_qpc_is_not_accepted(self):
        for change in ('mixed','regressed','bool','negative','moving_duplicate'):
            rows,control,matches=self.fixture();poses=[row for row in rows if row['event']=='transform']
            if change=='mixed':poses[1].pop('sampled_us')
            elif change=='regressed':poses[1]['sampled_us']=poses[0]['sampled_us']-1
            elif change=='bool':poses[1]['sampled_us']=True
            elif change=='negative':poses[1]['sampled_us']=-1
            else:
                poses[1]['sampled_us']=poses[0]['sampled_us'];poses[1]['position']=[1,0,0]
            with self.subTest(change=change),self.assertRaises(AssertionError):
                verifier.changing_rtt_evidence(self.log(rows),control,matches)

    def test_identical_origin_duplicate_qpc_has_zero_dt_without_fake_speed(self):
        row=dict(position=[0,0,0],tick_ms=100,sampled_us=12345)
        field,scale,approximate=verifier.pose_metric_clock([row,dict(row)])
        self.assertFalse(approximate)
        self.assertEqual(verifier.pose_pair(row,row,field,scale)['interval_ms'],0)
        rows,control,matches=self.fixture();rows.insert(2,dict(rows[1]))
        self.assertTrue(verifier.changing_rtt_evidence(self.log(rows),control,matches,require_sampled_us=True)['passed'])

    def test_qpc_does_not_weaken_hundred_ms_stall_red(self):
        for kwargs in (dict(publication_stall=True),dict(pose_stall=True)):
            rows,control,matches=self.fixture(**kwargs)
            result=verifier.changing_rtt_evidence(self.log(rows),control,matches,require_sampled_us=True)
            self.assertFalse(result['passed'])

    def test_qpc_samples_require_actual_setter_perf_clock_not_a_guessed_offset(self):
        rows,control,matches=self.fixture();control['worlds'][0]['rise'].pop('effective_perf_counter_ns')
        with self.assertRaisesRegex(AssertionError,'setter perf clock'):
            verifier.changing_rtt_evidence(self.log(rows),control,matches,require_sampled_us=True)

    def test_existing_feel_summary_speed_prefers_qpc_without_retiming_command_gates(self):
        rows,args=FeelEvidenceTests().fixture()
        before=verifier.evaluate_feel(rows,**args)
        for row in rows:
            if row['event']=='transform':row['sampled_us']=row['tick_ms']*1000+123456
        after=verifier.evaluate_feel(rows,**args)
        self.assertFalse(after['pose_timing_approximate']);self.assertEqual(after['pose_metric_clock'],'sampled_us')
        for key in ('command_to_visible_ms','visibility_before_authority_ms','canonical_commit_frame','speculative_frame'):
            self.assertEqual(after[key],before[key])


class TransitionGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name).resolve()
        self.fixture=ChangingRttControllerTests();self.fixture.setUp()

    def test_exact_marker_immutable_and_no_temporary_partial_file(self):
        cmd=self.fixture.command()
        row=verifier.publish_transition_gate(self.folder,cmd,2,lambda:1000,lambda:1000000)
        expected=('BA_MOVEMENT_TURN_V1 '+'a'*32+' 7 91 1 1 2\n').encode('ascii')
        self.assertEqual(Path(row['path']).read_bytes(),expected)
        self.assertEqual(row['sha256'],verifier.digest(expected))
        self.assertEqual(len(list(self.folder.iterdir())),1)
        with self.assertRaisesRegex(AssertionError,'no overwrite'):
            verifier.publish_transition_gate(self.folder,cmd,2,lambda:1000,lambda:1000000)

    def phase(self,tick,nxt,target,*,match=None):
        return f'[{tick}] Movement pacing waiting: reason=6 next={nxt} confirmed=500 received=500 networkReceived=500 physical={nxt-1} presented={nxt-1} targetAssigned={target} rtt_us=130000\n'

    def test_controller_publishes2_aftersetter_and3_after_fresh_true_next_phase(self):
        f=self.fixture
        f.relay.changes=[]
        f.control=verifier.ChangingRttController(lambda:f.clock,lambda:f.clock*1_000_000,transition_gates=self.folder)
        f.control.begin(f.match,f.relay);f.rise();f.fall_ready();f.update(5700)
        state=f.control.worlds[-1];self.assertTrue(Path(state['turn2_gate']['path']).exists())
        self.assertGreaterEqual(state['turn2_gate']['requested_perf_counter_ns'],state['fall']['effective_perf_counter_ns'])
        turn=dict(f.command(),ordinal=2,move_id=2,origin=[20,0,0],target=[-28,0,0],motion_from=[19,0,0],
            sampled_us=5800000,motion_from_sampled_us=5700000,enqueue_sampled_us=5800001,
            tick_ms=5800,presented_frame=532,completed_frame=532,physical_frame=532,
            originalCtor=True,physicalUI=False,queueDelta=1,action_sha256='b'*64)
        f.rtt+=f.sample(3,5800,raw=130,estimate=130)
        start=f'[1000] Movement pacing START: match={f.match} world=7 waitSteadyFrame=1 budget=12 BA_RESURRECTION_MOVEMENT_PACING_V1\n'
        f.extra_log='MOVEMENT TURN '+json.dumps(turn)+'\n'+start+self.phase(6000,540,539)+self.phase(6600,552,551)
        f.rows.extend([f.pose(6500,18,550),f.pose(6600,17,552)])
        f.update(6600)
        self.assertIn('turn3_gate',state)
        self.assertEqual([row['next_assignment_delta']for row in state['turn3_phase_rows']],[-1,-1])
        self.assertEqual(state['turn3_phase_rows'][1]['tick_ms']-state['turn3_phase_rows'][0]['tick_ms'],600)

    def test_phase_parser_binds_current_start_and_corrects_head_next_offbyone(self):
        first='a'*32;second='b'*32
        log=f'Movement pacing START: match={first} world=7 waitSteadyFrame=1\n'+self.phase(1000,594,593)
        log+=f'Movement pacing START: match={second} world=8 waitSteadyFrame=1\n'+self.phase(2000,614,614)
        rows=verifier.phase_rows(log,first,7)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['next_assignment_delta'],-1)
        self.assertGreater(abs(rows[0]['target_assigned']-1-rows[0]['next']),1)
        self.assertEqual(verifier.phase_rows(log,first,8),[])

    def test_stale_or_newer_unconverged_phase_never_publishes_recovered_gate(self):
        for condition in ('stale','newer_bad'):
            folder=self.folder/condition;folder.mkdir()
            f=ChangingRttControllerTests();f.setUp();f.relay.changes=[]
            f.control=verifier.ChangingRttController(lambda:f.clock,lambda:f.clock*1_000_000,transition_gates=folder)
            f.control.begin(f.match,f.relay);f.rise();f.fall_ready();f.update(5700)
            turn=dict(f.command(),ordinal=2,move_id=2,origin=[20,0,0],target=[-28,0,0],motion_from=[19,0,0],
                sampled_us=5800000,motion_from_sampled_us=5700000,enqueue_sampled_us=5800001,
                tick_ms=5800,presented_frame=532,completed_frame=532,physical_frame=532,
                originalCtor=True,physicalUI=False,queueDelta=1,action_sha256='b'*64)
            f.rtt+=f.sample(3,5800,raw=130,estimate=130)
            f.extra_log='MOVEMENT TURN '+json.dumps(turn)+'\n'+f'Movement pacing START: match={f.match} world=7 waitSteadyFrame=1\n'
            f.extra_log+=self.phase(6000,540,539)+self.phase(6600,552,551)
            if condition=='newer_bad':f.extra_log+=self.phase(6950,559,561)
            now=7200 if condition=='stale' else 7000
            f.rows.extend([f.pose(now-100,18,558),f.pose(now,17,560)])
            f.update(now)
            with self.subTest(condition=condition):self.assertNotIn('turn3_gate',f.control.worlds[-1])
            f.extra_log+=self.phase(7600,570,569)
            f.rows.extend([f.pose(7500,16,569),f.pose(7600,15,570)]);f.update(7600)
            self.assertIn('turn3_gate',f.control.worlds[-1])


class DecisionPhaseTests(unittest.TestCase):
    @staticmethod
    def row(tick=6000,nxt=540,assigned=539,**fields):
        return dict(dict(schema=1,event='decision',match='a'*32,world=7,next=nxt,target_assigned=assigned,
            presented_frame=nxt-1,rtt_us=130000,allowed=False,wait=6,
            decision_us=tick*1000,sampled_us=tick*1000+10,tick_ms=tick),**fields)

    @staticmethod
    def log(rows):
        return '\n'.join('MOVEMENT PHASE '+json.dumps(row)for row in rows)+'\n'

    def test_real_decisions_include_allowed_and_wait_without_recomputing_target(self):
        rows=[self.row(),self.row(6020,541,541,allowed=True,wait=0)]
        result=verifier.decision_phase_rows(self.log(rows),'a'*32,7)
        self.assertEqual([row['next_assignment_delta']for row in result],[-1,0])
        self.assertEqual([{key:value for key,value in row.items()if key!='next_assignment_delta'}for row in result],rows)
        self.assertEqual(verifier.decision_phase_rows(self.log(rows),'b'*32,7),[])

    def test_schema_scope_clock_and_throttle_fail_closed(self):
        for fields in (dict(schema=True),dict(world=True),dict(allowed=1),dict(wait=7),dict(allowed=True),
                       dict(next=650),dict(next=399),dict(rtt_us=2000001),dict(target_assigned=0),
                       dict(sampled_us=5999999),dict(sampled_us=6050000),dict(unexpected=1)):
            with self.subTest(fields=fields),self.assertRaises(AssertionError):
                verifier.decision_phase_rows(self.log([self.row(**fields)]),'a'*32,7)
        for rows in ([self.row(),self.row()], [self.row(),self.row(6009)],
                     [self.row(),self.row(6020,decision_us=5999000)],
                     [self.row(),self.row(6020,tick_ms=5999)]):
            with self.subTest(rows=rows),self.assertRaises(AssertionError):
                verifier.decision_phase_rows(self.log(rows),'a'*32,7)

    def test_world_and_count_bounds_and_rematch_reset(self):
        first=self.row();second=self.row(1000,world=8,match='b'*32)
        self.assertEqual(len(verifier.decision_phase_rows(self.log([first,second]),'b'*32,8)),1)
        with self.assertRaisesRegex(AssertionError,'world/count'):
            verifier.decision_phase_rows(self.log([first,second,self.row(2000,world=9,match='c'*32)]),'a'*32,7)
        with self.assertRaisesRegex(AssertionError,'world/count'):
            verifier.decision_phase_rows(self.log([self.row(6000+i*10)for i in range(4097)]),'a'*32,7)

    def controller(self,folder):
        f=ChangingRttControllerTests();f.setUp();f.relay.changes=[]
        f.control=verifier.ChangingRttController(lambda:f.clock,lambda:f.clock*1_000_000,
            transition_gates=folder,phase_source='decision')
        f.control.begin(f.match,f.relay);f.rise();f.fall_ready();f.update(5700)
        turn=dict(f.command(),ordinal=2,move_id=2,origin=[20,0,0],target=[-28,0,0],motion_from=[19,0,0],
            sampled_us=5800000,motion_from_sampled_us=5700000,enqueue_sampled_us=5800001,
            tick_ms=5800,presented_frame=532,completed_frame=532,physical_frame=532,
            originalCtor=True,physicalUI=False,queueDelta=1,action_sha256='b'*64)
        f.rtt+=f.sample(3,5800,raw=130,estimate=130)
        f.extra_log='MOVEMENT TURN '+json.dumps(turn)+'\n'
        f.rows.extend([f.pose(6500,18,550),f.pose(6600,17,552)])
        return f

    def test_dense_actual_decisions_close_sparse_sampling_alias_without_phase_relaxation(self):
        with tempfile.TemporaryDirectory()as directory:
            f=self.controller(Path(directory).resolve())
            sparse=TransitionGateTests()
            f.extra_log+=f'Movement pacing START: match={f.match} world=7 waitSteadyFrame=1\n'
            f.extra_log+=sparse.phase(6000,540,538)+sparse.phase(6600,552,551)
            f.update(6600)
            self.assertNotIn('turn3_gate',f.control.worlds[-1])  # No fallback, even one sparse eligible sample.
            actual=[self.row(6000,540,538),self.row(6050,541,540),self.row(6500,550,548),self.row(6600,552,551)]
            f.extra_log+=self.log(actual);f.update(6601)
            state=f.control.worlds[-1]
            self.assertIn('turn3_gate',state)
            self.assertEqual([row['next_assignment_delta']for row in state['turn3_phase_rows']],[-1,-1])
            self.assertEqual(f.control.snapshot()['phase_source'],'decision')

    def test_low_ack_causality_latest_bad_and_stale_decisions_prevent_gate(self):
        cases={'before_ack':[self.row(5900),self.row(6600,552,551)],
               'too_close':[self.row(6200),self.row(6600,552,551)],
               'newest_bad':[self.row(6000),self.row(6550,551,550),self.row(6600,552,550)],
               'stale':[self.row(5950),self.row(6050,541,540)]}
        with tempfile.TemporaryDirectory()as directory:
            for name,rows in cases.items():
                folder=Path(directory)/name;folder.mkdir()
                f=self.controller(folder.resolve());f.extra_log+=self.log(rows);f.update(6601)
                with self.subTest(name=name):self.assertNotIn('turn3_gate',f.control.worlds[-1])


class TransitionOrderEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name).resolve()
        self.match='a'*32
        self.common=dict(schema=1,match=self.match,world=7,entity=91,unit_type=1,incarnation=340,move_id=1)
        self.first=dict(self.common,event='command_created',tick_ms=1000,original_callback='Uncapped.ExecuteTargetGroundCommand..ctor',
                        ability=12,target=[48,0,0],action_sha256='f'*64)
        def pose(tick,x,frame):
            return dict(self.common,event='transform',tick_ms=tick,sampled_us=tick*1000,
                source=verifier.FEEL_CONTRACT['transform_source'],position=[x,0,0],presented_frame=frame,completed_frame=frame)
        self.poses=[pose(1100,9,554),pose(1200,10,555),pose(1216,10.1,556),pose(1232,10.15,556),pose(1248,10,557),
                    pose(1820,5,588),pose(1920,4,589),pose(1936,3.9,590),pose(1952,3.8,590),pose(1968,3.95,591)]
        self.orders=[];self.actions=[];self.bodies={};self.commits=[];self.registrations=[]
        for ordinal,origin,target,prior,tick,frame,assigned in ((2,10,-38,9,1201,550,557),(3,4,36,5,1921,590,590)):
            position=field_uint(1,int(target*2**32)&(2**64-1))
            group=field_uint(1,1)+field_uint(2,12)+field_packed_uint(3,[91])
            action=field_bytes(1,field_bytes(1,group)+field_bytes(3,field_bytes(3,field_bytes(1,position))))
            self.actions.append(action);body=encode_player_input(encode_identity(1,'Owned subject'),[action]);sequence=ordinal+2
            self.bodies[self.match,0,sequence]=body
            sample=(tick-1)*1000
            order=dict(self.common,event='command_created',move_id=ordinal,ordinal=ordinal,tick_ms=tick,
                sampled_us=sample,motion_from_sampled_us=sample-100000,enqueue_sampled_us=tick*1000,
                origin=[origin,0,0],motion_from=[prior,0,0],target=[target,0,0],ability=12,
                action_sha256=verifier.digest(action),original_callback='Uncapped.ExecuteTargetGroundCommand..ctor',
                originalCtor=True,physicalUI=False,queueDelta=1,physical_frame=assigned-1,presented_frame=assigned-2,completed_frame=assigned-2)
            self.orders.append(order)
            self.commits.append(dict(event='command_batch_committed',match=self.match,slot=0,sequence=sequence,frame=frame))
            self.registrations.append(dict(sequence=sequence,assigned=assigned,tick=tick,body=body))
        self.state=dict(match=self.match,world=7,command=self.first,fall=dict(effective_tick_ms=1180,effective_perf_counter_ns=1180000000),
                        low_samples=[dict(received_tick_ms=1350)])
        for ordinal,tick in ((2,1190),(3,1910)):
            self.state[f'turn{ordinal}_gate']=verifier.publish_transition_gate(self.folder,self.first,ordinal,lambda tick=tick:tick,
                                                                            lambda tick=tick:tick*1000000)
        self.phases=[dict(tick_ms=1400,reason=6,next=570,confirmed=500,received=500,network_received=500,
            physical=569,presented=569,target_assigned=569,rtt_us=130000),
            dict(tick_ms=1900,reason=6,next=590,confirmed=500,received=500,network_received=500,
            physical=589,presented=589,target_assigned=590,rtt_us=130000)]
        self.state['turn3_phase_rows']=self.phases
        for row in self.phases:row['next_assignment_delta']=row['target_assigned']-row['next']
        self.authorities=[dict(schema=1,world=7,match=self.match,frame=frame,tick_ms=tick,
            canonical_sha256='b'*64,wire_sha256=wire*64)for frame,tick,wire in ((550,1300,'c'),(590,2050,'d'))]
        self.bridge=[dict(match=self.match,frame=frame,received_tick_ms=tick,payload_sha256=wire*64)
                     for frame,tick,wire in ((550,1290,'c'),(590,2040,'d'))]
        self.states={frame:'a'*64 for frame in range(611)}
        self.worker=[dict(schema=1,event='confirmed_native_state',world=7,frame=frame,confirmed_frontier=frame,
            parsed_state_sha256='a'*64,corrections=int(frame>=550),corrections_delta=int(frame==550),
            replayed_frames_total=7 if frame>=550 else 0,replayed_frames_delta=7 if frame==550 else 0,
            tick_ms=100+frame*2 if frame<550 else 1310+(frame-550)*5 if frame<590 else 2060+(frame-590)*5)
            for frame in range(611)]
        self.journal=[dict(frame=frame,players={0:[self.actions[0]]if frame==550 else [self.actions[1]]if frame==590 else [],1:[]})
                      for frame in range(611)]

    def log(self):
        lines=['MOVEMENT FEEL '+json.dumps(row)for row in [self.first,*self.poses]]
        lines+=['MOVEMENT TURN '+json.dumps(row)for row in self.orders]
        lines+=['MOVEMENT AUTHORITY '+json.dumps(row)for row in self.authorities]
        for row in self.registrations:
            lines.append(f'Movement local batch registered: sequence={row["sequence"]} speculativeFrame={row["assigned"]} tick={row["tick"]} match={self.match}')
            lines.append(f'Original command batch submitted: match={self.match} sequence={row["sequence"]} actions={len(decode_player_input(row["body"])["actions"])} bytes={len(row["body"])} body_sha256={verifier.digest(row["body"])} sendTick={row["tick"]+1} sourceNextFrame=500')
        lines.append(f'Movement pacing START: match={self.match} world=7 waitSteadyFrame=1')
        for row in self.phases:
            lines.append(f'[{row["tick_ms"]}] Movement pacing waiting: reason=6 next={row["next"]} confirmed=500 received=500 networkReceived=500 physical={row["physical"]} presented={row["presented"]} targetAssigned={row["target_assigned"]} rtt_us=130000')
        lines+=['MOVEMENT PHASE '+json.dumps(row)for row in getattr(self,'decision_phases',[])]
        return '\n'.join(lines)

    def check(self,phase_source='pacer_wait'):
        return verifier.transition_order_evidence(self.log(),dict(worlds=[self.state],phase_source=phase_source),match=self.match,slot=0,
            commits=self.commits,raw_bodies=self.bodies,journal=self.journal,canonical_states=self.states,
            canonical_payloads={550:'c'*64,590:'d'*64},
            bridge_frames=self.bridge,worker_states=self.worker,native_receipts=getattr(self,'native_receipts',None))

    def test_two_true_new_directions_before_both_receipts_with_raw_transient_phase(self):
        result=self.check();self.assertTrue(result['passed'])
        self.assertEqual([row['assigned_minus_canonical']for row in result['orders']],[7,0])
        self.assertEqual(result['orders'][0]['promotion_group_replayed_delta'],7)
        self.assertAlmostEqual(result['orders'][0]['enqueue_to_new_direction_ms'],47)
        self.assertEqual([row['continuation_frames']for row in result['orders']],[20,20])

    def test_dense_phase_final_proof_requires_exact_captured_rows_and_actual_low_ack(self):
        self.state['low_samples'][-1]['received_us']=1350000
        self.decision_phases=[DecisionPhaseTests.row(1400,570,569),DecisionPhaseTests.row(1900,590,590)]
        self.state['turn3_phase_rows']=verifier.decision_phase_rows(self.log(),self.match,7)
        self.assertTrue(self.check('decision')['passed'])
        self.state['turn3_phase_rows'][0]['target_assigned']+=1
        with self.assertRaisesRegex(AssertionError,'actual recovered phase'):self.check('decision')

    def test_old_ongoing_motion_is_not_a_response_to_new_reverse_order(self):
        for row in self.poses:
            if 1201<row['tick_ms']<1290:row['position']=[10+(row['tick_ms']-1200)*.01,0,0]
        with self.assertRaisesRegex(AssertionError,'NEW-direction'):self.check()

    def test_reversal_only_after_one_authority_receipt_is_insufficient(self):
        self.bridge[0]['received_tick_ms']=1240
        with self.assertRaisesRegex(AssertionError,'NEW-direction'):self.check()

    def test_origin_and_prior_must_be_exact_actual_qpc_pose_samples(self):
        self.orders[0]['motion_from']=[8,0,0]
        with self.assertRaisesRegex(AssertionError,'actual QPC pose'):self.check()

    def test_duplicate_intent_changed_actor_or_target_cannot_pass(self):
        self.orders[0]['action_sha256']='f'*64
        with self.assertRaisesRegex(AssertionError,'hashes were replayed'):self.check()
        self.orders[0]['action_sha256']=verifier.digest(self.actions[0]);self.orders[0]['incarnation']=341
        with self.assertRaisesRegex(AssertionError,'incarnation'):self.check()

    def test_immutable72_or_unique_canonical_commit_are_mandatory(self):
        original=self.bodies;self.bodies={}
        with self.assertRaisesRegex(AssertionError,'immutable72'):self.check()
        self.bodies=original;self.commits.append(dict(self.commits[0]))
        with self.assertRaisesRegex(AssertionError,'canonical commit'):self.check()

    def test_missing_real67_and_wrong_wire_hash_fail(self):
        self.registrations[0]['sequence']=40
        with self.assertRaisesRegex(AssertionError,'actual67'):self.check()
        self.registrations[0]['sequence']=4;self.bridge[0]['payload_sha256']='e'*64
        with self.assertRaisesRegex(AssertionError,'wire binding'):self.check()

    def test_recovered_order3_wrong_phase_is_reported_red_without_rewriting_it(self):
        self.registrations[1]['assigned']=593
        for row in self.worker[590:]:row.update(corrections=2,replayed_frames_total=10)
        self.worker[590].update(corrections_delta=1,replayed_frames_delta=3)
        result=self.check();self.assertFalse(result['passed'])
        self.assertEqual(result['orders'][1]['assigned_minus_canonical'],3)

    def test_missing_correction_or_twenty_frame_tail_cannot_be_substituted(self):
        saved=deepcopy(self.worker)
        for row in self.worker:row.update(corrections=0,corrections_delta=0,replayed_frames_total=0,replayed_frames_delta=0)
        with self.assertRaisesRegex(AssertionError,'replay'):self.check()
        self.worker=saved[:-1]
        with self.assertRaisesRegex(AssertionError,'20 contiguous'):self.check()

    def test_gate_visibility_is_a_bracket_not_postreturn_earliest_time(self):
        gate=self.state['turn2_gate'];order=self.orders[0]
        gate['published_perf_counter_ns']=order['enqueue_sampled_us']*1000+1000
        gate['published_tick_ms']=order['tick_ms']+1
        self.assertTrue(self.check()['passed'])
        gate['requested_perf_counter_ns']=order['enqueue_sampled_us']*1000+1
        with self.assertRaisesRegex(AssertionError,'precedes its actual owned gate'):self.check()

    def test_phase_observations_must_be_current_match_fresh_and_after_actual_lowack(self):
        self.state['low_samples'][0]['received_tick_ms']=1500
        with self.assertRaisesRegex(AssertionError,'phase observations'):self.check()
        self.state['low_samples'][0]['received_tick_ms']=1350
        order=self.orders[1]
        for key in ('sampled_us','motion_from_sampled_us','enqueue_sampled_us'):order[key]+=600000
        order['tick_ms']+=600
        for row in self.poses:
            if row['tick_ms']>=1820:row['tick_ms']+=600;row['sampled_us']+=600000
        self.state['turn3_gate'].update(requested_tick_ms=2510,requested_perf_counter_ns=2510000000,
                                       published_tick_ms=2510,published_perf_counter_ns=2510000000)
        with self.assertRaisesRegex(AssertionError,'stales'):self.check()


class EarlyEmptyRetimeTests(unittest.TestCase):
    def setUp(self):
        f=self.f=TransitionOrderEvidenceTests();f.setUp();self.addCleanup(f.doCleanups)
        f.registrations[0]['assigned']=547
        for row in f.worker:
            if 546<=row['frame']<=549:
                row.update(confirmed_frontier=549,tick_ms=1280,corrections=1,replayed_frames_total=4,
                    corrections_delta=int(row['frame']==546),replayed_frames_delta=4 if row['frame']==546 else 0)
            elif row['frame']>=550:
                row.update(corrections=1,replayed_frames_total=4,corrections_delta=0,replayed_frames_delta=0)
        f.native_receipts=[dict(pid=123,match=f.match,frame=547,actions=0,sim=549,sha256='e'*64)]
        f.bridge.append(dict(match=f.match,frame=547,received_tick_ms=1270,payload_sha256='e'*64))
        self.payloads={547:'e'*64,550:'c'*64,590:'d'*64}

    def check(self):
        f=self.f
        binding=verifier.transition_order_binding(f.log(),f.orders[0],slot=0,raw_bodies=f.bodies,journal=f.journal,commits=f.commits)
        return verifier.early_empty_retime_evidence(f.log(),match=f.match,slot=0,order=f.orders[0],binding=binding,
            authority=f.authorities[0],new_direction=f.poses[4],commits=f.commits,raw_bodies=f.bodies,journal=f.journal,
            canonical_states=f.states,canonical_payloads=self.payloads,bridge_frames=f.bridge,
            worker_states=f.worker,native_receipts=f.native_receipts)

    def test_exact_early_empty65_positive_group_and_final_twenty_states_without_invented_time(self):
        final,early=self.check()
        self.assertEqual(early['kind'],'early_empty_retime');self.assertIsNone(early['native65_tick_ms'])
        self.assertEqual(early['promotion_group_replayed_delta'],4)
        self.assertEqual(early['pending_local_sequences'],[4]);self.assertEqual(final['continuation_frames'],20)
        self.assertEqual(final['confirmed_state_frame'],550)
        self.assertEqual(final['promotion_group_replayed_delta'],0)
        self.assertTrue(final['correction_required'])

    def test_real_transition_evaluator_accepts_this_early_retime_only_with_exact_witness(self):
        f=self.f
        result=verifier.transition_order_evidence(f.log(),dict(worlds=[f.state]),match=f.match,slot=0,
            commits=f.commits,raw_bodies=f.bodies,journal=f.journal,canonical_states=f.states,
            canonical_payloads=self.payloads,bridge_frames=f.bridge,worker_states=f.worker,native_receipts=f.native_receipts)
        self.assertTrue(result['passed']);self.assertEqual(result['orders'][0]['assigned_minus_canonical'],-3)
        self.assertEqual(result['orders'][0]['early_empty_retime']['promotion_group_replayed_delta'],4)

    def test_wrong_assigned_hash_nonempty_or_missing_native65_cannot_substitute(self):
        saved=deepcopy(self.f.native_receipts)
        for changes in (dict(frame=548),dict(sha256='f'*64),dict(actions=1),dict(sim=546)):
            self.f.native_receipts=[dict(saved[0],**changes)]
            with self.subTest(changes=changes),self.assertRaisesRegex(AssertionError,'empty65'):self.check()
        self.f.native_receipts=[]
        with self.assertRaisesRegex(AssertionError,'empty65'):self.check()

    def test_other_canonical_actions_or_pending_local_prediction_are_forbidden(self):
        self.f.journal[548]['players'][1]=[b'other action']
        with self.assertRaisesRegex(AssertionError,'other canonical actions'):self.check()
        self.f.journal[548]['players'][1]=[]
        self.f.registrations.append(dict(sequence=6,assigned=548,tick=1250,body=self.f.registrations[0]['body']))
        self.f.bodies[self.f.match,0,6]=self.f.registrations[0]['body']
        self.f.commits.append(dict(event='command_batch_committed',match=self.f.match,slot=0,sequence=6,frame=560))
        # Keep the exact original command binding unique; use a different body for the extra pending order.
        self.f.bodies[self.f.match,0,6]=encode_player_input(encode_identity(1,'Owned subject'),[b'other action'])
        self.f.registrations[-1]['body']=self.f.bodies[self.f.match,0,6]
        with self.assertRaisesRegex(AssertionError,'another pending'):self.check()

    def test_second_predicted_action_in_same_batch_is_not_unique_original_move(self):
        f=self.f;body=encode_player_input(encode_identity(1,'Owned subject'),[f.actions[0],b'another predicted Move'])
        f.bodies[f.match,0,4]=body;f.registrations[0]['body']=body
        with self.assertRaisesRegex(AssertionError,'another predicted action'):self.check()

    def test_unrelated_or_nonpositive_replay_group_and_wrong_native_hash_fail(self):
        saved=deepcopy(self.f.worker)
        for row in self.f.worker:
            row.update(corrections=0,replayed_frames_total=0,corrections_delta=0,replayed_frames_delta=0)
        with self.assertRaisesRegex(AssertionError,'positive replay'):self.check()
        self.f.worker=deepcopy(saved);self.f.worker[547]['parsed_state_sha256']='f'*64
        with self.assertRaisesRegex(AssertionError,'differs from authority'):self.check()
        self.f.worker=deepcopy(saved)
        for row in self.f.worker[546:550]:row['confirmed_frontier']=550
        with self.assertRaises(AssertionError):self.check()

    def test_actual_new_direction_and_positive_group_must_precede_final65_in_order(self):
        saved=deepcopy(self.f.worker)
        for tick in (1260,1301):
            for row in self.f.worker[546:550]:row['tick_ms']=tick
            with self.subTest(tick=tick),self.assertRaisesRegex(AssertionError,'timing'):self.check()
        self.f.worker=saved;self.f.bridge[-1]['received_tick_ms']=1240
        with self.assertRaisesRegex(AssertionError,'timing'):self.check()

    def test_final_confirmation_and_twenty_real_continuations_remain_required(self):
        self.f.worker=self.f.worker[:570]
        with self.assertRaisesRegex(AssertionError,'20 contiguous'):self.check()

    def test_zero_or_positive_phase_cannot_use_early_empty_exception(self):
        for assigned in (550,551):
            self.f.registrations[0]['assigned']=assigned
            with self.subTest(assigned=assigned),self.assertRaisesRegex(AssertionError,'negative actual command phase'):self.check()

    def test_receipt_parser_binds_exact_pid_match_contiguous_native_payloads(self):
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'receipts.tsv'
            header='pid\tmatch\tframe\tactions\tsim\tsha256\n'
            value=f'123\t{self.f.match}\t0\t0\t-1\t'+64*'a'+'\n'
            path.write_text(header+value)
            self.assertEqual(verifier.read_native_receipts(path,pid=123,match=self.f.match)[0]['frame'],0)
            for raw in ((header+value).replace('\t0\t0\t','\t1\t0\t'),header+value+value,(header+value).rstrip('\n')):
                path.write_text(raw)
                with self.assertRaises(AssertionError):verifier.read_native_receipts(path,pid=123,match=self.f.match)
            path.write_text(header+value)
            with self.assertRaises(AssertionError):verifier.read_native_receipts(path,pid=124,match=self.f.match)


class ObservationOrderingTests(unittest.TestCase):
    def test_first_phase_red_retains_independent_turn_and_smoothness_results(self):
        report=dict(passed=False,scoped_observation_passed=False,
            feel=dict(passed=False,speculative_frame=441,canonical_commit_frame=443,
                      speculative_minus_canonical_frames=-2))
        collected=[]
        def independent():
            collected.append(True)
            report['changing_rtt_observation']=dict(passed=True)
            report['changing_rtt_smoothness_passed']=True
            report['transition_orders']=dict(passed=True,episodes=[dict(match='a'*32),dict(match='b'*32)])
        with self.assertRaisesRegex(AssertionError,'actual movement feel contract remains missing'):
            verifier.finalize_movement_observation(report,independent)
        self.assertEqual(collected,[True])
        self.assertTrue(report['transition_orders']['passed'])
        self.assertTrue(report['changing_rtt_smoothness_passed'])
        self.assertFalse(report['passed']or report['scoped_observation_passed'])
        self.assertEqual(report['feel']['speculative_minus_canonical_frames'],-2)


if __name__ == '__main__':
    unittest.main()
