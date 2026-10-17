"""Opt-in custom lobby/rematch verification against a locally imported native DLL.

Uses three scripted TCP clients, not the unfinished graphical custom-menu adapter.
Game data, frame captures and verification output remain under ignored local/.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import traceback
import uuid

from server import community_protocol as c, protocol as p
from server.dedicated_server import DedicatedServer
from server.profiles import ProfileStore
from tools.verify_worker_rooms import Verification, ScriptedPeer, ROOT, require, wait_until, digest


class CommunityVerification(Verification):
    @staticmethod
    def source_hashes():
        values = Verification.source_hashes()
        values.update({name: digest((ROOT / name).read_bytes()) for name in (
            'server/community.py', 'server/community_protocol.py', 'tools/verify_community_native.py')})
        return values

    async def online(self, name):
        reader, writer = await asyncio.open_connection(*self.address[:2])
        peer = ScriptedPeer(reader, writer)
        peer.profile, peer.request = 'native_' + uuid.uuid4().hex, 0
        self.peers.append(peer)
        await peer.send(c.HELLO, c.hello(peer.profile, name))
        data = c.Reader(await peer.receive(c.WELCOME))
        require((data.number('H'), data.number('H')) == (c.VERSION, p.VERSION), 'wrong negotiated version')
        require(data.key() == peer.profile, 'wrong community identity')
        peer.deck = data.deck()
        data.end()
        return peer

    async def command(self, peer, kind, body=b''):
        peer.request += 1
        await peer.send(kind, struct.pack('<I', peer.request) + body)
        reply = c.Reader(await peer.receive(c.ACK, 10))
        require(reply.number('I') == peer.request and reply.number('B') == kind, 'wrong command acknowledgement')
        accepted, reason, identity = reply.flag(), reply.text(), reply.text()
        reply.end()
        require(accepted, 'community command rejected: ' + reason)
        return identity

    async def start_custom(self, lobby, peers):
        for peer in peers:
            peer.observed.clear()  # Retained captures below are scoped to this match.
        await self.command(peers[0], c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision))
        require(lobby.phase == c.STARTING and lobby.room is None, 'host start skipped peer acknowledgement')
        await self.command(peers[1], c.READY, p.encode_string(lobby.id) + struct.pack('<IB', lobby.epoch, 1))
        for peer in peers:
            peer.slot, peer.input_window, peer.deck = p.decode_welcome(await peer.receive(p.WELCOME))
            peer.bootstrap = await peer.receive(p.BOOTSTRAP)
        room = lobby.room
        require(peers[0].bootstrap == peers[1].bootstrap == room.match.gzip_game_data, 'custom bootstrap mismatch')
        folder = self.output / 'matches' / room.match_id
        for peer in peers:
            (folder / f'received-bootstrap-{peer.slot}.pb.gz').write_bytes(peer.bootstrap)
        await asyncio.gather(*(peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest()) for peer in peers))
        await asyncio.gather(*(peer.receive(p.START) for peer in peers))
        require(lobby.phase == c.RUNNING, 'custom lobby did not enter running state')
        return {'room': room, 'worker': room.sim, 'peers': peers, 'folder': folder,
                'frames': [], 'inputs': [], 'started': time.perf_counter()}

    async def complete_custom(self, lobby, session):
        room, worker, peers = session['room'], session['worker'], session['peers']
        for frame in range(self.args.surrender_frame + 60):
            await self.advance(session, frame, surrender=frame == self.args.surrender_frame)
            if room.result is not None and frame >= room.result_frame + 19:
                break
        results = await asyncio.gather(*(peer.receive(p.MATCH_END, 10) for peer in peers))
        require(results[0] == results[1], 'custom clients received different results')
        result = json.loads(results[0])
        native = worker.last_state['game_state']
        require(result['result'] == native and native['complete'], 'result differs from completed native state')
        require(native['winning_alliance'] == 1 and native['army_conceded_flag'] == 1
                and native['game_over_frame'] == self.args.surrender_frame, 'wrong native surrender result')
        await wait_until(lambda: worker.process.poll() is not None, timeout=10)
        require(worker.process.poll() == 0, 'native worker did not exit cleanly')
        self.capture(session, result=result, native_state=worker.last_state)
        for peer in peers:
            await self.command(peer, c.RETURN, p.encode_string(room.match_id))
        require(lobby.phase == c.OPEN and lobby.room is None, 'custom lobby not reusable after both returns')
        require(all(self.server.community.sessions[peer.profile].peer.room is None for peer in peers),
                'custom peers retained old match seats')

    def changed_deck(self, current):
        for slot in range(8):
            for unit in sorted(self.template.catalog):
                candidate = list(current)
                candidate[slot] = unit
                if candidate == current:
                    continue
                try:
                    self.template.validate_deck(candidate)
                except ValueError:
                    continue
                return candidate
        raise AssertionError('no alternate valid deck found in imported catalog')

    async def run(self):
        self.report['scope'] = 'Three community TCP sessions; real native custom 1v1 and same-socket rematch; no graphical UI'
        self.report['community_protocol'] = c.VERSION
        try:
            self.server = DedicatedServer(self.template, ProfileStore(self.output / 'profiles', self.template),
                sim_factory=self.factory, audit=self.event, data_dir=self.output, max_rooms=2, audit_state=True)
            self.address = await self.server.start('127.0.0.1', 0)
            host, guest, bystander = await self.online('Native host'), await self.online('Native guest'), await self.online('Uninvited player')
            identity = await self.command(host, c.CREATE, b'\x01')
            invite = await self.command(host, c.INVITE, p.encode_string(guest.profile))
            require(await self.command(guest, c.REPLY, p.encode_string(invite) + b'\x01') == identity, 'wrong invited lobby')
            lobby = self.server.community.lobbies[identity]
            self.report['lobby'] = identity
            self.report['profile_ids'] = [peer.profile for peer in (host, guest, bystander)]
            for index in range(2):
                if index:
                    selected = self.changed_deck(host.deck)
                    await self.command(host, c.SET_DECK, p.deck_bytes(selected))
                    self.report['rematch_selected_deck'] = selected
                session = await self.start_custom(lobby, (host, guest))
                if index:
                    require(session['room'].decks[host.slot] == selected, 'changed deck not frozen into rematch')
                await self.complete_custom(lobby, session)
                print(f'Custom native match{index + 1}/2 complete;{len(session["frames"])} frames;worker exited0.', flush=True)
            require(len({row['match_id'] for row in self.matches}) == 2, 'match identity reused')
            require(not any(kind in (p.WELCOME, p.BOOTSTRAP, p.START, p.FRAME) for kind, _ in bystander.observed),
                    'uninvited player received match data')
            require(self.server.community.sessions[bystander.profile].lobby is None, 'uninvited player joined lobby')
            self.report['same_connections_rematched'] = True
            self.report['uninvited_player_received_no_match_data'] = True
            self.report['passed'] = True
        except BaseException as error:
            self.report['error'], self.report['traceback'] = repr(error), traceback.format_exc()
            raise
        finally:
            if self.server:
                await self.server.close()
            await asyncio.gather(*(peer.close() for peer in self.peers), return_exceptions=True)
            await asyncio.gather(*(worker.close() for worker in self.workers), return_exceptions=True)
            self.report['worker_cleanup'] = [{'pid': w.pid, 'exit_code': w.process.poll(), 'closed': w.closed} for w in self.workers]
            self.report['all_workers_reaped'] = all(w.process.poll() is not None for w in self.workers)
            self.report['elapsed_seconds'] = time.perf_counter() - self.started
            self.report['source_sha256_at_finish'] = self.source_hashes()
            self.report['source_files_unchanged_during_run'] = self.report['source_sha256_at_start'] == self.report['source_sha256_at_finish']
            self.report['passed'] &= self.report['all_workers_reaped'] and self.report['source_files_unchanged_during_run']
            (self.output / 'verification.json').write_text(json.dumps(self.report, indent=2) + '\n')
            self.audit.close()
            print(f'Evidence: {self.output / "verification.json"}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, default=ROOT / 'local/assets/p0-export03')
    parser.add_argument('--output', type=Path, default=ROOT / 'local' / ('community-native-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--surrender-frame', type=int, default=140)
    args = parser.parse_args()
    if os.name != 'nt' or not 5 <= args.surrender_frame <= 1000:
        parser.error('requires Windows and a surrender frame in5..1000')
    args.matches = 2
    asyncio.run(CommunityVerification(args).run())


if __name__ == '__main__':
    main()
