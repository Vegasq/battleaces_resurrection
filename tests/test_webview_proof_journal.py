import json,os,shutil,unittest,uuid
from pathlib import Path
from tools.webview_proof_journal import ROOT,latest

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.folder=(ROOT/'local'/('proofjournal149_'+uuid.uuid4().hex)).resolve();self.assertTrue(self.folder.is_relative_to(ROOT/'local'))
        self.profile=self.folder/'.battleaces-resurrection/profiles/nativestest_owned';self.profile.mkdir(parents=True);self.pid=1234
    def tearDown(self):
        self.assertTrue(self.folder.resolve().is_relative_to(ROOT/'local'));shutil.rmtree(self.folder)
    def publish(self,n,**changes):
        data=dict(schema=1,pid=self.pid,publication=n,phase='waiting_initialization');data.update(changes)
        temp=self.profile/f'temporary-{n}.tmp';temp.write_text(json.dumps(data));path=self.profile/f'webview-proof-{self.pid}-{n}.json';os.replace(temp,path);return path
    def test_pinned_old_generation_does_not_block_new_complete_publication(self):
        old=self.publish(1)
        with old.open('rb') as held:
            new=self.publish(2,phase='failed');path,data=latest(self.profile,self.pid)
            self.assertEqual(path,new);self.assertEqual(data['publication'],2);self.assertEqual(json.load(held)['publication'],1)
    def test_numeric_latest_not_lexical_and_incomplete_temp_ignored(self):
        self.publish(2);last=self.publish(10);(self.profile/'temporary-11.tmp').write_text('{')
        self.assertEqual(latest(self.profile,self.pid)[0],last)
    def test_missing_foreign_pid_and_unowned_profile(self):
        self.assertIsNone(latest(self.profile,self.pid));self.publish(1,pid=99)
        with self.assertRaises(ValueError):latest(self.profile,self.pid)
        for profile,pid in ((ROOT,1234),(self.profile,True),(self.profile,0)):
            with self.assertRaises(ValueError):latest(profile,pid)
    def test_invalid_latest_is_not_silently_replaced_by_older_valid_data(self):
        self.publish(1);self.publish(2,publication=1)
        with self.assertRaises(ValueError):latest(self.profile,self.pid)
        p=self.profile/f'webview-proof-{self.pid}-2.json';p.write_text('{')
        with self.assertRaises(json.JSONDecodeError):latest(self.profile,self.pid)
    def test_malformed_name_and_wrong_scalar_types_refused(self):
        p=self.publish(1,schema=True)
        with self.assertRaises(ValueError):latest(self.profile,self.pid)
        p.unlink();(self.profile/f'webview-proof-{self.pid}-01.json').write_text('{}')
        with self.assertRaises(ValueError):latest(self.profile,self.pid)
    def test_publication_and_byte_budgets_enforced(self):
        p=self.publish(1);p.write_bytes(b'x'*65537)
        with self.assertRaises(ValueError):latest(self.profile,self.pid)
        for n in range(2,258):(self.profile/f'webview-proof-{self.pid}-{n}.json').write_text('{}')
        with self.assertRaises(ValueError):latest(self.profile,self.pid)

if __name__=='__main__':unittest.main()
