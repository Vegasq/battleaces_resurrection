"""D2 T07/T08: same two native humans complete Custom/local4/Custom/public1/Custom.

Owned original callbacks,fixture TLS and forced final cleanup only;physical,
protected enrollment,bundled entry,native Quit and LAN remain separate gates.
"""
import asyncio
import csv
import hashlib
import json
import re
import time

from tools import custom_transition_evidence as evidence
from tools.public_profile_evidence import expected_players
from tools.verify_practice_ai import movement_evidence
from tools.verify_public_clients import journal_builds
from server import community_protocol as c

require = evidence.require


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run(ctx):
    server, clients, events = ctx.server, ctx.clients, ctx.events
    report, runtime, output = ctx.report, ctx.runtime, ctx.output
    remote_matches, decks, commands, local = [], {}, [], []
    prior_apply = server.community.apply

    async def capture(session, kind, command, now):
        value = dict(command)
        if 'cosmetics' in value:
            selection = value['cosmetics']
            value['cosmetics'] = dict(catalog_sha256=selection.catalog_sha256, slots=selection.slots)
        commands.append(dict(profile=session.peer.profile_id, kind=kind, **value))
        return await prior_apply(session, kind, command, now)

    server.community.apply = capture

    def stage_gate(stage):
        return runtime/f'custom-transition-{ctx.gate_key}-stage-{stage}.ready'

    async def capacity(allow_lobby=False):
        deadline = time.monotonic()+8
        while server.rooms or server.worker_cleanup or server.community.public.entries or server.community.public.offers:
            require(time.monotonic() < deadline, 'transition retained queue/room/worker capacity')
            await asyncio.sleep(.05)
        require(len(server.community.lobbies) == int(allow_lobby), 'transition retained/unexpected Custom lobby')

    def snapshot(log, index):
        from server.cosmetics import CosmeticCatalog
        catalog = CosmeticCatalog(ctx.assets)
        rows = [json.loads(line.split('REMOTE COSMETICS frozen snapshot: ', 1)[1]) for line in log.splitlines()
                if 'REMOTE COSMETICS frozen snapshot: ' in line]
        require(len(rows) == 1 and rows[0]['profile'] == ctx.keys[index] and rows[0]['catalog_sha256'] == catalog.sha256 and
                catalog.validate_selection(rows[0]['slots']) == ctx.selected[index], 'remote frozen full native appearance changed')

    for stage, kind in enumerate(evidence.KINDS, 1):
        await ctx.wait_for(lambda: all(f'CUSTOM TRANSITION waiting for gate: stage={stage} role={role} nativeIdle=1 party=0 ' in row['log']
            for row, role in zip(clients, ('host', 'guest'))), 'native transition gate not reached')
        await capacity()
        if stage == 1:
            require(all(f'BA_RESURRECTION_COSMETICS_PERSIST_V1 ready: profile={key} slots=17 restored=1 writable=1' in row['log']
                        for key, row in zip(ctx.keys, clients)), 'owned canonical cosmetic selections were not restored')
        offsets = [len(row['log']) for row in clients]
        audit_start = len(events)
        with stage_gate(stage).open('xb'):
            pass
        ctx.observe('probe_custom_stage_released', stage=stage, kind=kind)
        if kind == 'C':
            await ctx.wait_for(lambda: all(f'CUSTOM TRANSITION original invitation flow armed: stage={stage} role={role}' in row['log'][offset:]
                for row, role, offset in zip(clients, ('host', 'guest'), offsets)), 'both native Custom profiles/decks not prepared')
            if stage == 1:
                require('DEDICATED REMATCH SMOKE automated native deck edit:' in clients[1]['log'],
                        'existing native deck-edit prerequisite flag/action missing before first invitation')
            with (runtime/f'custom-transition-{ctx.gate_key}-custom-start-{stage}.ready').open('xb'):
                pass
            ctx.observe('probe_custom_invitation_gate_released', stage=stage)
        if kind == 4:
            await ctx.wait_for(lambda: all(f'CUSTOM TRANSITION local returned: stage=2 role={role} practiceCompleted=1 nativeIdle=1' in row['log'][offset:]
                for row, role, offset in zip(clients, ('host', 'guest'), offsets)), 'local Try Deck/results/Continue did not return')
            rows = events[audit_start:]
            require(not any(row['event'] in ('community_joined', 'public_queue_entered', 'public_match_offered',
                'custom_lobby_created', 'match_created', 'worker_started') for row in rows), 'local stage contacted/allocated multiplayer')
            for index, row in enumerate(clients):
                tail, pid = row['log'][offsets[index]:], row['process'].pid
                matches = re.findall(r'Practice requested: match=([0-9a-f]{32}) mode=4 ', tail)
                joins = [json.loads(line.split('Practice original JoinArmy: ', 1)[1]) for line in tail.splitlines()
                         if 'Practice original JoinArmy: ' in line]
                armies = [json.loads(line.split('Practice army snapshot: ', 1)[1]) for line in tail.splitlines()
                          if 'Practice army snapshot: ' in line]
                require(len(matches) == 1 and len(joins) == len(armies) == 2 and
                        armies[0]['players'][0]['playerHandleWithName']['playerName'] == row['name'] and
                        armies[0]['deck']['units'] == decks[index], 'Try Deck changed the configured human name/deck')
                selected = ctx.selected[index]
                frozen = [json.loads(line.split('HUMAN COSMETICS frozen message: ', 1)[1]) for line in tail.splitlines()
                          if 'HUMAN COSMETICS frozen message: ' in line]
                require(len(frozen) == 2 and frozen[0]['deck'] == frozen[1]['deck'] == armies[0]['deck'] and
                        frozen[0]['deck']['entitlements'] == [dict(cosmeticAssetKeys=list(selected.keys))] and
                        all(value.get('portraitId', 0) == selected.portrait and value.get('bannerId', 0) == selected.banner for value in frozen),
                        'Try Deck full frozen selection differs from original Custom')
                require('HUMAN COSMETICS SimPlayer passed:' in tail and 'completeMap=1' in tail and
                        all(any(f'HUMAN COSMETICS identity binding: phase={phase} ' in line and
                            f'portrait={selected.portrait} banner={selected.banner} ' in line for line in tail.splitlines()) for phase in ('in-game', 'result')),
                        'Try Deck human native full appearance/result bindings missing')
                moved, ordered = movement_evidence(tail, set(armies[1]['deck']['units']))
                require(moved & ordered, 'Try Deck bot did not autonomously order and move produced units')
                source = runtime/f'lan-resources-{pid}-{matches[0]}.tsv'
                raw = source.read_bytes()
                resources = list(csv.DictReader(raw.decode('utf-8').splitlines(), delimiter='\t'))
                supply = max(int(value['current_supply']) for value in resources if value['viewer'] == value['army'] == '1')
                require(supply > 0, 'Try Deck bot did not build units')
                (output/source.name).write_bytes(raw)
                local.append(dict(pid=pid, match=matches[0], deck=decks[index], bot_max_supply=supply,
                    produced_units_with_orders_and_position_change=sorted(moved & ordered), resource_sha256=hashlib.sha256(raw).hexdigest()))
            report['local_practice'] = local
        else:
            marker = 'CUSTOM TRANSITION Custom returned: stage='+str(stage)+' role=' if kind == 'C' else 'CUSTOM TRANSITION public returned: stage=4 role='
            await ctx.wait_for(lambda: all(marker+role+' ' in row['log'][offset:] for row, role, offset in zip(clients, ('host', 'guest'), offsets)), 'remote transition match/results/Continue timed out')
            await capacity(allow_lobby=kind == 'C')
            completed = [row for row in events if row['event'] == 'match_completed']
            require(len(completed) == len(ctx.workers) == len(remote_matches)+1 and not any(row['event'] == 'match_aborted' for row in events), 'transition duplicated/aborted remote match')
            result = completed[-1]
            match = result['match']
            require(match not in remote_matches, 'remote transition reused an old match')
            remote_matches.append(match)
            folder = output/'matches'/match
            manifest = json.loads((folder/'match.json').read_bytes())
            require(manifest['bootstrap_sha256'] == sha(folder/'bootstrap.pb.gz') and not manifest['bots'] and
                    set(manifest['profiles'].values()) == {profile for profile, _ in ctx.identities} and
                    set(map(int, manifest['profiles'])) == {0, 1}, 'Custom/public human-only topology differs')
            players = expected_players((folder/'bootstrap.pb.gz').read_bytes(), match, 1)
            canonical = {row['frame']: row['frame_payload_sha256'] for row in events if row['event'] == 'frame_queued' and row['match'] == match}
            stage_clients = []
            for index, row in enumerate(clients):
                tail, pid = row['log'][offsets[index]:], row['process'].pid
                seats = [int(seat) for seat, profile in manifest['profiles'].items() if profile == ctx.identities[index][0]]
                require(len(seats) == 1, 'configured human missing/duplicated')
                seat = seats[0]
                own = players[seat]
                require(own['name'] == row['name'] and own['profile'] == 0 and own['portrait'] == ctx.selected[index].portrait and
                        own['banner'] == ctx.selected[index].banner, 'remote bootstrap changed configured human identity/avatar')
                if index not in decks:
                    decks[index] = own['units']
                require(decks[index] == own['units'], 'mode transition changed selected human deck')
                snapshot(tail, index)
                require(f'REMOTE COSMETICS SimPlayer passed: match={match} army={seat} ' in tail, 'actual ingested remote appearance missing')
                frame = 300+100*seat
                build = re.search(rf'LAN NORMAL BUILD smoke frame{frame} slot{seat} army{seat} [^\r\n]+', tail)
                require(build and 'queued=1 commandQueueDelta=1' in build[0], 'original human build missing after transition')
                source = runtime/f'dedicated-receipts-{pid}-{match}.tsv'
                raw = source.read_bytes()
                receipts = list(csv.DictReader(raw.decode('utf-8').splitlines(), delimiter='\t'))
                require(len(receipts) == len(canonical) >= 600 and [int(value['frame']) for value in receipts] == list(range(len(receipts))) and
                        all(value['sha256'] == canonical[int(value['frame'])] for value in receipts), 'transition native frames differ from authoritative audit')
                (output/source.name).write_bytes(raw)
                stage_clients.append(dict(pid=pid, seat=seat, name=row['name'], deck=own['units'], build_frame=frame,
                    received_frames=len(receipts), receipt_sha256=hashlib.sha256(raw).hexdigest(), complete_appearance=True))
            require(decks[0] != decks[1], 'independent initial selected deck edit missing')
            report['stages'].append(dict(stage=stage, kind=kind, match=match, clients=stage_clients, result=result['result'],
                received_frames=len(canonical), bootstrap_sha256=sha(folder/'bootstrap.pb.gz'), manifest_sha256=sha(folder/'match.json'),
                journal_human_builds=journal_builds(folder/'frames.bin', stage_clients, len(canonical))))
            if kind == 'C':
                lobby = next(iter(server.community.lobbies.values()))
                require(lobby.phase == c.OPEN and len(lobby.members) == 2 and not lobby.room, 'original Custom lobby not restored')
                for index, role in ((1, 'guest'), (0, 'host')):
                    gate = runtime/f'custom-transition-{ctx.gate_key}-leave-{stage}-{role}.ready'
                    with gate.open('xb'):
                        pass
                    ctx.observe('probe_custom_leave_released', stage=stage, role=role)
                    await ctx.wait_for(lambda index=index, role=role: f'CUSTOM TRANSITION departed: stage={stage} role={role} party=0 prediction=0 pending=0 nativeIdle=1' in clients[index]['log'], 'original Custom Leave did not clear native state')
                await capacity()
        (output/'progress.json').write_text(json.dumps(dict(remote=report['stages'], local=local), indent=2)+'\n')
    await ctx.wait_for(lambda: all('CUSTOM TRANSITION complete: stages=C,local4,C,public1,C role='+role+' worlds=5 ' in row['log']
        for row, role in zip(clients, ('host', 'guest'))), 'final Custom departure not complete')
    require(ctx.attempts == [2, 2] and sorted(ctx.authenticated) == sorted([profile for profile, _ in ctx.identities]*2),
            'Custom/local transition did not obtain exactly one fresh session after local practice')
    require(sum(row['event'] == 'custom_lobby_created' for row in events) == 3 and
            sum(row['event'] == 'public_queue_entered' for row in events) == 2 and
            sum(row['event'] == 'public_match_offered' for row in events) == 1, 'transition lobby/public allocation counts differ')
    require(sum(row['kind'] == c.INVITE for row in commands) == sum(row['kind'] == c.REPLY and row.get('accept', False) for row in commands) == 3,
            'three original invitations/acceptances required')
    report['custom_commands'] = commands
    report['native_sequences'] = [evidence.validate(row['log'], role, remote_matches) for row, role in zip(clients, ('host', 'guest'))]
