"""Reject stale-response proofs without active local play and ordered reconnection."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from client_patch.transport import bridge
from server import protocol as p,public_protocol as q,loadout_protocol as loadout
from tools.public_late_assignment import Probe,WitnessBridge,validate,local_evidence,sha


class LateAssignmentEvidenceTests(unittest.TestCase):
    def fixture(self,mode=1):
        first='a'*32;last='b'*32;count=2 if mode==1 else 4
        def line(text):return '[1000] '+text+'\n'
        def remote(ticket,generation,key):return ''.join(map(line,[
            f'Public search intent: ticket={ticket} mode={mode} originalSearch=1 deadlineMs=30000 BA_RESURRECTION_PUBLIC_QUEUE_V1',
            f'Client world acquired: generation={generation} owner=remote match={key}',
            f'Public native match joined: ticket={ticket} match={key} mode={mode} participants={count} seat=0 remoteWorld=1',
            f'Public result Continue routed: mode={mode} source=remote next=End rewards=0 progressionUnchanged=1 publicModePreserved=1',
            f'Client world released: generation={generation} owner=remote nativeIdle=1',
            f'Public native return: ticket={ticket} match={key} aborted=0 nativeIdle=1',
            f'Public intent retired: ticket={ticket} reason='+('connection lost after return nativeIdle=1 disconnect=1' if ticket==1 else 'returned nativeIdle=1 disconnect=0')]))
        prefix=line('PUBLIC LATE ASSIGNMENT SMOKE maxIntents=3 practiceProfile=19 BA_RESURRECTION_LATE_ASSIGNMENT_V2')+remote(1,1,first)+''.join(map(line,[
            f'Public search intent: ticket=2 mode={mode} originalSearch=1 deadlineMs=30000 BA_RESURRECTION_PUBLIC_QUEUE_V1',
            f'Public fallback accepted: ticket=2 mode={mode} beforeAmbiguousCommit=1 elapsedMs=12 reason=unavailable',
            'Client world acquired: generation=2 owner=local-practice match=',
            'Practice world ready: humanWorld=111 aiWorld=222',
            f'Local AI all ready: bots={count-1} sharedSimulation=1 producers={count}',
            'Practice AI cadence: sim=200 aiUpdated=200']))
        log=prefix+''.join(map(line,[
            'Practice AI cadence: sim=400 aiUpdated=400',
            f'Public result Continue routed: mode={mode} source=local next=End rewards=0 progressionUnchanged=1 publicModePreserved=1',
            'PRACTICE SMOKE native Continue (automated)',
            'Client world released: generation=2 owner=local-practice nativeIdle=1',
            f'Practice returned: completed=1 mode={mode} seat=-1 presenceRetained=0 standalone=1',
            'PUBLIC LATE ASSIGNMENT SMOKE preference preserved before intent3: profile=19']))+remote(3,3,last)
        matches=[dict(ticket=ticket,match=key,result=dict(complete=True),received_frames=1220) for ticket,key in ((1,first),(3,last))]
        capture=dict(ticket=1,mode=mode,match=first,private_session=1,payload_sha256='c'*64,payload_bytes=200)
        injection=dict(old_private_session=1,payload_sha256='c'*64,sequence=5,native_frame=200,native_log_characters=len(prefix))
        events=[dict(event='probe_assignment_captured',**capture),dict(event='probe_late_assignment_injected',**injection)]
        for ticket,key in ((1,first),(3,last)):
            events.extend([dict(event='public_queue_entered',ticket=ticket),dict(event='public_match_offered',tickets=[ticket],match=key),
                dict(event='match_created',match=key),dict(event='match_completed',match=key),dict(event='worker_started',match=key),
                dict(event='public_ticket_retired',ticket=ticket,reason='returned to menu')])
        events.extend([
            dict(event='probe_private_written',sequence=1,kind=bridge.READY,private_session=1,purpose='control'),
            dict(event='probe_private_written',sequence=5,kind=bridge.DATA,private_session=1,purpose='late-assignment',payload_sha256='c'*64,payload_bytes=200),
            dict(event='probe_private_written',sequence=9,kind=bridge.READY,private_session=3,purpose='control')])
        return [log,mode,matches,events,capture,injection]

    def test_remote_local_remote_in_all_modes_and_windows_line_endings(self):
        for mode in (1,2,5):
            for crlf in (False,True):
                with self.subTest(mode=mode,crlf=crlf):
                    args=self.fixture(mode)
                    if crlf:args[0]=args[0].replace('\n','\r\n')
                    result=validate(*args)
                    self.assertTrue(result['ordered_private_stream_barrier'])
                    self.assertEqual(result['original_continue_actions'],3)

    def test_no_third_world_early_delivery_or_no_local_progress_cannot_pass(self):
        for change in ('no_third','early','late','no_progress','wrong_lease','missing_continue','ready2','no_capture','no_delivery','changed_preference'):
            with self.subTest(change=change):
                args=self.fixture()
                if change=='no_third':args[2].pop()
                if change=='early':args[5]['native_log_characters']=1
                if change=='late':args[5]['native_log_characters']=len(args[0])
                if change=='no_progress':args[0]=args[0].replace('sim=400','sim=200')
                if change=='wrong_lease':args[0]=args[0].replace('generation=2 owner=local','generation=4 owner=local')
                if change=='missing_continue':args[0]=args[0].replace('PRACTICE SMOKE native Continue','missing')
                if change=='ready2':args[0]+='[2000] Public READY sent: ticket=2 proposal=unowned\n'
                if change=='no_capture':args[4]=None
                if change=='no_delivery':args[5]=None
                if change=='changed_preference':args[0]=args[0].replace('before intent3: profile=19','before intent3: profile=18')
                with self.assertRaises(AssertionError):validate(*args)

    def test_payload_or_native_identity_changes_are_rejected(self):
        for change in ('capture','injection','wire_payload','wire_session','wire_size','server_identity','failed_result'):
            with self.subTest(change=change):
                args=self.fixture()
                if change=='capture':args[4]['payload_sha256']='d'*64
                if change=='injection':args[5]['payload_sha256']='d'*64
                sent=next(row for row in args[3] if row['event']=='probe_private_written' and row['purpose']=='late-assignment')
                if change=='wire_payload':sent['payload_sha256']='d'*64
                if change=='wire_session':sent['private_session']=2
                if change=='wire_size':sent['payload_bytes']=1
                if change=='server_identity':args[2][1]['match']='d'*32
                if change=='failed_result':args[2][1]['result']['complete']=False
                with self.assertRaises(AssertionError):validate(*args)

    def test_private_stream_must_consume_old_data_before_authenticated_ready3(self):
        for change in ('missing_ready3','ready_before_replay','duplicate_replay','duplicate_sequence','retired_wrongly'):
            with self.subTest(change=change):
                args=self.fixture();events=args[3]
                if change=='missing_ready3':events.pop()
                if change=='ready_before_replay':events[-1]['sequence']=4
                if change=='duplicate_replay':events.insert(-1,deepcopy(events[-2]))
                if change=='duplicate_sequence':events[-1]['sequence']=5
                if change=='retired_wrongly':next(row for row in events if row['event']=='public_ticket_retired')['reason']='disconnected'
                with self.assertRaises(AssertionError):validate(*args)

    def test_extra_server_queue_world_abort_or_client_error_is_rejected(self):
        for change in ('queue2','extra_world','abort','error','fallback_error'):
            with self.subTest(change=change):
                args=self.fixture()
                if change=='queue2':args[3].append(dict(event='public_queue_entered',ticket=2))
                if change=='extra_world':args[0]+='[2000] Client world acquired: generation=4 owner=remote match=x\n'
                if change=='abort':args[3].append(dict(event='match_aborted',match='a'*32))
                if change=='error':args[0]+='[2000] Public client failure: bad\n'
                if change=='fallback_error':args[0]+='[2000] Practice stopped in tick\n'
                with self.assertRaises(AssertionError):validate(*args)


class AssignmentCaptureTests(unittest.TestCase):
    def test_native_player_name_schema_and_post_delivery_movement_scope(self):
        deck=dict(units=list(range(1,9)),entitlements=[dict(cosmeticAssetKeys=[10,20])])
        human=dict(deck=deck,players=[dict(playerHandleWithName=dict(playerName='Public Config Player'))])
        bot=dict(armyId=1,allianceId=1,deck=dict(units=list(range(9,17))),players=[dict(aiProfileId=18)])
        prefix='[1] Public fallback accepted: ticket=2 mode=1\n'
        for army in (human,bot):prefix+='[2] Practice army snapshot: '+json.dumps(army)+'\n'
        for _ in range(2):prefix+='[3] HUMAN COSMETICS frozen message: '+json.dumps(dict(deck=deck))+'\n'
        prefix+='[4] HUMAN COSMETICS SimPlayer passed: full=1\n'
        after='[5] post_delivery_marker\n[6] Practice native JoinArmy validated: army=1 selectedUnits=8\n'
        after+='[7] Public AI identity binding: phase=result name=Original Bot army=1\n'
        log=prefix+after+'[8] Client world released: generation=2 owner=local-practice nativeIdle=1\n'
        with patch('tools.verify_practice_ai.movement_evidence',return_value=({42},{42})) as movement:
            result=local_evidence(log,1,dict(native_log_characters=len(prefix)),deck['units'],[10,20])
            self.assertTrue(result['full_human_appearance'])
            self.assertEqual(result['bots_after_injection'][0]['ordered_moving_units'],[42])
            self.assertIn('post_delivery_marker',movement.call_args.args[0])
            self.assertNotIn('Practice army snapshot:',movement.call_args.args[0])
            with self.assertRaises(AssertionError):
                local_evidence(log.replace('Public Config Player','Other Player'),1,dict(native_log_characters=len(prefix)),deck['units'],[10,20])

    def test_actual_peer_send_is_captured_once_without_changing_forwarded_bytes(self):
        class Peer:
            def __init__(self):self.sent=[]
            def send(self,kind,payload=b''):self.sent.append((kind,payload))
        root=Path(__file__).resolve().parents[1]/'local'
        folder=root/('late-capture-test-'+uuid.uuid4().hex);folder.mkdir()
        try:
            observed=[];probe=Probe(1,folder,lambda event,**fields:observed.append(dict(event=event,**fields)))
            probe.transport=SimpleNamespace(last_session=1)
            peer=Peer();probe.attach_peer(peer);probe.attach_peer(peer)
            selection=loadout.Selection('c'*64,tuple((slot,0) for slot in range(1,18)))
            payload=q.assignment(1,'a'*32,1,0,1,6,list(range(1,9)),cosmetics=selection)
            peer.send(q.STATE,b'not an assignment');peer.send(loadout.MATCH_LOADOUT,payload);peer.send(loadout.MATCH_LOADOUT,payload)
            self.assertEqual(peer.sent,[(q.STATE,b'not an assignment'),(loadout.MATCH_LOADOUT,payload),(loadout.MATCH_LOADOUT,payload)])
            self.assertEqual(probe.packet,p.encode(loadout.MATCH_LOADOUT,payload))
            self.assertEqual((folder/'captured-assignment.bin').read_bytes(),probe.packet)
            self.assertEqual(len(observed),1)
            self.assertEqual(probe.capture['payload_sha256'],sha(probe.packet))
        finally:
            (folder/'captured-assignment.bin').unlink(missing_ok=True);folder.rmdir()


class WitnessBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_writes_and_witnesses_have_identical_stream_order(self):
        class Writer:
            def __init__(self):self.written=[]
            def write(self,value):self.written.append(value)
            async def drain(self):await asyncio.sleep(0)
        writer=Writer();events=[]
        transport=WitnessBridge(None,writer,None,version=2,observe=lambda event,**fields:events.append(dict(event=event,**fields)))
        packet=b'owned assignment';identity=b'p_'+b'a'*32
        await asyncio.gather(transport.send(bridge.DATA,1,packet,probe_injection=True),transport.send(bridge.READY,3,identity))
        self.assertEqual(writer.written,[bridge.encode(bridge.DATA,1,packet,version=2),bridge.encode(bridge.READY,3,identity,version=2)])
        self.assertEqual([row['sequence'] for row in events],[1,2])
        self.assertEqual([row['wire_sha256'] for row in events],[sha(value) for value in writer.written])


if __name__=='__main__':unittest.main()
