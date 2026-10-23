"""Public queues with frozen proposals and one authoritative match per commit.

Waiting tickets may be cancelled. All selected humans acknowledge the same
proposal before any worker is created. Bot filling happens at the oldest
ticket's deadline; partially filled groups never split into private matches.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
import uuid

from . import community_protocol as c, public_protocol as q
from . import loadout_protocol as loadout
from .community import Rejected, require


@dataclass
class Entry:
    session: object
    ticket: int
    mode: int
    deck: tuple[int, ...]
    entered: float
    deadline: float
    cosmetics: object = None
    full_loadout: bool = False
    offer: str | None = None

    @property
    def profile(self):
        return self.session.peer.profile_id


@dataclass
class Offer:
    id: str
    mode: int
    entries: tuple[Entry, ...]
    deadline: float
    phase: int = q.OFFERED
    ready: set[str] = field(default_factory=set)
    returned: set[str] = field(default_factory=set)
    room: object = None


class PublicMatchmaking:
    def __init__(self, community, *, offer_timeout=10.0, clock=time.monotonic):
        self.community, self.server = community, community.server
        self.entries, self.offers = {}, {}
        self.offer_timeout = offer_timeout
        self.clock = clock

    def busy(self, profile):
        return profile in self.entries

    def status(self, profile):
        entry = self.entries.get(profile)
        offer = self.offers.get(entry.offer) if entry else None
        return c.IN_MATCH if offer and offer.phase >= q.PREPARING else c.UNAVAILABLE

    def publish(self, entry, phase, *, offer='', reason='', now=None):
        now = self.clock() if now is None else now
        elapsed = min(0xffffffff, int(max(0, now-entry.entered)*1000))
        self.community.send(entry.session.peer, q.STATE, q.state(entry.ticket, phase, entry.mode, elapsed, offer, reason))

    def retire(self, entry, reason):
        if self.entries.get(entry.profile) is not entry:
            return
        self.entries.pop(entry.profile)
        self.publish(entry, q.RETIRED, offer=entry.offer or '', reason=reason)
        self.server.audit('public_ticket_retired', profile=entry.profile, ticket=entry.ticket, reason=reason)

    def dissolve(self, offer, reason, *, remove=()):
        require(offer.phase == q.OFFERED and offer.room is None, 'committed public match cannot be requeued')
        self.offers.pop(offer.id, None)
        for entry in offer.entries:
            if self.entries.get(entry.profile) is not entry:
                continue
            entry.offer = None
            if entry.profile in remove or entry.session.peer.closed:
                self.retire(entry, reason)
            else:
                self.publish(entry, q.WAITING, reason=reason)
        self.community.publish_presence()

    async def apply(self, session, kind, command, now):
        now = self.clock()
        profile = session.peer.profile_id
        self.community.require_session(session)
        require(not session.saving, 'profile selection is still saving')
        require(not self.server.closing and not self.community.closing, 'server is stopping')
        if kind in (q.ENTER, loadout.ENTER_LOADOUT):
            require(not self.busy(profile) and session.lobby is None and not session.practicing and session.peer.room is None,
                    'leave the current activity before public matchmaking')
            require(command['ticket'] > session.last_public_ticket, 'public queue ticket was already used')
            require(command['mode'] in self.server.templates and self.server.bot_catalog is not None and
                    self.server.ai_factory is not None, 'server public mode/bot assets unavailable')
            try:
                deck = self.server.templates[command['mode']].validate_deck(command['deck'])
                cosmetics = (command['cosmetics'].validate(self.server.cosmetic_catalog)
                             if kind == loadout.ENTER_LOADOUT else session.cosmetics)
                await self.community.save_loadout(session, deck, cosmetics)
            except ValueError as error:
                raise Rejected(str(error)) from error
            except OSError as error:
                self.server.audit('profile_save_failed', profile=profile, reason=repr(error))
                raise Rejected('profile save unavailable') from error
            require(not self.busy(profile) and session.lobby is None and not session.practicing and session.peer.room is None,
                    'activity changed while saving public selection')
            remaining = command['wait_ms']/1000
            entry = Entry(session, command['ticket'], command['mode'], tuple(deck),
                          now-(q.FALLBACK_SECONDS-remaining), now+remaining, cosmetics=cosmetics,
                          full_loadout=kind == loadout.ENTER_LOADOUT)
            session.last_public_ticket, session.deck, session.cosmetics = entry.ticket, list(deck), cosmetics
            if entry.full_loadout: session.full_loadout = True
            self.entries[profile] = entry
            self.community.cancel_invites(lambda invite: profile in (invite.sender, invite.target), c.BUSY)
            self.publish(entry, q.WAITING, now=now)
            self.community.publish_presence()
            self.server.audit('public_queue_entered', profile=profile, ticket=entry.ticket, mode=entry.mode, wait_ms=command['wait_ms'])
            self.maintain(now)
            return
        entry = self.entries.get(profile)
        require(entry is not None and entry.session is session and entry.ticket == command['ticket'],
                'public queue ticket changed or retired')
        offer = self.offers.get(entry.offer)
        if kind == q.CANCEL:
            require(offer is None or offer.phase == q.OFFERED, 'public match already committed')
            if offer:
                self.dissolve(offer, 'player cancelled search', remove=(profile,))
            else:
                self.retire(entry, 'search cancelled')
                self.community.publish_presence()
            return
        require(offer is not None and offer.id == command['match'], 'public match proposal changed')
        if kind == q.READY:
            require(offer.phase == q.OFFERED and profile not in offer.ready, 'public proposal already acknowledged')
            if now >= offer.deadline:
                missing = {member.profile for member in offer.entries} - offer.ready
                self.dissolve(offer, 'public proposal acknowledgement timed out', remove=missing)
                raise Rejected('public proposal expired')
            offer.ready.add(profile)
            if offer.ready == {member.profile for member in offer.entries}:
                # This is the single commit point. No further readiness or
                # timeout event may launch another worker for these tickets.
                offer.phase = q.PREPARING
                for member in offer.entries:
                    self.publish(member, q.PREPARING, offer=offer.id, now=now)
                self.community.publish_presence()
                task = asyncio.create_task(self.launch(offer))
                self.community.launches.add(task)
                task.add_done_callback(self.community.launches.discard)
            return offer.id
        require(kind == q.RETURN and offer.phase == q.RESULTS and profile not in offer.returned,
                'public match has not ended or was already returned')
        await self.release_peer(entry, offer.room)
        offer.returned.add(profile)
        self.retire(entry, 'returned to menu')
        if offer.returned == {member.profile for member in offer.entries}:
            self.offers.pop(offer.id, None)
        self.community.publish_presence()

    def maintain(self, now=None):
        now = self.clock() if now is None else now
        if self.server.closing or self.community.closing:
            return
        for offer in list(self.offers.values()):
            if offer.phase == q.OFFERED and now >= offer.deadline:
                missing = {entry.profile for entry in offer.entries} - offer.ready
                self.dissolve(offer, 'public proposal acknowledgement timed out', remove=missing)
        for mode, (_, human_slots) in q.MODES.items():
            while True:
                waiting = sorted((entry for entry in self.entries.values() if entry.mode == mode and entry.offer is None
                                  and not entry.session.peer.closed), key=lambda entry: (entry.entered, entry.profile))
                if not waiting or (len(waiting) < len(human_slots) and now < waiting[0].deadline):
                    break
                if self.server.room_count() >= self.server.max_rooms:
                    for entry in waiting:
                        if now >= entry.deadline:
                            self.retire(entry, 'server match capacity unavailable')
                    self.community.publish_presence()
                    break
                members = tuple(waiting[:len(human_slots)])
                offer = Offer(uuid.uuid4().hex, mode, members, now+self.offer_timeout)
                self.offers[offer.id] = offer
                for entry in members:
                    entry.offer = offer.id
                    self.publish(entry, q.OFFERED, offer=offer.id, now=now)
                self.community.publish_presence()
                self.server.audit('public_match_offered', match=offer.id, mode=mode,
                                  humans=[entry.profile for entry in members],
                                  tickets=[entry.ticket for entry in members], fallback=len(members) < len(human_slots))

    async def launch(self, offer):
        from .dedicated_server import BotSeat, Room
        room = None
        try:
            require(not self.server.closing and not self.community.closing, 'server is stopping')
            require(self.offers.get(offer.id) is offer and offer.phase == q.PREPARING, 'public proposal retired before launch')
            require(all(self.entries.get(entry.profile) is entry and not entry.session.peer.closed
                        and entry.session.peer.room is None for entry in offer.entries), 'public player left before setup')
            count, human_slots = q.MODES[offer.mode]
            humans = dict(zip(human_slots, offer.entries))
            names, bots = {entry.session.peer.name for entry in offer.entries}, []
            for slot in range(count):
                if slot in humans:
                    continue
                role = 'teammates' if offer.mode == 5 and slot == 2 else 'opponents'
                choice = self.server.bot_catalog.choose(offer.mode, role=role, excluded_names=names)
                names.add(choice.name)
                bots.append(BotSeat(slot, choice.profile, choice.name, choice.deck.units, choice))
            name = 'public_' + offer.id
            require(name not in self.server.rooms, 'public match already launched')
            room = Room(self.server, name, bots=bots, mode=offer.mode, public_match=offer.id)
            self.server.rooms[name], offer.room = room, room
            for slot, entry in humans.items():
                peer = entry.session.peer
                peer.next_input, peer.joined_army = 0, False
                await room.join(peer, slot, entry.profile, peer.name, deck=entry.deck, ticket=entry.ticket,
                          cosmetics=entry.cosmetics, full_loadout=entry.full_loadout)
                room.ready.add(slot)
            await room.prepare_match()
            if room.state == 'loading' and self.offers.get(offer.id) is offer:
                offer.phase = q.LOADING
                for entry in offer.entries:
                    if self.entries.get(entry.profile) is entry:
                        self.publish(entry, q.LOADING, offer=offer.id)
        except BaseException as error:
            if room:
                await room.finish('public match setup failed', aborted=True)
            elif self.offers.get(offer.id) is offer:
                self.offers.pop(offer.id, None)
                for entry in offer.entries:
                    self.retire(entry, 'public match setup failed')
                self.community.publish_presence()
            if not isinstance(error, Exception):
                raise
            self.server.audit('public_match_setup_error', match=offer.id, error=repr(error))

    def match_running(self, room):
        offer = self.offers.get(room.public_match)
        if offer and offer.room is room:
            offer.phase = q.RUNNING
            for entry in offer.entries:
                if self.entries.get(entry.profile) is entry:
                    self.publish(entry, q.RUNNING, offer=offer.id)
            self.community.publish_presence()

    def match_finished(self, room, aborted, reason):
        offer = self.offers.get(room.public_match)
        if not offer or offer.room is not room or offer.phase == q.RESULTS:
            return
        # Native validation or evidence-file creation does not publish a match.
        # Once assignment delivery begins, preserve even a partially sent ID.
        if room.state == 'closed' and not room.assignment_started:
            self.offers.pop(offer.id, None)
            for entry in offer.entries:
                peer = entry.session.peer
                if peer.room is room:
                    room.peers.pop(peer.slot, None)
                    peer.room, peer.slot = None, None
                self.retire(entry, reason)
        else:
            offer.phase = q.RESULTS
            for entry in offer.entries:
                if self.entries.get(entry.profile) is entry:
                    if aborted:
                        self.community.send(entry.session.peer, c.ABORTED, c.aborted(offer.id, reason))
                    self.publish(entry, q.RESULTS, offer=offer.id, reason=reason)
        self.community.publish_presence()

    async def release_peer(self, entry, room):
        peer = entry.session.peer
        if room and peer.room is room:
            await room.detach(peer, 'returned from public match')
            room.peers.pop(peer.slot, None)
            peer.room, peer.slot = None, None
            peer.next_input, peer.joined_army = 0, False

    async def disconnect(self, session):
        entry = self.entries.get(session.peer.profile_id)
        if entry is None or entry.session is not session:
            return
        offer = self.offers.get(entry.offer)
        if offer and offer.phase == q.OFFERED:
            self.dissolve(offer, 'public player disconnected', remove=(entry.profile,))
        elif offer:
            if offer.room:
                await offer.room.detach(session.peer, 'public player disconnected')
                await self.release_peer(entry, offer.room)
            offer.returned.add(entry.profile)
            self.retire(entry, 'public player disconnected')
            if offer.returned == {member.profile for member in offer.entries}:
                self.offers.pop(offer.id, None)
        else:
            self.retire(entry, 'public player disconnected')
