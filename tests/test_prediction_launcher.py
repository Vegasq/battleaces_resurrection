"""Private typed paths cannot enable prediction through ordinary settings/CLI."""
import argparse
import asyncio
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest
from unittest import mock

from client_patch.transport import launcher as launch
from tests.test_credentials import private_test_folder, remove_test_folder


class PredictionLauncherTests(unittest.TestCase):
    def setUp(self):
        self.root=private_test_folder('prediction-launcher-')
        self.game=self.root/'game';self.game.mkdir()
        app=self.root/'program/app';main=app/'client_patch/prediction_worker/__main__.py'
        resources=(self.root/'program/runtime/python.exe',self.root/'program/heap/BAHeap.dll',
                   self.root/'program/cooperative/PredictionCooperative.dll',main)
        for path in resources:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'authored non-executable fixture\n')
        data=self.root/'run-data';data.mkdir()
        self.options=launch.PredictionWorkerOptions(resources[0],app,resources[1],resources[2],data)
        self.args=argparse.Namespace(run_name='prediction',unified_experimental=True,
                                    original_command_scheduling_experimental=True,replay=None)
        self.config=dict(game_directory=self.game,server_host='127.0.0.1',server_port=47623,
                         display_name='Private player',room='community',local_profile='prediction_custom',
                         fullscreen=False,solo_ai_host='local')
    def tearDown(self):remove_test_folder(self.root)
    def argv(self,**kwargs):return launch.game_arguments(self.config,None,17,self.args,**kwargs)

    def test_normal_default_arguments_remain_prediction_free(self):
        self.args.original_command_scheduling_experimental=False
        actual=self.argv()
        self.assertEqual(actual,self.argv(prediction_worker=None))
        self.assertFalse(any(value.startswith('-prediction-') for value in actual))
        self.assertIsNone(launch.prediction_worker_options(self.args))

    def test_explicit_typed_options_add_only_movement_and_five_paths(self):
        normal=self.argv();actual=self.argv(prediction_worker=self.options)
        extra=[value for value in actual if value not in normal]
        self.assertEqual(extra,['-prediction-movement-experimental',
            '-prediction-worker-python='+str(self.options.python),
            '-prediction-worker-module-root='+str(self.options.module_root),
            '-prediction-worker-heap-helper='+str(self.options.heap_helper),
            '-prediction-worker-cooperative='+str(self.options.cooperative),
            '-prediction-worker-data-dir='+str(self.options.data_directory)])
        self.assertFalse(any('smoke' in value or 'probe' in value or 'observe' in value for value in extra))
        with self.assertRaises(FrozenInstanceError):self.options.python=Path('changed')

    def test_visual_correction_true_adds_only_its_flag_and_false_is_unchanged(self):
        self.assertIs(self.options.visual_correction,False)
        normal=self.argv(prediction_worker=self.options)
        self.assertEqual(normal,self.argv(prediction_worker=replace(self.options,visual_correction=False)))
        enabled=replace(self.options,visual_correction=True)
        actual=self.argv(prediction_worker=enabled)
        self.assertEqual([flag for flag in actual if flag not in normal],['-prediction-visual-correction'])
        self.assertEqual([flag for flag in actual if flag!='-prediction-visual-correction'],normal)
        self.assertFalse(any(word in flag for flag in actual for word in ('smoke','probe','observe','stages','frame-timing')))
        self.assertIs(launch.prediction_worker_options(self.args,enabled).visual_correction,True)

    def test_visual_correction_cannot_be_enabled_by_settings_or_namespace(self):
        self.config['visual_correction']=True;self.args.visual_correction=True
        self.assertNotIn('-prediction-visual-correction',self.argv())
        self.assertNotIn('-prediction-visual-correction',self.argv(prediction_worker=self.options))

    def test_invalid_visual_boolean_refuses_before_filesystem_verify_or_ipc(self):
        async def run():
            for invalid in (0,1,None,'true',[],{}):
                with self.subTest(invalid=invalid),mock.patch.object(Path,'lstat',side_effect=AssertionError('filesystem touched')), \
                        mock.patch.object(launch,'verify_game') as verify,mock.patch.object(launch.socket,'socketpair') as pair:
                    with self.assertRaisesRegex(launch.LaunchError,'Boolean'):
                        await launch.launch(self.config,None,self.args,
                            prediction_worker=replace(self.options,visual_correction=invalid))
                    verify.assert_not_called();pair.assert_not_called()
        asyncio.run(run())

    def test_namespace_options_are_typed_and_conflicts_rejected(self):
        self.args.prediction_worker=self.options
        self.assertEqual(self.argv(),self.argv(prediction_worker=self.options))
        other=self.root/'other-data';other.mkdir()
        with self.assertRaisesRegex(launch.LaunchError,'Conflicting'):
            self.argv(prediction_worker=replace(self.options,data_directory=other))
        self.args.prediction_worker={'python':str(self.options.python)}
        with self.assertRaisesRegex(launch.LaunchError,'typed'):self.argv()

    def test_wrong_context_refuses_before_creating_game_runtime_paths(self):
        for key,value in (('unified_experimental',False),('unified_experimental',1),
                          ('original_command_scheduling_experimental',False),('replay','')):
            old=getattr(self.args,key);setattr(self.args,key,value)
            with self.subTest(key=key,value=value),self.assertRaises(launch.LaunchError):
                self.argv(prediction_worker=self.options)
            setattr(self.args,key,old)
        self.assertFalse((self.game/'investigation').exists())

    def test_relative_missing_or_wrong_named_resources_refuse(self):
        for name in ('python','module_root','heap_helper','cooperative','data_directory'):
            with self.subTest(name=name),self.assertRaises(launch.LaunchError):
                self.argv(prediction_worker=replace(self.options,**{name:Path('relative')}))
        bad=self.root/'OtherHeap.dll';bad.write_bytes(b'authored')
        with self.assertRaisesRegex(launch.LaunchError,'names'):
            self.argv(prediction_worker=replace(self.options,heap_helper=bad))
        (self.options.module_root/'client_patch/prediction_worker/__main__.py').unlink()
        with self.assertRaisesRegex(launch.LaunchError,'closure'):
            self.argv(prediction_worker=self.options)

    def test_data_cannot_be_an_immutable_program_root(self):
        with self.assertRaisesRegex(launch.LaunchError,'separate'):
            self.argv(prediction_worker=replace(self.options,data_directory=self.options.module_root))

    def test_invalid_launch_options_fail_before_verify_or_ipc(self):
        async def run():
            with mock.patch.object(launch,'verify_game') as verify, mock.patch.object(launch.socket,'socketpair') as pair:
                with self.assertRaisesRegex(launch.LaunchError,'typed'):
                    await launch.launch(self.config,None,self.args,prediction_worker={})
                verify.assert_not_called();pair.assert_not_called()
        asyncio.run(run())

    def test_spawn_forwards_options_and_restores_private_socket_inheritance(self):
        child=mock.Mock();child.fileno.return_value=17
        with mock.patch.object(launch.subprocess,'Popen') as popen:
            launch.spawn_game(self.config,None,self.args,child,prediction_worker=replace(self.options,visual_correction=True))
        argv=popen.call_args.args[0]
        self.assertIn('-prediction-movement-experimental',argv)
        self.assertIn('-prediction-visual-correction',argv)
        self.assertEqual(child.set_inheritable.call_args_list,[mock.call(True),mock.call(False)])

    def test_async_launch_passes_only_validated_options_to_spawn(self):
        options=replace(self.options,visual_correction=True)
        async def run():
            parent,child=mock.Mock(),mock.Mock()
            writer=mock.Mock();writer.wait_closed=mock.AsyncMock()
            game=mock.Mock();game.poll.return_value=0;game.wait.return_value=0
            async def bridge_run():pass
            with mock.patch.object(launch,'verify_game'),mock.patch.object(launch.socket,'socketpair',return_value=(parent,child)), \
                    mock.patch.object(launch.asyncio,'open_connection',new=mock.AsyncMock(return_value=(object(),writer))), \
                    mock.patch.object(launch,'spawn_game',return_value=game) as spawn, \
                    mock.patch.object(launch,'Bridge') as bridge:
                bridge.return_value.run.side_effect=bridge_run
                result=await launch.launch(self.config,None,self.args,prediction_worker=options)
                self.assertEqual(result,0)
                self.assertEqual(spawn.call_args.kwargs['prediction_worker'],options)
                self.assertIs(spawn.call_args.kwargs['prediction_worker'].visual_correction,True)
            child.close.assert_called();writer.close.assert_called()
        asyncio.run(run())


if __name__=='__main__':unittest.main()
