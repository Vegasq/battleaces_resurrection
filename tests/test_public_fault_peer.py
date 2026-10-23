"""Public fault-driver state/ticket bindings against real wire decoders."""
import asyncio
import struct
import unittest
from unittest.mock import AsyncMock
from server import protocol as p,public_protocol as q
from tools.verify_room_faults import Peer


class PublicPeerTests(unittest.IsolatedAsyncioTestCase):
    def peer(self,*payloads):
        reader=asyncio.StreamReader()
        for body in payloads:reader.feed_data(p.encode(q.STATE,body))
        reader.feed_eof()
        peer=Peer(reader,None);peer.ticket=2
        return peer

    async def test_offer_cannot_come_from_retired_ticket(self):
        peer=self.peer(q.state(1,q.OFFERED,1,10,'old'),q.state(2,q.WAITING,1,20),q.state(2,q.OFFERED,1,30,'fresh'))
        state=await peer.public_phase(q.OFFERED)
        self.assertEqual((state['ticket'],state['match']),(2,'fresh'))
        self.assertEqual(len(peer.public_states),3)

    async def test_results_require_both_current_ticket_and_exact_match(self):
        peer=self.peer(q.state(1,q.RESULTS,1,10,'wanted','old'),q.state(2,q.RESULTS,1,20,'other','wrong'),q.state(2,q.RESULTS,1,30,'wanted','server simulation error'))
        state=await peer.public_phase(q.RESULTS,match='wanted')
        self.assertEqual(state['reason'],'server simulation error')
        self.assertEqual(len(peer.public_states),3)

    async def test_malformed_state_never_enters_validated_cache(self):
        body=bytearray(q.state(2,q.RESULTS,1,1,'match','reason'));body[10]=255
        peer=self.peer(bytes(body))
        with self.assertRaises(p.ProtocolError):await peer.public_phase(q.RESULTS)
        self.assertEqual(peer.public_states,[])

    async def test_command_uses_next_shared_request_and_current_ticket(self):
        peer=self.peer();peer.request=7;peer.command=AsyncMock(return_value='')
        await peer.public_command(q.RETURN,match='finished')
        kind,body=peer.command.call_args.args
        parsed=q.decode_command(kind,struct.pack('<I',8)+body)
        self.assertEqual(parsed,dict(request=8,ticket=2,match='finished'))


if __name__=='__main__':unittest.main()
