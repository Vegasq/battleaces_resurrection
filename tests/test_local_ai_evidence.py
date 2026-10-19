"""Authored native-style records catch cross-army/name/search false positives."""
import json
import unittest
from tools.local_ai_evidence import public_match,public_search


def fixture(mode):
    count=2 if mode==1 else 4
    lines=[f'Practice requested: match={"a"*32} mode={mode} selectedDeckSnapshot=1 standalone=1',
           f'PUBLIC QUEUE SMOKE original OnMapSelected: mode={mode} visible=1 automatedCallback=1',
           'Public AI difficulty snapshot: selected=normal modifierProfile=18 practiceSelectionUnchanged=1']
    resources=[]
    for seat in range(count):
        name='Human' if seat==0 else 'Authored Bot '+str(seat)
        profile=0 if seat==0 else 58 if mode==1 else 59 if mode==2 or seat==2 else 60
        army=dict(armyId=seat,allianceId=seat%2,deck=dict(units=[900+seat]),
                  players=[dict(playerHandleWithName=dict(playerName=name),aiProfileId=profile)],portraitId=700+seat,bannerId=800+seat)
        lines.append('Practice army snapshot: '+json.dumps(army))
        if not seat:continue
        lines.extend(['Practice AI join captured:','Practice AI JoinedGame delivered:',
                      f'Practice effective AI profile: id={profile} expectedTableEntry=1',
                      f'Practice native JoinArmy validated: army={seat} exactSnapshot=1',
                      f'Practice AI entity: frame=1 army={seat} id={100+seat} type={900+seat} position=(1,0,1)',
                      f'Practice AI entity: frame=2 army={seat} id={100+seat} type={900+seat} position=(2,0,1)'])
        action=dict(executeCommand=dict(entityTypeData=[dict(abilityId=12,entityIds=[100+seat])],commandData=dict(targetGroundCommandData={})))
        lines.append(f'Local AI owned action: identity={seat+1} frame=2 protobuf='+json.dumps(action))
        for phase in ('in-game','result'):
            lines.append(f'Public AI identity binding: phase={phase} name={name} modelAi=1 portrait={700+seat} banner={800+seat} portraitChildren=1 bannerChildren=1 live=1 currentMatch=1 army={seat}')
        resources.append(dict(viewer=str(seat%2),army=str(seat),current_supply='10'))
    lines.extend([f'Local AI all ready: bots={count-1} sharedSimulation=1 producers={count}',
                  'Practice native EndOfGameResponse delivered;','PRACTICE SMOKE native Continue (automated)',
                  f'Practice returned: completed=1 mode={mode} seat=-1 presenceRetained=0 standalone=1',
                  'NATIVE QUIT owned menu verified:'])
    return '\n'.join(lines),resources


class LocalAIEvidenceTests(unittest.TestCase):
    def test_each_public_topology_and_bot_pool(self):
        for mode in (1,2,5):
            with self.subTest(mode=mode):
                log,rows=fixture(mode)
                result=public_match(log,rows,mode=mode,display_name='Human')
                self.assertEqual(len(result['bots']),1 if mode==1 else 3)
                self.assertTrue(all(bot['ordered_moving_units'] for bot in result['bots']))
                self.assertEqual(public_match(log.replace('\n','\r\n'),rows,mode=mode,display_name='Human'),result)

    def test_another_armys_supply_or_movement_cannot_cover_missing_bot(self):
        log,rows=fixture(2)
        for missing in (1,2,3):
            with self.subTest(missing=missing):
                changed=log.replace(f'identity={missing+1} frame=2 protobuf=',f'identity=99 frame=2 protobuf=')
                with self.assertRaisesRegex(AssertionError,'move produced'):
                    public_match(changed,rows,mode=2,display_name='Human')
                changed_rows=[dict(row,current_supply='0') if row['army']==str(missing) else row for row in rows]
                with self.assertRaisesRegex(AssertionError,'supply missing'):
                    public_match(log,changed_rows,mode=2,display_name='Human')

    def test_foreign_name_avatar_or_result_ai_flag_is_rejected(self):
        log,rows=fixture(5)
        for changed in (log.replace('phase=result name=Authored Bot 2','phase=result name=Other Name'),
                        log.replace('portrait=702 banner=802','portrait=999 banner=802'),
                        log.replace('phase=result name=Authored Bot 2 modelAi=1','phase=result name=Authored Bot 2 modelAi=0')):
            with self.subTest(changed=changed[-80:]),self.assertRaisesRegex(AssertionError,'profile binding missing'):
                public_match(changed,rows,mode=5,display_name='Human')

    def test_wrong_configured_name_topology_and_mode_are_rejected(self):
        log,rows=fixture(2)
        for changed,mode,name in ((log,2,'Another Human'),(log,5,'Human'),
                                  (log.replace('"allianceId": 0','"allianceId": 1'),2,'Human')):
            with self.subTest(mode=mode,name=name),self.assertRaises(AssertionError):
                public_match(changed,rows,mode=mode,display_name=name)

    def test_native_public_search_orders_ticket_and_retirement(self):
        lines=['Native search began: ticket=7 mode=1 nativeStatus=5 originalPanel=1',
               'Public search intent: ticket=7 mode=1 originalSearch=1 deadlineMs=30000',
               'Public fallback accepted: ticket=7 mode=1 beforeAmbiguousCommit=1',
               'Native search match accepted: ticket=7 status=7',
               'Native search joining signal: ticket=7 mode=1 activeConnection=1 originalRouter=1',
               'Native search released: ticket=7 reason=ready status=0',
               'Client world released: owner=local-practice nativeIdle=1']
        log='\n'.join(lines)
        self.assertEqual(public_search(log,mode=1)['native_status_sequence'],[5,7,0])
        for changed in (log.replace('ticket=7 status=7','ticket=8 status=7'),
                        '\n'.join(lines[:2]+[lines[3],lines[2]]+lines[4:]),
                        log+'\nClient world acquired: owner=remote'):
            with self.subTest(changed=changed[-80:]),self.assertRaises(AssertionError):public_search(changed,mode=1)
