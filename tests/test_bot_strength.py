"""Authored counterexamples for native strength-effect assessment, no game data."""
import copy,unittest
from tools import verify_bot_strength as s

def fixture():
    def resources(primary,secondary):
        return dict(primary=primary,secondary=secondary,primary_gathered=primary,secondary_gathered=secondary,
                    current_supply=0,max_supply=200,primary_lost=0,secondary_lost=0)
    levels={}
    for name,ratio in (('easy',s.Q32//2),('normal',s.Q32),('hard',s.Q32*3//2)):
        resource_ratio=ratio if name=='easy' else s.Q32
        samples=[dict(frame=200,resources={str(a):resources(400,400) for a in (0,1)}),
                 dict(frame=600,resources={'0':resources(1400,600),'1':resources(400+(1000*resource_ratio>>32),400+(200*resource_ratio>>32))})]
        hits={}
        for slot in (0,1):
            health=(1000*ratio>>32) if slot else 1000
            before=dict(id=100+slot,army=slot,type=7,max_health=health,current_damage=0,position=[slot,0,0])
            damage=(100*ratio>>32) if not slot else 100
            hits[str(slot)]=dict(frame=20,before=before,after=dict(before,current_damage=damage),
                attacker=dict(id=101-slot,army=1-slot,type=7,position=[1-slot,0,0]),live_units=[1,1],delta=damage)
        levels[name]=dict(strength=[resource_ratio,ratio,ratio],income=dict(samples=samples,closed=True),combat=dict(hits=hits,build_count=2,closed=True))
    levels['normal-repeat']=copy.deepcopy(levels['normal'])
    return levels

class BotStrengthTests(unittest.TestCase):
    def test_complete_authored_controls_pass(self):self.assertTrue(all(s.assess(fixture()).values()))

    def test_ineffective_income_or_human_contamination_cannot_pass(self):
        for level,army in (('easy','1'),('easy','0')):
            sample=fixture();row=sample[level]['income']['samples'][-1]['resources'][army]
            row['primary']=row['primary_gathered']=1401
            with self.subTest(army=army):self.assertFalse(all(s.assess(sample).values()))

    def test_integer_income_endpoint_quantization_is_bounded_to_one_unit(self):
        sample=fixture();row=sample['easy']['income']['samples'][-1]['resources']['1']
        row['primary']+=1;row['primary_gathered']+=1
        self.assertTrue(all(s.assess(sample).values()))
        row['primary']+=1;row['primary_gathered']+=1
        self.assertFalse(all(s.assess(sample).values()))

    def test_missing_hit_wrong_owner_or_multiple_attackers_refuse(self):
        for change in ('missing','owner','multiple'):
            sample=fixture();hit=sample['hard']['combat']['hits']['0']
            if change=='missing':sample['hard']['combat']['hits'].pop('1')
            elif change=='owner':hit['attacker']['army']=0
            else:hit['live_units']=[1,2]
            with self.subTest(change=change),self.assertRaises(ValueError):s.assess(sample)

    def test_changed_damage_health_geometry_or_repeat_fails(self):
        for change in ('damage','health','geometry','repeat'):
            sample=fixture();hit=sample['hard']['combat']['hits']['0']
            if change=='damage':hit['delta']-=1;hit['after']['current_damage']-=1
            elif change=='health':hit['before']['max_health']+=1;hit['after']['max_health']+=1
            elif change=='geometry':hit['frame']+=1
            else:sample['normal-repeat']['combat']['build_count']=1
            with self.subTest(change=change):self.assertFalse(all(s.assess(sample).values()))

    def test_unclosed_world_or_spending_in_income_control_is_not_accepted(self):
        sample=fixture();sample['easy']['combat']['closed']=False
        self.assertFalse(all(s.assess(sample).values()))
        sample=fixture();sample['hard']['income']['samples'][0]['resources']['1']['current_supply']=1
        with self.assertRaises(ValueError):s.assess(sample)

    def test_output_cannot_write_source_or_package_asset_subtrees(self):
        package=s.ROOT/'local/strength162-fixture-package';assets=s.ROOT/'local/strength162-fixture-assets'
        for output in (s.ROOT/'server/strength162',package/'child',assets/'child'):
            with self.subTest(output=output),self.assertRaises(ValueError):s.run(package,assets,output)
            self.assertFalse(output.exists())

if __name__=='__main__':unittest.main()
