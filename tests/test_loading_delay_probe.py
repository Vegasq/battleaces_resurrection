import copy
import unittest
from tools import loading_delay_probe as probe


class LoadingDelayTests(unittest.TestCase):
    def fixture(self):
        rows=[]
        def add(kind,tick,**extra):
            rows.append(dict(schema=1,sequence=len(rows)+1,pid=123,tid=456,
                             tick=tick,kind=kind,**extra))
        pending=dict(mapLoading=1,active=0,world=False)
        add('armed',100)
        add('hold-start',1000,**pending)
        for i in range(130):add('hold-sample',1000+i*1000,heldCalls=i+1,**pending)
        add('hold-release',131000,elapsedMs=130000,heldCalls=130,**pending)
        add('complete-enter',131100,**pending)
        add('complete-return',131110,mapLoading=0,active=1,world=True)
        add('cleanup-enter',131120,mapLoading=0,active=1,world=True,reason=1)
        log=('[121100] Dedicated cleanup exceeded 120s; retaining native state, process restart required\n'
             'Public intent retired: ticket=2 reason=returned nativeIdle=1 disconnect=0\n')
        return rows,log

    def test_delayed_original_completion(self):
        rows,log=self.fixture()
        self.assertTrue(probe.validate(rows,log,123)['passed'])

    def test_rejects_premature_cleanup_and_invalid_world(self):
        for changes in (dict(mapLoading=1),dict(reason=2),dict(tick=130999)):
            rows,log=self.fixture();rows[-1].update(changes)
            with self.assertRaises(ValueError):probe.validate(rows,log,123)
        rows,log=self.fixture();rows[-2]['world']=False
        with self.assertRaises(ValueError):probe.validate(rows,log,123)

    def test_requires_timeout_identity_and_continuous_unity_thread(self):
        rows,log=self.fixture()
        for changed,output,pid in ((rows,'',123),(rows,log,124),
                                  (rows,log.replace('121100','131100'),123)):
            with self.assertRaises(ValueError):probe.validate(changed,output,pid)
        for changes in (dict(tid=999),dict(active=1),dict(world=True)):
            changed=copy.deepcopy(rows);changed[50].update(changes)
            with self.assertRaises(ValueError):probe.validate(changed,log,123)

    def test_probe_errors_fail_closed(self):
        rows,log=self.fixture();rows[0]['kind']='error'
        with self.assertRaises(ValueError):probe.validate(rows,log,123)


class PendingLoadQuitTests(unittest.TestCase):
    def fixture(self, count=0):
        rows=[]
        def add(kind,tick,**extra):
            rows.append(dict(schema=1,sequence=len(rows)+1,pid=123,tid=456,tick=tick,kind=kind,**extra))
        pending=dict(mapLoading=1,active=0,world=False)
        observed=dict(**pending,assetLoadingCount=count,wantsToQuit=0)
        add('armed',100,holdUntilQuit=True,delayMs=None)
        add('hold-start',1000,**pending)
        for i in range(121):add('hold-sample',1000+i*1000,heldCalls=i+1,**observed)
        for i,kind in enumerate(('uiQuit-enter','applicationQuit-enter','wants-quit-enter')):
            add(kind,122000+i,**observed)
        observed['wantsToQuit']=1
        add('wants-quit-return',122003,accepted=int(count<=0),**observed)
        if count<=0:add('assets-quit-enter',122004)
        log=('[121100] Dedicated cleanup exceeded 120s; retaining native state, process restart required\n'
             '[122000] PENDING LOAD QUIT SMOKE BA_RESURRECTION_PENDING_LOAD_QUIT_V1: blocked=1 mapLoading=1 thread=456 originalModal=ModalConfirmVM (NOT manual UI input)\n'
             '[122000] QUIT SMOKE invoking original disconnected modal OnCancel (NOT manual UI input)\n')
        return rows,log

    def check(self,rows,log,**overrides):
        args=dict(game_exit=0,launcher_exit=0,forced_cleanup=False)
        args.update(overrides)
        return probe.validate_pending_quit(rows,log,123,**args)

    def test_pending_map_quit_is_not_engine_or_positive_counter_recovery(self):
        result=self.check(*self.fixture())
        self.assertTrue(result['passed'])
        self.assertEqual(result['asset_loading_count'],0)
        for key in ('positive_counter_recovery_proved','safe_cancellation_proved','hung_engine_recovery_proved'):
            self.assertFalse(result[key])

    def test_native_veto_is_an_observation_not_exit_acceptance(self):
        result=self.check(*self.fixture(1),game_exit=None,launcher_exit=None,forced_cleanup=True)
        self.assertTrue(result['admission_observed'])
        self.assertFalse(result['original_quit_accepted'])
        self.assertFalse(result['passed'])

    def test_forced_or_abnormal_exit_never_passes(self):
        for changes in (dict(forced_cleanup=True),dict(game_exit=1),dict(launcher_exit=None),dict(game_exit=False)):
            self.assertFalse(self.check(*self.fixture(),**changes)['passed'])

    def test_released_or_completed_load_rejected(self):
        for kind in ('hold-release','complete-enter','complete-return'):
            rows,log=self.fixture();rows[-1]['kind']=kind
            with self.assertRaisesRegex(ValueError,'released or completed'):self.check(rows,log)
        rows,log=self.fixture();rows[0].update(holdUntilQuit=False,delayMs=130000)
        with self.assertRaisesRegex(ValueError,'timer'):self.check(rows,log)

    def test_unowned_thread_world_and_early_cleanup_rejected(self):
        for changes in (dict(tid=789),dict(mapLoading=0),dict(world=True),dict(active=1),dict(pid=321)):
            rows,log=self.fixture();rows[50].update(changes)
            with self.assertRaises(ValueError):self.check(rows,log)
        rows,log=self.fixture();rows[50]['kind']='cleanup-enter'
        with self.assertRaisesRegex(ValueError,'cleanup preceded'):self.check(rows,log)

    def test_missing_counter_wrong_veto_and_missing_original_route_rejected(self):
        rows,log=self.fixture();del rows[50]['assetLoadingCount']
        with self.assertRaisesRegex(ValueError,'counter observation'):self.check(rows,log)
        rows,log=self.fixture();rows[-2]['assetLoadingCount']=1
        with self.assertRaisesRegex(ValueError,'veto observation'):self.check(rows,log)
        rows,log=self.fixture();rows[-5]['kind']='unrelated-Quit'
        with self.assertRaisesRegex(ValueError,'uiQuit-enter'):self.check(rows,log)

    def test_requires_real_deadline_and_explicit_diagnostic_dispatch(self):
        rows,log=self.fixture()
        for changed in ('',log.replace('121100','120999'),log.replace('blocked=1','blocked=0')):
            with self.assertRaises(ValueError):self.check(rows,changed)


if __name__=='__main__':unittest.main()
