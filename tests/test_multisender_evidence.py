"""Reject false three-client invitation success from native/server disagreement."""
from types import SimpleNamespace
import unittest

from tools.verify_custom_multisender import settled_evidence


class MultisenderEvidenceTests(unittest.TestCase):
    def fixture(self,selected='first'):
        profiles=dict(first='multi_first',second='multi_second',target='multi_target')
        ids=dict(first='a'*32,second='b'*32)
        rooms=dict(first='c'*32,second='d'*32)
        sender=profiles[selected];lobby=rooms[selected]
        logs=dict(target=f'MULTI INVITE target accepted original popup: invite={ids[selected]} sender={sender} lobby={lobby} received=2 pendingDelta=1\n'
            f'MULTI INVITE target settled: sender={sender} lobby={lobby} members=2 replyCounter=0 incoming=0 popup=0 world=0\n')
        lobbies={};events=[]
        for role in ('first','second'):
            accepted=role==selected;status,members=(1,2) if accepted else (5,1)
            logs[role]=f'MULTI INVITE host settled: role={role} invite={ids[role]} lobby={rooms[role]} status={status} members={members} replyCounter=0 sent=0 world=0 partyUnchanged=1\n'
            lobbies[rooms[role]]=SimpleNamespace(host=profiles[role],members=[profiles[role]]+(['multi_target'] if accepted else []))
            events.extend([dict(event='custom_invite_created',invite=ids[role],sender=profiles[role],target=profiles['target']),
                           dict(event='custom_invite_resolved',invite=ids[role],status=status)])
        return logs,profiles,lobbies,events

    def test_either_original_popup_sender_can_be_selected(self):
        for role in ('first','second'):
            with self.subTest(role=role):
                result=settled_evidence(*self.fixture(role))
                self.assertEqual(result['selected_role'],role)
                self.assertTrue(result['native_unselected_party_unchanged'])

    def test_unrelated_player_moved_or_duplicated_group_is_rejected(self):
        for change in ('target_in_losing_lobby','wrong_host','extra_lobby','missing_target','duplicate_member'):
            with self.subTest(change=change):
                args=list(self.fixture());rooms=args[2]
                if change=='target_in_losing_lobby':rooms['d'*32].members.append('multi_target')
                if change=='wrong_host':rooms['d'*32].host='multi_first'
                if change=='extra_lobby':rooms['e'*32]=SimpleNamespace(host='other',members=['other'])
                if change=='missing_target':rooms['c'*32].members.remove('multi_target')
                if change=='duplicate_member':rooms['c'*32].members.append('multi_target')
                with self.assertRaises(AssertionError):settled_evidence(*args)

    def test_native_pending_credits_popup_or_wrong_resolution_is_rejected(self):
        for role,before,after in (('target','replyCounter=0','replyCounter=1'),('target','popup=0','popup=1'),
                                  ('target','received=2','received=1'),('second','partyUnchanged=1','partyUnchanged=0'),
                                  ('second','status=5','status=1'),('first','members=2','members=1')):
            with self.subTest(role=role,change=after):
                args=list(self.fixture());args[0][role]=args[0][role].replace(before,after)
                with self.assertRaises(AssertionError):settled_evidence(*args)

    def test_duplicate_accept_unknown_sender_or_wrong_invite_id_is_rejected(self):
        for change in ('duplicate','unknown_sender','wrong_invite','missing_busy','wrong_target'):
            with self.subTest(change=change):
                args=list(self.fixture());logs,profiles,rooms,events=args
                if change=='duplicate':logs['target']+=logs['target']
                if change=='unknown_sender':logs['target']=logs['target'].replace('multi_first','unrelated')
                if change=='wrong_invite':logs['first']=logs['first'].replace('a'*32,'e'*32)
                if change=='missing_busy':events.pop()
                if change=='wrong_target':events[2]['target']='unrelated'
                with self.assertRaises(AssertionError):settled_evidence(*args)


if __name__=='__main__':unittest.main()
