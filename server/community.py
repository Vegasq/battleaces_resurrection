"""Server-owned connected directory, targeted invitations and custom lobby lifetime."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
import uuid

from . import community_protocol as c, protocol as p
from . import loadout_protocol as loadout


class Rejected(ValueError):
    """A valid request cannot be applied to current state; keep the session open."""


def require(condition, reason):
    if not condition:
        raise Rejected(reason)


@dataclass
class Session:
    peer: object
    deck: list[int]
    cosmetics: object = None
    full_loadout: bool = False
    lobby: str | None = None
    practicing: bool = False
    saving: bool = False
    last_request: int = 0
    last_public_ticket: int = 0
    tokens: float = 16.0
    rate_at: float = field(default_factory=time.monotonic)


@dataclass
class Lobby:
    id: str
    host: str
    members: list[str]
    phase: int = c.OPEN
    revision: int = 1
    epoch: int = 0
    ready: set[str] = field(default_factory=set)
    returned: set[str] = field(default_factory=set)
    match_id: str | None = None
    room: object = None
    deadline: float = 0.0
    activity: float = field(default_factory=time.monotonic)


@dataclass
class Invite:
    id: str
    lobby: str
    sender: str
    target: str
    expires: float


class Community:
    def __init__(self, server, *, invite_timeout=30.0, start_timeout=10.0):
        self.server = server
        self.invite_timeout, self.start_timeout = invite_timeout, start_timeout
        self.sessions, self.lobbies, self.invites = {}, {}, {}
        self.revision, self.directory_rows = 0, ()
        self.portrait_rows = ()
        self.maintenance = None
        self.launches = set()
        self.closing = False
        from .public_matchmaking import PublicMatchmaking
        self.public = PublicMatchmaking(self)

    def start(self):
        self.maintenance = asyncio.create_task(self.maintain())

    @staticmethod
    def send(peer, kind, payload):
        if peer.closed:
            return
        try:
            peer.send(kind, payload)
        except p.ProtocolError:
            # A slow directory consumer must not abort other players' rooms.
            peer.close('community output stalled')

    def publish_presence(self, *, recipient=None):
        rows = []
        portraits = {}
        for peer in self.server.peers:
            if peer.closed or peer.profile_id is None:
                continue
            session = self.sessions.get(peer.profile_id)
            if peer.community and session is None:
                continue
            lobby = self.lobbies.get(session.lobby) if session else None
            if session:
                public = self.public.busy(peer.profile_id)
                status = (self.public.status(peer.profile_id) if public else c.UNAVAILABLE if session.practicing or session.saving
                          else c.AVAILABLE if not lobby else c.IN_LOBBY if lobby.phase < c.LOADING else c.IN_MATCH)
                invitable = lobby is None and not session.practicing and not session.saving and not public
            else:
                status = c.IN_MATCH if peer.room and peer.room.state not in ('lobby', 'completed', 'closed') else c.IN_LOBBY
                invitable = False  # Legacy clients cannot receive invitation messages.
            rows.append((peer.profile_id, peer.name, status, invitable))
            # Re-derive from validated slots, never a caller's derived portrait ID
            # or a disk profile changed after this session's selection was frozen.
            portrait = 0
            if session and session.cosmetics and self.server.cosmetic_catalog:
                try:
                    portrait = self.server.cosmetic_catalog.validate_selection(session.cosmetics.slots).portrait
                except ValueError:
                    pass  # An unavailable/foreign selection gets the client fallback.
            portraits[peer.profile_id] = portrait
        rows = tuple(sorted(rows))
        portrait_rows = tuple(sorted(portraits.items()))
        changed = rows != self.directory_rows or portrait_rows != self.portrait_rows
        if changed:
            self.directory_rows = rows
            self.portrait_rows = portrait_rows
            self.revision += 1
        if changed or recipient:
            packets = {}
            targets = [recipient] if recipient and not changed else [s.peer for s in self.sessions.values()]
            for peer in targets:
                version = peer.community_version
                if version not in packets:
                    packets[version] = ((c.DIRECTORY_PORTRAITS, c.directory_portraits(
                        self.revision, rows, self.server.cosmetic_catalog.sha256 if self.server.cosmetic_catalog else '0'*64,
                        portraits)) if version == c.PORTRAIT_VERSION else (c.DIRECTORY, c.directory(self.revision, rows)))
                kind, packet = packets[version]
                self.send(peer, kind, packet)

    async def register(self, peer, profile, name):
        peer.profile_id, peer.name, peer.community = profile, name, True
        try:
            state = await self.server.profile_io.load_state(profile, self.server.template.default_decks[0])
            deck, cosmetics = list(state.deck), state.cosmetics
        except (ValueError, KeyError, OSError) as error:
            deck = list(self.server.template.default_decks[0])
            cosmetics = self.server.cosmetic_catalog.normalize_local() if self.server.cosmetic_catalog else None
            self.server.audit('profile_load_fallback', profile=profile, reason=str(error))
        require(not self.closing and not self.server.closing and not peer.closed, 'connection closed during profile load')
        self.sessions[profile] = Session(peer, list(deck), cosmetics=cosmetics)
        self.send(peer, c.WELCOME, c.welcome(profile, deck, version=peer.community_version))
        self.publish_presence(recipient=peer)
        self.server.audit('community_joined', profile=profile, name=name)

    def require_session(self, session):
        require(not self.closing and not self.server.closing and not session.peer.closed and
                self.sessions.get(session.peer.profile_id) is session, 'player session changed or closed')

    async def save_loadout(self, session, deck, cosmetics):
        self.require_session(session)
        require(not session.saving, 'profile selection is still saving')
        session.saving = True
        self.publish_presence()
        try:
            await self.server.profile_io.save(session.peer.profile_id, deck, cosmetics=cosmetics)
            self.require_session(session)
        finally:
            session.saving = False
            self.publish_presence()

    def publish_lobby(self, lobby, reason=''):
        lobby.revision += 1
        packets = {}
        for profile in lobby.members:
            session = self.sessions[profile]
            if session.full_loadout not in packets:
                packets[session.full_loadout] = c.lobby_state(lobby, self.sessions, reason, complete=session.full_loadout)
            self.send(session.peer, loadout.LOBBY_LOADOUT if session.full_loadout else c.LOBBY, packets[session.full_loadout])
        self.publish_presence()

    def resolve_invite(self, invite, status):
        self.invites.pop(invite.id, None)
        packet = c.invitation(invite, status, 0)
        for profile in (invite.sender, invite.target):
            if profile in self.sessions:
                self.send(self.sessions[profile].peer, c.INVITATION, packet)
        self.server.audit('custom_invite_resolved', invite=invite.id, status=status)

    def cancel_invites(self, predicate, status=c.CANCELLED):
        for invite in list(self.invites.values()):
            if predicate(invite):
                self.resolve_invite(invite, status)

    def member_lobby(self, session, identity=None):
        lobby = self.lobbies.get(session.lobby)
        require(lobby is not None and (identity is None or identity == lobby.id), 'custom lobby changed')
        return lobby

    def cancel_start(self, lobby, reason):
        lobby.phase, lobby.deadline = c.OPEN, 0.0
        lobby.epoch += 1  # Old readiness acknowledgements cannot start a new attempt.
        lobby.ready.clear()
        self.publish_lobby(lobby, reason)

    def remove_member(self, profile, lobby):
        session = self.sessions[profile]
        self.cancel_invites(lambda i: i.lobby == lobby.id)
        lobby.members.remove(profile)
        lobby.ready.discard(profile)
        lobby.returned.discard(profile)
        session.lobby = None
        self.send(session.peer, loadout.LOBBY_LOADOUT if session.full_loadout else c.LOBBY,
                  c.lobby_state(None, self.sessions, complete=session.full_loadout))
        if not lobby.members:
            self.lobbies.pop(lobby.id, None)
        else:
            if lobby.host == profile:
                lobby.host = lobby.members[0]
            if lobby.phase == c.STARTING:
                self.cancel_start(lobby, 'player left before start')
            elif lobby.phase == c.RESULTS and set(lobby.members) <= lobby.returned:
                self.reopen(lobby)
            else:
                self.publish_lobby(lobby)

    def reopen(self, lobby):
        lobby.phase, lobby.match_id, lobby.room = c.OPEN, None, None
        lobby.ready.clear()
        lobby.returned.clear()
        lobby.activity = time.monotonic()
        self.publish_lobby(lobby)

    async def disconnect(self, peer):
        profile = peer.profile_id
        session = self.sessions.get(profile)
        if session is None or session.peer is not peer:
            return
        await self.public.disconnect(session)
        lobby = self.lobbies.get(session.lobby)
        self.cancel_invites(lambda i: profile in (i.sender, i.target))
        if lobby:
            self.remove_member(profile, lobby)
        self.sessions.pop(profile, None)
        if peer.room:
            room = peer.room
            await room.detach(peer, 'player disconnected')
            room.peers.pop(peer.slot, None)
            peer.room = None
        self.publish_presence()
        self.server.audit('community_left', profile=profile)

    async def handle(self, peer, kind, payload):
        if kind in (p.INPUT, p.LOADED):
            p.require(peer.room is not None, 'match message without an assigned match')
            if peer.room.state in ('completed', 'closed'):
                return  # Discard already-in-flight input/loaded packets after a result/abort.
            await peer.room.on_message(peer, kind, payload)
            return
        session = self.sessions[peer.profile_id]
        command = c.decode_command(kind, payload)
        p.require(command['request'] > session.last_request, 'community request IDs must increase')
        session.last_request = command['request']
        now = time.monotonic()
        session.tokens = min(16.0, session.tokens + max(0, now - session.rate_at) * 8)
        session.rate_at = now
        p.require(session.tokens >= 1, 'community command rate exceeded')
        session.tokens -= 1
        try:
            object_id = await self.apply(session, kind, command, now)
        except Rejected as error:
            self.send(peer, c.ACK, c.acknowledgement(command['request'], kind, False, str(error)))
        else:
            self.send(peer, c.ACK, c.acknowledgement(command['request'], kind, True, object_id=object_id or ''))

    async def apply(self, session, kind, command, now):
        profile = session.peer.profile_id
        self.require_session(session)
        require(not session.saving or kind == c.REFRESH, 'profile selection is still saving')
        from . import public_protocol as public
        if kind in public.COMMANDS:
            return await self.public.apply(session, kind, command, now)
        require(not self.public.busy(profile) or kind == c.REFRESH, 'finish or cancel public matchmaking first')
        if kind == c.PRACTICE:
            require(session.lobby is None and session.peer.room is None, 'leave the multiplayer lobby before practice')
            session.practicing = command['active']
            if session.practicing:
                self.cancel_invites(lambda i: i.target == profile or i.sender == profile, c.BUSY)
            self.publish_presence()
            self.server.audit('community_practice', profile=profile, active=session.practicing)
            return
        if kind == c.CREATE:
            require(not session.practicing, 'finish practice before creating a lobby')
            require(command['mode'] == 1, 'only custom 1v1 is supported')
            require(session.lobby is None, 'already in a custom lobby')
            require(self.server.room_count() < self.server.max_rooms, 'room capacity reached')
            lobby = Lobby(uuid.uuid4().hex, profile, [profile])
            self.lobbies[lobby.id] = lobby
            session.lobby = lobby.id
            self.cancel_invites(lambda i: i.target == profile, c.BUSY)
            self.publish_lobby(lobby)
            self.server.audit('custom_lobby_created', lobby=lobby.id, host=profile)
            return lobby.id
        if kind == c.REFRESH:
            self.publish_presence(recipient=session.peer)
            return
        if kind in (c.SET_DECK, loadout.SET_LOADOUT):
            lobby_id = session.lobby
            lobby = self.lobbies.get(session.lobby)
            require(not lobby or lobby.phase == c.OPEN or
                    (lobby.phase == c.RESULTS and profile in lobby.returned), 'deck is frozen for this match')
            try:
                cosmetics = (command['cosmetics'].validate(self.server.cosmetic_catalog)
                             if kind == loadout.SET_LOADOUT else session.cosmetics)
                await self.save_loadout(session, command['deck'], cosmetics)
            except ValueError as error:
                raise Rejected(str(error)) from error
            except OSError as error:
                self.server.audit('profile_save_failed', profile=profile, reason=repr(error))
                raise Rejected('profile save unavailable') from error
            require(session.lobby == lobby_id and self.lobbies.get(lobby_id) is lobby and
                    (not lobby or lobby.phase == c.OPEN or
                     (lobby.phase == c.RESULTS and profile in lobby.returned)), 'lobby changed while saving selection')
            session.deck, session.cosmetics = list(command['deck']), cosmetics
            if kind == loadout.SET_LOADOUT: session.full_loadout = True
            self.publish_presence()
            self.server.audit('community_loadout_saved', profile=profile, complete=kind == loadout.SET_LOADOUT,
                              catalog=cosmetics.catalog_sha256 if cosmetics else None, slots=len(cosmetics.slots) if cosmetics else 0)
            if lobby:
                lobby.ready.clear()
                lobby.activity = now
                self.publish_lobby(lobby)
            return
        if kind in (c.REPLY, c.CANCEL):
            invite = self.invites.get(command['invite'])
            require(invite is not None, 'invitation is no longer pending')
            require(profile == (invite.target if kind == c.REPLY else invite.sender), 'invitation belongs to another player')
            if now >= invite.expires:
                self.resolve_invite(invite, c.EXPIRED)
                raise Rejected('invitation expired')
            if kind == c.CANCEL or not command['accept']:
                self.resolve_invite(invite, c.CANCELLED if kind == c.CANCEL else c.DECLINED)
                return invite.id
            lobby = self.lobbies.get(invite.lobby)
            require(not session.practicing and not session.saving, 'finish practice or profile save before accepting an invitation')
            require(session.lobby is None, 'already in a custom lobby')
            require(lobby and lobby.host == invite.sender and lobby.phase == c.OPEN and len(lobby.members) < 2,
                    'invited lobby is unavailable')
            lobby.members.append(profile)
            session.lobby = lobby.id
            lobby.activity = now
            self.resolve_invite(invite, c.ACCEPTED)
            self.cancel_invites(lambda i: i.target == profile or i.lobby == lobby.id, c.BUSY)
            self.publish_lobby(lobby)
            return lobby.id
        if kind == c.RETURN:
            lobby = self.member_lobby(session)
            require(lobby.phase == c.RESULTS and lobby.match_id == command['match'], 'match has not finished or changed')
            require(profile not in lobby.returned, 'already returned from match')
            room = session.peer.room
            if room:
                await room.detach(session.peer, 'returned to custom lobby')
                room.peers.pop(session.peer.slot, None)
                session.peer.room, session.peer.slot = None, None
                session.peer.next_input, session.peer.joined_army = 0, False
            lobby.returned.add(profile)
            if set(lobby.members) <= lobby.returned:
                self.reopen(lobby)
            else:
                self.publish_lobby(lobby)
            return
        lobby = self.member_lobby(session, command.get('lobby'))
        if kind == c.INVITE:
            require(lobby.phase == c.OPEN and lobby.host == profile and len(lobby.members) < 2,
                    'only the host of an open lobby can invite')
            target = self.sessions.get(command['target'])
            require(command['target'] != profile, 'cannot invite yourself')
            require(target is not None and not target.peer.closed and target.lobby is None and not target.practicing and not target.saving
                    and not self.public.busy(command['target']), 'player is not available')
            require(not any(i.sender == profile and i.target == command['target'] for i in self.invites.values()),
                    'invitation already pending')
            require(len(self.invites) < 128 and sum(i.sender == profile or i.target == profile for i in self.invites.values()) < 8
                    and sum(i.target == command['target'] for i in self.invites.values()) < 8, 'invitation capacity reached')
            invite = Invite(uuid.uuid4().hex, lobby.id, profile, command['target'], now + self.invite_timeout)
            self.invites[invite.id] = invite
            packet = c.invitation(invite, c.PENDING, int(self.invite_timeout * 1000))
            self.send(session.peer, c.INVITATION, packet)
            self.send(target.peer, c.INVITATION, packet)
            lobby.activity = now
            self.server.audit('custom_invite_created', invite=invite.id, lobby=lobby.id, sender=profile, target=invite.target)
            return invite.id
        if kind == c.LEAVE:
            require(lobby.phase in (c.OPEN, c.STARTING), 'return from the match before leaving the lobby')
            self.remove_member(profile, lobby)
            self.publish_presence()
            return
        if kind == c.START:
            require(lobby.host == profile, 'only the host can start')
            require(lobby.phase == c.OPEN and len(lobby.members) == 2, 'custom lobby needs two players')
            require(not any(self.sessions[member].saving for member in lobby.members), 'wait for profile selections to finish saving')
            require(command['revision'] == lobby.revision, 'custom lobby changed; refresh before starting')
            lobby.phase, lobby.deadline = c.STARTING, now + self.start_timeout
            lobby.epoch += 1
            lobby.ready = {profile}  # Native host Start is its readiness acknowledgement.
            self.cancel_invites(lambda i: i.lobby == lobby.id)
            self.publish_lobby(lobby)
            return lobby.id
        if kind == c.READY:
            require(lobby.phase == c.STARTING and command['epoch'] == lobby.epoch, 'start attempt changed')
            require(not any(self.sessions[member].saving for member in lobby.members), 'wait for profile selections to finish saving')
            if now >= lobby.deadline:
                self.cancel_start(lobby, 'start acknowledgement timed out')
                raise Rejected('start acknowledgement expired')
            if not command['ready']:
                self.cancel_start(lobby, 'player cancelled start')
                return
            lobby.ready.add(profile)
            if lobby.ready == set(lobby.members):
                lobby.phase, lobby.deadline = c.LOADING, 0.0
                lobby.returned.clear()
                self.publish_lobby(lobby)
                task = asyncio.create_task(self.server.start_custom_match(lobby))
                self.launches.add(task)
                task.add_done_callback(self.launches.discard)
            else:
                self.publish_lobby(lobby)
            return
        raise p.ProtocolError('unsupported community command')

    def match_running(self, room):
        lobby = self.lobbies.get(room.community_lobby)
        if lobby and lobby.room is room:
            lobby.phase, lobby.match_id = c.RUNNING, room.match_id
            self.publish_lobby(lobby)

    def match_finished(self, room, aborted, reason):
        lobby = self.lobbies.get(room.community_lobby)
        if not lobby or lobby.room is not room or lobby.phase == c.RESULTS:
            return
        if not room.match_id:
            # Failure before any match identity/bootstrap was published needs no
            # native world teardown acknowledgement. Release provisional seats.
            for profile in lobby.members:
                peer = self.sessions[profile].peer
                if peer.room is room:
                    room.peers.pop(peer.slot, None)
                    peer.room, peer.slot = None, None
            lobby.room = None
            self.cancel_start(lobby, reason)
            return
        lobby.phase, lobby.match_id = c.RESULTS, room.match_id
        lobby.ready.clear()
        if aborted:
            for profile in lobby.members:
                self.send(self.sessions[profile].peer, c.ABORTED, c.aborted(room.match_id or '', reason))
        self.publish_lobby(lobby, reason)

    async def maintain(self):
        try:
            while not self.closing:
                await asyncio.sleep(0.1)
                now = time.monotonic()
                self.public.maintain()
                for invite in list(self.invites.values()):
                    if now >= invite.expires:
                        self.resolve_invite(invite, c.EXPIRED)
                for lobby in list(self.lobbies.values()):
                    if lobby.phase == c.STARTING and now >= lobby.deadline:
                        self.cancel_start(lobby, 'start acknowledgement timed out')
                    elif lobby.phase == c.OPEN and now - lobby.activity > self.server.lobby_timeout:
                        for profile in list(lobby.members):
                            self.remove_member(profile, lobby)
                        self.publish_presence()
        except asyncio.CancelledError:
            pass

    async def close(self):
        self.closing = True
        pending = list(self.launches) + ([self.maintenance] if self.maintenance else [])
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self.invites.clear()
