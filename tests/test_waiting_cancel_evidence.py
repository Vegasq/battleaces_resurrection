import copy
import unittest
from tools.packaged_network_evidence import validate_waiting_cancel


class WaitingCancelEvidenceTests(unittest.TestCase):
    def fixture(self,mode=2):
        deck=list(range(1,9));appearance=dict(catalog_sha256='a'*64,slots={str(i):i for i in range(1,18)})
        events=[dict(event='public_queue_entered',profile='p1',ticket=1,mode=mode),
                dict(event='public_ticket_retired',profile='p1',ticket=1,reason='search cancelled'),
                dict(event='public_queue_entered',profile='p1',ticket=2,mode=mode)]
        log='\n'.join(('Dedicated deck smoke rematch-after units=[1,2,3,4,5,6,7,8] abilities=[9,10,11,12]',
            f'[1000] Public search intent: ticket=1 mode={mode} originalSearch=1',
            '[4000] Native search original Cancel invoked: ticket=1 automated',
            '[4000] PUBLIC QUEUE SMOKE cancellation: ticket=1 point=waiting noWorld=1',
            'Native search released: ticket=1 reason=cancel requested status=0',
            'Public intent retired: ticket=1 reason=cancelled nativeIdle=1 disconnect=0',
            'PUBLIC QUEUE SMOKE waiting for retry gate: key=a',
            'PUBLIC QUEUE SMOKE retry gate released: key=a',
            f'[5100] Public search intent: ticket=2 mode={mode} originalSearch=1',
            'Native search stale ticket rejected: retired=1 current=2 panelRetained=1'))
        clients=[dict(player='p1',log=log)]
        selections=[dict(profile='p1',ticket=t,mode=mode,full_loadout=True,deck=deck.copy(),cosmetics=copy.deepcopy(appearance)) for t in (1,2)]
        frozen=dict(humans={'0':dict(profile='p1')},decks={'0':deck.copy()},cosmetics={'0':copy.deepcopy(appearance)},active_ability_groups={'0':[9,10,11,12]})
        live=dict.fromkeys(('rooms','retired','entries','offers','cleanup','active_workers'),0);live['sessions']=1
        return dict(events=events,clients=clients,selections=selections,frozen=frozen,before_retry=live,mode=mode)

    def test_owned_waiting_cancel_binds_both_tickets_and_saved_selection(self):
        self.assertEqual(validate_waiting_cancel(**self.fixture())['cancel_elapsed_ms'],3000)

    def test_mode_is_bound_to_events_native_intents_and_loadouts(self):
        self.assertEqual(validate_waiting_cancel(**self.fixture(mode=5))['mode'],5)
        for field in ('events','selections','clients'):
            changed=self.fixture(mode=5);old=self.fixture(mode=2);changed[field]=old[field]
            with self.subTest(field=field),self.assertRaises(AssertionError):validate_waiting_cancel(**changed)
        changed=self.fixture();changed['mode']=4
        with self.assertRaises(AssertionError):validate_waiting_cancel(**changed)

    def test_1v1_cancellation_requires_1v1_native_and_server_tickets(self):
        self.assertEqual(validate_waiting_cancel(**self.fixture(mode=1))['mode'],1)
        for field in ('events','selections','clients'):
            changed=self.fixture(mode=1);changed[field]=self.fixture(mode=2)[field]
            with self.subTest(field=field),self.assertRaises(AssertionError):validate_waiting_cancel(**changed)

    def test_rejects_missing_cancel_wrong_generation_and_early_world(self):
        changes=[lambda f:f['events'].pop(1),
                 lambda f:f['events'][2].update(ticket=1),
                 lambda f:f['events'][1].update(reason='player disconnected'),
                 lambda f:f['before_retry'].update(active_workers=1),
                 lambda f:f['events'].insert(1,dict(event='worker_started')),
                 lambda f:f['clients'][0].update(log=f['clients'][0]['log'].replace('noWorld=1','noWorld=0')),
                 lambda f:f['clients'][0].update(log='Client world acquired: early\n'+f['clients'][0]['log']),
                 lambda f:f['clients'][0].update(log=f['clients'][0]['log'].replace('[4000] PUBLIC','[3999] PUBLIC')),
                 lambda f:f['clients'][0].update(log=f['clients'][0]['log'].replace('reason=cancelled nativeIdle=1','reason=cancelled nativeIdle=0'))]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                fixture=self.fixture();change(fixture)
                with self.assertRaises(AssertionError):validate_waiting_cancel(**fixture)

    def test_wire_object_and_frozen_pairs_match_without_ignoring_duplicates(self):
        fixture=self.fixture();appearance=fixture['frozen']['cosmetics']['0']
        appearance['slots']=[[int(k),v] for k,v in appearance['slots'].items()]
        self.assertTrue(validate_waiting_cancel(**fixture)['passed'])
        appearance['slots'][-1]=appearance['slots'][0]
        with self.assertRaises(AssertionError):validate_waiting_cancel(**fixture)

    def test_rejects_lost_choices_or_wrong_final_identity(self):
        changes=[lambda f:f['selections'][1]['deck'].__setitem__(0,99),
                 lambda f:f['selections'][1]['cosmetics']['slots'].__setitem__('1',99),
                 lambda f:f['selections'][1].update(full_loadout=False),
                 lambda f:f['frozen']['humans']['0'].update(profile='p2'),
                 lambda f:f['frozen']['active_ability_groups']['0'].__setitem__(0,99)]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                fixture=self.fixture();change(fixture)
                with self.assertRaises(AssertionError):validate_waiting_cancel(**fixture)


if __name__=='__main__':unittest.main()
