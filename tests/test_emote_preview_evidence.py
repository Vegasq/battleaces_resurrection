"""Authored controls for acceptance of complete, correctly bound preview traces."""
import copy
import unittest
from tools.verify_emote_previews import validate_cases

def evidence():
    cases=[dict(item=100+i,animation_name='Clip'+str(i%9),emotion=i%4,typewriter=bool(i%2),text_effects=['Effect'+str(i%3)],
                text={'m_TableEntryReference':{'m_KeyId':1000+i}}) for i in range(46)]
    contract=dict(passed=True,runtime_executed=False,cases=cases,default_portrait=66,
                  portrait_cases=[dict(item=66,materials=[dict(emotion=e,path='Material'+str(e)+'.mat') for e in range(4)])])
    rows=[]
    for index,c in enumerate(cases+[cases[0]]):
        for sample,phase in enumerate(['loaded','play-return','progress','progress']):
            rows.append(dict(index=index,item=c['item'],model_item=c['item'],portrait=66,animation=c['animation_name'],
                material='Material'+str(c['emotion']),clip_binding_matches=True,material_binding_matches=True,
                dialog_matches_definition=True,vm_initialized=True,vm_active=True,solo_active=True,
                text_key=c['text']['m_TableEntryReference']['m_KeyId'],effects=c['text_effects'],typewriter=c['typewriter'],
                localized_text='Text'+str(c['item']),animator_text=('<noparse></noparse>' if c['typewriter'] else '')+'Text'+str(c['item']),
                animation_id=900+index%9,actual_animation_id=900+index%9,actual_animation=c['animation_name'],solo_id=800,phase=phase,
                tick=1000+index*1000+sample*100,seconds=sample/10,playing=True,graph_ready=True,pending_show=False))
    back=dict(rows[-1],phase='back',tick=50000,playing=False,vm_active=False,vm_initialized=False,solo_active=False)
    rows.append(back)
    return dict(schema=1,visual_audio_verified=False,physical_input_tested=False,loadout_unchanged=True,observations=rows),copy.deepcopy(back),contract

class EmoteEvidenceTests(unittest.TestCase):
    def test_complete_sequence(self):
        validate_cases(*evidence())
    def test_missing_emote(self):
        proof,back,contract=evidence();proof['observations']=[r for r in proof['observations'] if r['index']!=12]
        with self.assertRaisesRegex(AssertionError,'all46'):validate_cases(proof,back,contract)
    def test_stale_animation(self):
        proof,back,contract=evidence();proof['observations'][4]['animation']='Clip0'
        with self.assertRaisesRegex(AssertionError,'component binding'):validate_cases(proof,back,contract)
    def test_wrong_face_material(self):
        proof,back,contract=evidence();proof['observations'][0]['material']='Material3'
        with self.assertRaisesRegex(AssertionError,'component binding'):validate_cases(proof,back,contract)
    def test_loaded_text_not_bound(self):
        proof,back,contract=evidence();proof['observations'][0]['animator_text']='Previous emote'
        with self.assertRaisesRegex(AssertionError,'reach animator'):validate_cases(proof,back,contract)
    def test_typewriter_prefix_required(self):
        proof,back,contract=evidence();proof['observations'][4]['animator_text']=proof['observations'][4]['localized_text']
        with self.assertRaisesRegex(AssertionError,'reach animator'):validate_cases(proof,back,contract)
    def test_authored_tags_preserved(self):
        proof,back,contract=evidence();row=proof['observations'][4]
        row['localized_text']='<waitfor>Hmmmm.';row['animator_text']='<noparse></noparse><waitfor>Hmmmm.'
        validate_cases(proof,back,contract)
        row['animator_text']='<noparse></noparse>Hmmmm.'
        with self.assertRaisesRegex(AssertionError,'reach animator'):validate_cases(proof,back,contract)
    def test_actual_clip_identity_required(self):
        proof,back,contract=evidence();proof['observations'][4]['actual_animation_id']=123
        with self.assertRaisesRegex(AssertionError,'identity differs'):validate_cases(proof,back,contract)
    def test_original_clip_curve(self):
        proof,back,contract=evidence();contract['cases'][1]['animation_name']='Emote_Special'
        curve=dict(source_clip='Emote_Special',target_clip={'m_Name':'Emote_Mad_Rare'},field='_Clip',field_crc32=1345833794,
            binding=dict(attribute=1345833794,path=0,isPPtrCurve=1,typeID=114),
            script=dict(m_ClassName='SoloAnimation',m_Namespace='Animancer'),all_clip_pptr_counts={'Emote_Special':1,'Other':0})
        for row in proof['observations'][4:8]:
            row.update(animation='Emote_Special',actual_animation='Emote_Mad_Rare',actual_animation_id=456,clip_binding_matches=False)
        with self.assertRaisesRegex(AssertionError,'identity differs'):validate_cases(proof,back,contract)
        validate_cases(proof,back,contract,curve)
        proof['observations'][4]['actual_animation']='Previous clip'
        with self.assertRaisesRegex(AssertionError,'curve target differs'):validate_cases(proof,back,contract,curve)
    def test_unrelated_curve_rejected(self):
        proof,back,contract=evidence()
        curve=dict(source_clip='Other',target_clip={'m_Name':'Emote_Mad_Rare'},binding={},script={})
        with self.assertRaisesRegex(AssertionError,'curve contract differs'):validate_cases(proof,back,contract,curve)
    def test_playing_without_time_progress(self):
        proof,back,contract=evidence()
        for row in proof['observations'][:4]:row['seconds']=0
        with self.assertRaisesRegex(AssertionError,'did not advance'):validate_cases(proof,back,contract)
    def test_hidden_but_playing(self):
        proof,back,contract=evidence();proof['observations'][-1]['playing']=True;back['playing']=True
        with self.assertRaisesRegex(AssertionError,'active playback'):validate_cases(proof,back,contract)

if __name__=='__main__':unittest.main()
