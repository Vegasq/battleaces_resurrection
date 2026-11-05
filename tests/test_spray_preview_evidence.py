"""Reject incomplete or stale selected-resource evidence; these are authored controls."""
import copy
import unittest
from tools.verify_spray_previews import validate_cases


def fixture():
    items=[54,10,71,151,152,203]
    contract=dict(passed=True,runtime_executed=False,slot=dict(id=8,default_item=54),cases=[
        dict(item=i,assets={'AssetReferenceSprite':{'name':f'Sprite{i}'},'AssetReferenceMaterial':{'name':f'Material{i}'}}) for i in items])
    rows=[]
    for index,item in enumerate(items+[54]):
        for phase in ['loaded','settled']:
            rows.append(dict(phase=phase,index=index,item=item,model_item=item,cosmetic_type=4,tick=100+len(rows),vm_id=1,graphic_id=2,
                sprite=f'Sprite{item}',sprite_id=item,material=f'Material{item}',material_id=1000+item,
                actual_material=f'Material{item}',actual_material_id=1000+item,material_binding_matches=True,
                vm_active=True,vm_initialized=True,graphic_active=True,image_present=True,image_enabled=True,override_present=False))
    back=dict(rows[-1],phase='back',tick=115,model_item=0,vm_active=False,vm_initialized=False,graphic_active=False)
    rows.append(back)
    proof=dict(schema=1,visual_audio_verified=False,physical_input_tested=False,loadout_unchanged=True,observations=rows)
    return proof,copy.deepcopy(back),contract


class SprayPreviewEvidenceTests(unittest.TestCase):
    def test_complete_authored_sequence(self):
        validate_cases(*fixture())

    def test_missing_selection(self):
        p,r,c=fixture();del p['observations'][4:6]
        with self.assertRaises(AssertionError):validate_cases(p,r,c)

    def test_previous_material_still_on_graphic(self):
        p,r,c=fixture();p['observations'][2]['actual_material_id']=1054
        with self.assertRaisesRegex(AssertionError,'graphic material'):validate_cases(p,r,c)

    def test_wrong_sprite_subobject(self):
        p,r,c=fixture();p['observations'][3]['sprite']='Texture2D_or_wrong_slice'
        with self.assertRaisesRegex(AssertionError,'sprite subobject'):validate_cases(p,r,c)

    def test_changed_owner(self):
        p,r,c=fixture();p['observations'][3]['vm_id']=99
        with self.assertRaisesRegex(AssertionError,'ownership changed'):validate_cases(p,r,c)

    def test_bound_image_disabled(self):
        p,r,c=fixture();p['observations'][3]['image_enabled']=False
        with self.assertRaisesRegex(AssertionError,'Image binding'):validate_cases(p,r,c)

    def test_return_has_different_resource_identity(self):
        p,r,c=fixture()
        for v in p['observations'][12:14]:v.update(material_id=9999,actual_material_id=9999)
        with self.assertRaisesRegex(AssertionError,'switch/return'):validate_cases(p,r,c)

    def test_back_does_not_disable_graphic(self):
        p,r,c=fixture();r['graphic_active']=True;p['observations'][-1]=dict(r)
        with self.assertRaisesRegex(AssertionError,'active preview'):validate_cases(p,r,c)

    def test_scope_must_not_claim_visual_acceptance(self):
        p,r,c=fixture();p['visual_audio_verified']=True
        with self.assertRaisesRegex(AssertionError,'scope'):validate_cases(p,r,c)

    def test_equipped_loadout_changed(self):
        p,r,c=fixture();p['loadout_unchanged']=False
        with self.assertRaisesRegex(AssertionError,'loadout'):validate_cases(p,r,c)


if __name__=='__main__':unittest.main()
