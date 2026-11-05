import copy
import unittest

from tools.graphical_soak_evidence import ROLES,LIMITS,assess,idle_round,assess_cadence


class GraphicalSoakEvidenceTests(unittest.TestCase):
    def cadence_fixture(self):
        matches=[f'{index:032x}' for index in range(21)]
        events=[dict(event='frame_queued',match=match,frame=frame,
                     perf_counter_ns=1_000_000_000+index*100_000_000_000+frame*50_000_000,worker_ms=3.)
                for index,match in enumerate(matches) for frame in range(1220)]
        return events,matches

    def test_raw_cadence_boundary_not_rounded_to_pass(self):
        events,matches=self.cadence_fixture()
        self.assertTrue(assess_cadence(events,matches)['passed'])
        duration=2*1219*1_000_000_000//39
        for frame,row in enumerate(events[:1220]):row['perf_counter_ns']=1_000_000_000+duration*frame//1219
        self.assertTrue(assess_cadence(events,matches)['passed'])
        events[1219]['perf_counter_ns']+=1
        result=assess_cadence(events,matches)
        self.assertFalse(result['passed'])
        self.assertEqual(round(result['matches'][matches[0]]['effective_hz'],3),19.5)
        self.assertFalse(result['matches'][matches[0]]['checks']['cadence'])

    def test_gap_boundary_kept_even_when_average_passes(self):
        events,matches=self.cadence_fixture()
        for row in events[100:1220]:row['perf_counter_ns']+=950_000_000
        self.assertTrue(assess_cadence(events,matches)['passed'])
        for row in events[100:1220]:row['perf_counter_ns']+=1
        checks=assess_cadence(events,matches)['matches'][matches[0]]['checks']
        self.assertTrue(checks['cadence']);self.assertFalse(checks['publication_gap'])

    def test_worker_budget_is_per_match(self):
        events,matches=self.cadence_fixture()
        for row in events[:12]:row['worker_ms']=50.001
        self.assertTrue(assess_cadence(events,matches)['passed'])
        events[12]['worker_ms']=50.001
        checks=assess_cadence(events,matches)['matches'][matches[0]]['checks']
        self.assertFalse(checks['worker_budget']);self.assertTrue(checks['cadence'])

    def test_missing_duplicate_foreign_or_invalid_cadence_refused(self):
        for mutate in (lambda rows:rows.pop(0),lambda rows:rows[1].update(frame=0),
                       lambda rows:rows[0].update(match='foreign'),
                       lambda rows:rows[1].update(perf_counter_ns=rows[0]['perf_counter_ns']),
                       lambda rows:rows[0].update(worker_ms=float('nan'))):
            events,matches=self.cadence_fixture();mutate(events)
            with self.assertRaises(AssertionError):assess_cadence(events,matches)
        events,matches=self.cadence_fixture()
        with self.assertRaises(AssertionError):assess_cadence(events,matches[:2])

    def fixture(self):
        rows=[]
        for n in range(1,22):
            processes={role:dict(pid=100+i,created_filetime=1000+i,private_bytes=100000000+n*1024,
                                working_set_bytes=1000000,handles=100,cpu_seconds=n)
                       for i,role in enumerate(ROLES)}
            rows.append(dict(round=n,processes=processes))
        return rows,[copy.deepcopy(rows[0])]

    def test_idle_measurements_and_intermediate_peak_are_separate(self):
        rows,trend=self.fixture()
        trend[0]['processes']['game0']['private_bytes']=900000000
        result=assess(rows,trend)
        self.assertTrue(result['passed'])
        self.assertEqual(result['processes']['game0']['peak']['private_bytes'],900000000)
        self.assertEqual(result['processes']['game0']['growth']['private_bytes'],18*1024)

    def test_every_process_growth_limit_is_enforced(self):
        for role in ROLES:
            for metric,limit in LIMITS[role].items():
                rows,trend=self.fixture()
                rows[-1]['processes'][role][metric]=rows[2]['processes'][role][metric]+limit+1
                with self.subTest(role=role,metric=metric):self.assertFalse(assess(rows,trend)['passed'])

    def test_missing_round_missing_measurement_and_pid_reuse_rejected(self):
        for mutate in (lambda rows:rows.pop(10),lambda rows:rows[-1]['processes'].pop('game1'),
                       lambda rows:rows[10]['processes']['game0'].update(created_filetime=9999),
                       lambda rows:rows[10]['processes']['server'].update(private_bytes=0)):
            rows,trend=self.fixture();mutate(rows)
            with self.assertRaises(AssertionError):assess(rows,trend)
        rows,_=self.fixture()
        with self.assertRaises(AssertionError):assess(rows,[])

    def test_idle_round_requires_contiguous_same_lobby_returns(self):
        marker=lambda n,lobby='a'*32:f'COMMUNITY SOAK idle: round={n} lobby={lobby} nativeIdle=1 BA_RESURRECTION_CUSTOM_SOAK_V1\n'
        self.assertEqual(idle_round(marker(1)+marker(2)),2)
        for log in (marker(2),marker(1)*2,marker(1)+marker(2,'b'*32)):
            with self.assertRaises(AssertionError):idle_round(log)
