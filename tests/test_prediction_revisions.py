"""Reanchor only speculative input guesses,at the next native owner boundary."""
import copy
import unittest

from client_patch.prediction_worker.prediction import Reconciler, PredictionInputError
from tests.test_native_prediction_reconciler import Sim, frame, move


class RevisionTests(unittest.TestCase):
    def advance(self, sim, reconciler, raw):
        chosen = reconciler.before_next_frame(raw)
        sim.process_frame(chosen,50)
        reconciler.after_native_frame(chosen)

    def setup_world(self, count=5):
        sim = Sim();r = Reconciler(sim)
        for number in range(count):
            self.advance(sim,r,frame(number,local=(move(1,30),) if number == 2 else ()))
        self.addCleanup(r.close)
        return sim,r

    def test_removal_and_reanchor_replay_to_fresh_control_without_duplicate(self):
        sim,r = self.setup_world()
        before = copy.deepcopy(sim.events)
        r.revise_unconfirmed({2:frame(2),4:frame(4,local=(move(1,30),))})
        self.assertEqual(sim.events,before)
        self.advance(sim,r,frame(5))
        control = Sim()
        for number in range(6):
            control.process_frame(frame(number,local=(move(1,30),) if number == 4 else ()),50)
        self.assertEqual(sim.state,control.state)
        self.assertEqual((r.metrics['restores'],r.metrics['revised_frames']), (1,2))
        for number in range(6):
            r.enqueue_authority(frame(number,local=(move(1,30),) if number == 4 else ()))
        self.advance(sim,r,frame(6))
        self.assertEqual(r.confirmed_frame,5)

    def test_invalid_revision_plan_is_atomic_and_known_authority_immutable(self):
        sim,r = self.setup_world()
        before = copy.deepcopy(sim.events),r.metrics
        with self.assertRaises(PredictionInputError):r.revise_unconfirmed({2:frame(2),99:frame(99)})
        self.assertEqual((sim.events,r.metrics),before)
        r.enqueue_authority(frame(0));r.enqueue_authority(frame(1))
        before = copy.deepcopy(sim.events),r.metrics
        with self.assertRaises(PredictionInputError):r.revise_unconfirmed({1:frame(1,local=(move(1,99),))})
        self.assertEqual((sim.events,r.metrics),before)

    def test_authority_arriving_after_revision_always_wins(self):
        sim,r = self.setup_world(count=2)
        r.revise_unconfirmed({0:frame(0,local=(move(1,99),))})
        r.enqueue_authority(frame(0));r.enqueue_authority(frame(1))
        self.advance(sim,r,frame(2))
        self.assertEqual(r.metrics['restores'],0)
        self.assertEqual(r.confirmed_frame,1)
        self.assertEqual(r.metrics['revised_guesses'],0)

    def test_complete_replacement_plan_can_cancel_prior_staged_revision(self):
        sim,r = self.setup_world(count=2)
        r.revise_unconfirmed({0:frame(0,local=(move(1,99),))})
        r.revise_unconfirmed({})
        self.advance(sim,r,frame(2))
        self.assertEqual(r.metrics['restores'],0)
        self.assertEqual(r.metrics['revised_guesses'],0)


if __name__ == '__main__':unittest.main()
