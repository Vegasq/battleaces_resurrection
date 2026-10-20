"""Actual diagnostic append publication; no game, credentials or ACL changes."""
import ast
import json
import shutil
import unittest
import uuid

from tools import verify_packaged_multiplayer as probe, packaged_network_drivers as drivers


class PackagedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder=probe.ROOT/'local'/('snapshot-read-'+uuid.uuid4().hex)
        self.folder.mkdir()
        self.path=self.folder/'server-live.jsonl'
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.folder.resolve().relative_to((probe.ROOT/'local').resolve())
        shutil.rmtree(self.folder)

    def publisher(self):
        function=next(node for node in ast.parse(drivers.SERVER).body if isinstance(node,ast.FunctionDef) and node.name=='publish')
        namespace=dict(output=self.folder,json=json,snapshot_sequence=0,
                       SNAPSHOT_MAX_BYTES=drivers.SNAPSHOT_MAX_BYTES,SNAPSHOT_MAX_ROW_BYTES=drivers.SNAPSHOT_MAX_ROW_BYTES)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'<actual diagnostic publisher>','exec'),namespace)
        return namespace['publish']

    def test_actual_publisher_appends_while_existing_reader_stays_open(self):
        publish=self.publisher();publish(self.path.name,dict(rooms=1))
        with self.path.open('rb') as held_reader:
            publish(self.path.name,dict(rooms=2))
            self.assertEqual(len(held_reader.read().splitlines()),2)
            self.assertEqual(probe.read_live_snapshot(self.path),dict(rooms=2))

    def test_partial_tail_waits_for_newline_and_complete_corruption_is_refused(self):
        self.publisher()(self.path.name,dict(rooms=1))
        with self.path.open('ab') as writer:
            writer.write(b'{"sequence":2,"snapshot":');writer.flush()
            self.assertEqual(probe.read_live_snapshot(self.path),dict(rooms=1))
            writer.write(b'{"rooms":2}}\n');writer.flush()
            self.assertEqual(probe.read_live_snapshot(self.path),dict(rooms=2))
        with self.path.open('ab') as writer:writer.write(b'{broken}\n')
        with self.assertRaises(ValueError):probe.read_live_snapshot(self.path)

    def test_custom_lobby_state_round_trips_without_premature_quit_readiness(self):
        publish=self.publisher()
        value=dict(rooms=0,retired=0,entries=0,offers=0,cleanup=0,sessions=2,
                   lobbies=[dict(id='authored',phase=0,epoch=2,members=['player-a','player-b'])])
        publish(self.path.name,value)
        actual=probe.read_live_snapshot(self.path)
        self.assertEqual(actual,value)
        self.assertFalse(probe.quit_readiness(actual,custom=True))
        value['lobbies']=[];publish(self.path.name,value)
        self.assertTrue(probe.quit_readiness(probe.read_live_snapshot(self.path),custom=True))

    def test_bad_or_unbounded_snapshots_fail_and_release_their_handles(self):
        for raw in (b'[]\n',b'{broken}\n',b'x'*(drivers.SNAPSHOT_MAX_BYTES+1),b'',
                    b'x'*drivers.SNAPSHOT_MAX_ROW_BYTES+b'\n',
                    b'{"sequence":true,"snapshot":{}}\n',b'{"sequence":1,"snapshot":[]}\n'):
            self.path.write_bytes(raw)
            with self.subTest(bytes=len(raw)),self.assertRaises((AssertionError,ValueError)):
                probe.read_live_snapshot(self.path)
            replacement=self.folder/'next.json';replacement.write_text('{"sequence":1,"snapshot":{"rooms":0}}\n',encoding='utf-8')
            replacement.replace(self.path)
            self.assertEqual(probe.read_live_snapshot(self.path),dict(rooms=0))

    def test_publisher_limits_refuse_growth_before_appending(self):
        publish=self.publisher()
        with self.assertRaises(AssertionError):publish(self.path.name,dict(value='x'*drivers.SNAPSHOT_MAX_ROW_BYTES))
        self.assertFalse(self.path.exists())
        self.path.write_bytes(b'x'*drivers.SNAPSHOT_MAX_BYTES)
        with self.assertRaises(AssertionError):publish(self.path.name,dict(rooms=0))
        self.assertEqual(self.path.stat().st_size,drivers.SNAPSHOT_MAX_BYTES)

    def test_missing_or_unowned_path_is_refused_without_creating_files(self):
        with self.assertRaises(OSError):probe.read_live_snapshot(self.path)
        with self.assertRaises(AssertionError):probe.read_live_snapshot(probe.ROOT/'server-live.jsonl')
        with self.assertRaises(AssertionError):probe.read_live_snapshot(self.folder/'other.json')
        self.assertEqual(list(self.folder.iterdir()),[])


if __name__=='__main__':unittest.main()
