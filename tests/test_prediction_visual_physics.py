"""Authored production batch evidence, never engine/native acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_prediction_visual_correction import authored
from tests import test_prediction_visual_input as input_tests
from tools import prediction_visual_physics as evidence


def fixture():
    records=[];poses=[];bindings=[]
    for world in (1,2):
        data=authored(world);bindings.append(data['binding']);poses.extend(data['records'])
        for p in data['records']:
            if p['event']!='visual_pose'or not p['wrote']:continue
            t=p['sampled_us'];records.append(dict(schema=1,event='batch',world=world,match=p['match'],frame=p['frame'],
                revision=1,policy_us=t,prepare_started_us=t+1,prepared_us=t+5,entered_us=t+10,returned_us=t+20,
                thread=1000,owner_thread=1000,writes=1,restorations=int(p['displayed']==p['raw']and p['pulses']==0)))
    return records,poses,bindings


def log(records):return '\n'.join(evidence.PREFIX+json.dumps(r)for r in records)


class VisualPhysicsProtocol(unittest.TestCase):
    def test_each_observed_changed_write_has_one_completed_sync_and_restoration(self):
        records,poses,bindings=fixture();result=evidence.evaluate(evidence.rows(log(records)),poses,bindings)
        self.assertTrue(result['passed']);self.assertFalse(result['diagnostic_intervention'])
        for world in result['worlds']:
            self.assertEqual(world['calls'],world['observed_changed_writes']);self.assertEqual(world['observed_restorations'],1)
            self.assertEqual(world['maximum_sync_us'],10);self.assertEqual(world['maximum_prepare_us'],4)
            self.assertEqual(world['maximum_prepare_through_sync_us'],19)

    def test_missing_duplicate_wrong_frame_and_restoration_are_refused(self):
        records,poses,bindings=fixture()
        cases=[records[1:],records+[records[0]],deepcopy(records),deepcopy(records)]
        cases[2][0]['frame']+=1
        for r in cases[3]:r['restorations']=0
        for bad in cases:
            with self.subTest(case=len(bad)),self.assertRaises(AssertionError):evidence.evaluate(evidence.rows(log(bad)),poses,bindings)

    def test_original_owner_clock_count_schema_and_no_intervention(self):
        records,_,_=fixture()
        for key,value in (('owner_thread',999),('writes',0),('writes',True),('restorations',2),('prepared_us',0),('frame',399)):
            bad=deepcopy(records);bad[0][key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):evidence.rows(log(bad))
        with self.assertRaisesRegex(AssertionError,'duplicate'):evidence.rows(log(records).replace('"schema": 1','"schema": 1, "schema": 1',1))
        with self.assertRaisesRegex(AssertionError,'intervention'):evidence.rows(log(records)+'\nVISUAL SYNC {}')

    def test_completed_frontend_join_must_follow_sync_return(self):
        records,poses,bindings=fixture();r=records[0]
        join=dict(world=r['world'],policy_us=r['policy_us'],joined_us=r['returned_us'])
        self.assertTrue(evidence.evaluate(records,poses,bindings,completed_joins=[join])['passed'])
        join['revision']=r['revision']+1
        with self.assertRaisesRegex(AssertionError,'revision differ'):evidence.evaluate(records,poses,bindings,completed_joins=[join])
        join.pop('revision')
        join['joined_us']-=1
        with self.assertRaisesRegex(AssertionError,'frontend completed'):evidence.evaluate(records,poses,bindings,completed_joins=[join])


class VisualPhysicsFiles(unittest.TestCase):
    def test_explicit_post_only_revision_requires_exact_two_path_inventory_delta(self):
        from tools import verify_prediction_multiplayer as controller
        names=evidence.OFFLINE_PATHS
        prepared={names[0]:'0'*64,names[1]:'1'*64,'client_patch/prediction_worker/native.py':'2'*64}
        current=dict(prepared);current[names[0]]=evidence.motion.sha(evidence.__file__);current[names[1]]=evidence.motion.sha(__file__)
        revision=dict(schema=1,scope='offline_checker_lexical_parser_fix',prepared_source_sha256={n:prepared[n]for n in names},
            current_source_sha256={n:current[n]for n in names})
        plan=dict(source_sha256=prepared)
        with self.assertRaisesRegex(AssertionError,'checker differs'):evidence._analysis_revision(plan,None)
        with patch.object(controller,'source_hashes',return_value=current):
            self.assertEqual(evidence._analysis_revision(plan,revision)['prepared_checker_sha256'],'0'*64)
            for key in ('prepared_source_sha256','current_source_sha256'):
                bad=deepcopy(revision);bad[key].pop(names[1])
                with self.assertRaises(AssertionError):evidence._analysis_revision(plan,bad)
            current['client_patch/prediction_worker/native.py']='3'*64
            with self.assertRaisesRegex(AssertionError,'unchanged full runtime'):evidence._analysis_revision(plan,revision)

    def test_closed_production_summary_pins_sources_and_rejects_early_publication_or_intervention(self):
        records,poses,bindings=fixture();batch={(r['world'],r['policy_us']):r for r in records}
        lines=[]
        for p in poses:
            if p['event']=='visual_pose' and (p['world'],p['sampled_us'])in batch:
                lines.append(evidence.PREFIX+json.dumps(batch[(p['world'],p['sampled_us'])]))
            lines.append(evidence.visual.PREFIX+json.dumps(p))
        original_queries,_,_=input_tests.fixture()
        # Genuine INPUT subrecords are valid in the complete log but produce no
        # visual_pose in a one-line parser call (Actual94 line3029 regression).
        lines.extend(evidence.queries.PREFIX+json.dumps(q)for q in original_queries)
        with tempfile.TemporaryDirectory()as directory:
            run=Path(directory)/'run';run.mkdir();player=Path(directory)/'UnityPlayer.dll';player.write_bytes(b'authored module')
            (run/'native-0.log').write_text('\n'.join(lines));(run/'native-1.log').write_text('')
            (run/'verification.json').write_text('{"passed":true}')
            source={}
            for name in evidence.PRODUCERS:
                path=run.parent/'source-at-prepare'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('authored '+name)
                source[name]=evidence.motion.sha(path)
            for m in (evidence,evidence.visual,evidence.queries,evidence.acquire,evidence.intervention,evidence.motion):
                source['tools/'+Path(m.__file__).name]=evidence.motion.sha(m.__file__)
            plan=dict(visual_correction=True,visual_input=True,visual_click_acquire=True,
                files=dict(unityplayer=dict(path=str(player),sha256=evidence.intervention.UNITYPLAYER_SHA256)),source_sha256=source)
            report=dict(passed=True,visual_input_witness_passed=True,visual_input=dict(worlds=[dict(records=[q for q in original_queries if q['world']==b['world']])for b in bindings],
                input_sha256={str(run/name):evidence.motion.sha(run/name)for name in ('native-0.log','native-1.log')}),
                visual_correction=dict(worlds=[dict(binding=b)for b in bindings]),visual_click_acquire=dict(worlds=[dict(records=[])for _ in bindings]))
            original=evidence.motion.sha
            def sha(path):return evidence.intervention.UNITYPLAYER_SHA256 if Path(path)==player else original(path)
            with patch.object(evidence.visual,'parent_gate'),patch.object(evidence.queries,'gate',return_value=True),\
                 patch.object(evidence.acquire,'gate',return_value=True),patch.object(evidence.motion,'sha',side_effect=sha):
                self.assertTrue(evidence.analyze(plan,report,run)['passed'])
                bad=deepcopy(plan);bad['source_sha256'][evidence.PRODUCERS[0]]='f'*64
                with self.assertRaisesRegex(AssertionError,'source differs'):evidence.analyze(bad,report,run)
                with self.assertRaisesRegex(AssertionError,'diagnostic flag'):evidence.analyze(dict(plan,visual_sync_probe=True),report,run)
                for flag in ('visual_input','visual_click_acquire'):
                    for value in (False,None):
                        with self.subTest(flag=flag,value=value),self.assertRaisesRegex(AssertionError,'candidate required'):
                            evidence.analyze(dict(plan,**{flag:value}),report,run)
                first=next(i for i,line in enumerate(lines)if line.startswith(evidence.PREFIX))
                wrong=list(lines);wrong[first],wrong[first+1]=wrong[first+1],wrong[first]
                (run/'native-0.log').write_text('\n'.join(wrong));report['visual_input']['input_sha256'][str(run/'native-0.log')]=original(run/'native-0.log')
                with self.assertRaisesRegex(AssertionError,'published before'):evidence.analyze(plan,report,run)


if __name__=='__main__':unittest.main()
