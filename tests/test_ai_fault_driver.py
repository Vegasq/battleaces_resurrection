"""Four-seat wire ownership and transparent diagnostic RPC delegation."""
from types import SimpleNamespace
import asyncio
import unittest
from server import public_protocol as q
from server.game_data import encode_player_input
from tools.verify_room_faults import observe_worker_rpc,validate_public_frame


class FourSeatTests(unittest.TestCase):
    def fixture(self):
        roster={slot:bytes([slot+1])*8 for slot in range(4)}
        peer=SimpleNamespace(participant_count=4,roster=roster)
        inputs={slot:encode_player_input(identity,[]) for slot,identity in roster.items()}
        return peer,inputs

    def test_four_participants_include_both_native_bot_seats(self):
        peer,inputs=self.fixture()
        self.assertEqual(validate_public_frame(peer,q.frame(9,inputs),9),inputs)

    def test_swapped_bot_identity_cannot_pass_as_its_human_neighbor(self):
        peer,inputs=self.fixture();inputs[1],inputs[2]=inputs[2],inputs[1]
        with self.assertRaisesRegex(AssertionError,'identity ownership'):
            validate_public_frame(peer,q.frame(9,inputs),9)

    def test_two_seat_packet_and_wrong_frame_cannot_qualify_four_seats(self):
        peer,inputs=self.fixture()
        for payload in (q.frame(9,{slot:inputs[slot] for slot in (0,1)}),q.frame(8,inputs)):
            with self.subTest(payload=payload),self.assertRaises((AssertionError,ValueError)):
                validate_public_frame(peer,payload,9)


class ObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_and_arguments_are_delegated_without_copy_or_substitution(self):
        rows=[];calls=[];response=object();metadata={};payload=b'original'
        async def original(*args,**kwargs):
            calls.append((args,kwargs));worker._request_id+=1;return response
        worker=SimpleNamespace(_exchange=original,_request_id=4)
        observe_worker_rpc(worker,rows)
        self.assertIs(await worker._exchange(7,10,metadata,payload,timeout=3),response)
        self.assertEqual(calls,[((7,10,metadata,payload),{'timeout':3})])
        self.assertIs(calls[0][0][2],metadata)
        self.assertEqual((rows[0]['operation'],rows[0]['frame'],rows[0]['status'],rows[0]['request_id_before'],rows[0]['request_id_after']),(7,10,'reply',4,5))

    async def test_original_exception_and_cancellation_are_propagated_by_identity(self):
        for error in (TimeoutError('original deadline'),asyncio.CancelledError()):
            rows=[]
            async def original(*args,**kwargs):raise error
            worker=SimpleNamespace(_exchange=original,_request_id=1)
            observe_worker_rpc(worker,rows)
            with self.subTest(error=type(error).__name__),self.assertRaises(type(error)) as caught:
                await worker._exchange(7,10)
            self.assertIs(caught.exception,error)
            self.assertEqual((rows[0]['status'],rows[0]['error_type']),('error',type(error).__name__))
            self.assertGreaterEqual(rows[0]['ended'],rows[0]['started'])


if __name__=='__main__':unittest.main()
