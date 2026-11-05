"""Authored failures for original frame-driven emote lifetime evidence."""
import unittest
from tools.verify_match_emotes import validate_cases,validate_lifecycle,COMPLETE

def evidence():
    rows=[]
    for index,item in enumerate([6,7,8,9]):
        start=100+index*150;end=start+60
        for phase,frame in [('dispatch-return',start),('frame',start+2),('frame',start+10),('frame',end),('frame',end+1),('expired',end+5)]:
            active=frame<=end
            rows.append(dict(index=index,item=item,army=0,frame=frame,tick=1000+frame*50,start=start,end=end,rate=20,
                state_start=start if active else 0,state_end=end if active else 0,asset_present=active,asset_matches=active,
                model_item=item,portrait=66,view_id=123,vm_initialized=True,visible=active,hidden=phase=='expired',
                solo_active=active,playing=active,graph_ready=True,seconds=(frame-start)/20,phase=phase))
    return dict(schema=1,loadout_unchanged=True,physical_input_tested=False,visual_audio_verified=False,observations=rows)

class MatchEmoteTests(unittest.TestCase):
    def test_complete(self):validate_cases(evidence())
    def test_missing_slot(self):
        p=evidence();p['observations']=[r for r in p['observations'] if r['index']!=2]
        with self.assertRaisesRegex(AssertionError,'four ordered'):validate_cases(p)
    def test_wrong_equipped_item(self):
        p=evidence();p['observations'][0]['model_item']=99
        with self.assertRaisesRegex(AssertionError,'equipped model'):validate_cases(p)
    def test_wrong_duration(self):
        p=evidence();p['observations'][0]['end']+=1
        with self.assertRaisesRegex(AssertionError,'three-second'):validate_cases(p)
    def test_expired_too_early(self):
        p=evidence();p['observations'][3].update(asset_present=False,state_start=0,state_end=0)
        with self.assertRaisesRegex(AssertionError,'early expiry'):validate_cases(p)
    def test_expired_too_late(self):
        p=evidence();p['observations'][4].update(asset_present=True,asset_matches=True,state_start=100,state_end=160)
        with self.assertRaisesRegex(AssertionError,'ownership'):validate_cases(p)
    def test_still_visible(self):
        p=evidence();p['observations'][5]['hidden']=False
        with self.assertRaisesRegex(AssertionError,'hide did not settle'):validate_cases(p)
    def test_hidden_before_expiry(self):
        p=evidence();p['observations'][3]['hidden']=True
        with self.assertRaisesRegex(AssertionError,'ownership differs'):validate_cases(p)
    def test_hidden_but_still_playing(self):
        p=evidence();p['observations'][5]['playing']=True
        with self.assertRaisesRegex(AssertionError,'hide did not settle'):validate_cases(p)
    def test_no_animation_progress(self):
        p=evidence()
        for r in p['observations']:r['seconds']=0
        with self.assertRaisesRegex(AssertionError,'did not advance'):validate_cases(p)
    def test_gap_at_expiry(self):
        p=evidence();p['observations']=[r for r in p['observations'] if r['frame']!=r['end']]
        with self.assertRaisesRegex(AssertionError,'boundary observation gap'):validate_cases(p)
    def test_show_transition_can_play(self):
        p=evidence()
        for r in p['observations']:r['visible']=r['phase']=='frame' and r['frame']==r['end']+1
        validate_cases(p)
    def test_inactive_animation_not_accepted(self):
        p=evidence()
        for r in p['observations']:r['solo_active']=False
        with self.assertRaisesRegex(AssertionError,'did not advance'):validate_cases(p)
    def test_lifecycle(self):
        native=dict(pid=42,mode='confirm',natural_exit=True,forced_cleanup=False,exit_code=0,owned_process_reaped=True,
            shared_settings_unchanged=True,source_files_unchanged=True,
            trace=[dict(pid=42,thread=1,tick=i,event=e) for i,e in enumerate(['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return'])])
        text='\n'.join(['PRACTICE SMOKE original EditDeck mode4 callback:',COMPLETE,'PRACTICE SMOKE native ConcedeGame (automated)',
            'Practice native EndOfGameResponse delivered;','PRACTICE SMOKE native Continue (automated)',
            'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1',
            'NATIVE QUIT owned menu verified:','NATIVE QUIT original confirmation dispatch:'])
        validate_lifecycle(native,text,42)
        native['forced_cleanup']=True
        with self.assertRaisesRegex(AssertionError,'Quit ownership'):validate_lifecycle(native,text,42)
        native['forced_cleanup']=False
        with self.assertRaisesRegex(AssertionError,'sequence differs'):validate_lifecycle(native,text.replace('native Continue','skipped Continue'),42)

if __name__=='__main__':unittest.main()
