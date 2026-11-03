"""Synthetic controls for a proposed recovery model, not production tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reach_recovery_model import Model, Plan, Refused


class RecoveryModelTests(unittest.TestCase):
    def setUp(self):
        self.plan = Plan("operation-1", "actor-1", "binding-1", "recursive")
        self.m = Model()

    def begin(self):
        self.m.begin(self.plan, authorized=True)

    def test_authority_and_bound_identity_precede_effects(self):
        with self.assertRaises(Refused):
            self.m.begin(self.plan, authorized=False)
        with self.assertRaises(Refused):
            self.m.commit_standing(self.plan)
        self.begin()
        for changed in (Plan("operation-1", "actor-2", "binding-1", "recursive"),
                        Plan("operation-1", "actor-1", "binding-2", "recursive")):
            with self.subTest(changed=changed), self.assertRaises(Refused):
                self.m.begin(changed, authorized=True)
        self.assertEqual(self.m.current_standing, "initial")

    def test_no_terminal_from_standing_alone_or_unrecorded_live(self):
        self.begin()
        self.m.commit_standing(self.plan)
        with self.assertRaises(Refused):
            self.m.publish(self.plan)
        self.m.apply_live(self.plan)
        with self.assertRaises(Refused):
            self.m.publish(self.plan)
        self.assertEqual(self.m.observed_outcome(self.plan), "standing-committed-live-unknown")

    def test_restart_cannot_manufacture_missing_live_evidence(self):
        self.begin()
        self.m.commit_standing(self.plan)
        self.m.apply_live(self.plan)
        self.m.restart()
        with self.assertRaises(Refused):
            self.m.record_live(self.plan)
        with self.assertRaises(Refused):
            self.m.apply_live(self.plan)
        with self.assertRaises(Refused):
            self.m.publish(self.plan)
        self.assertEqual(self.m.observed_outcome(self.plan), "standing-committed-live-unknown")

    def test_lost_terminal_reply_is_reconciled_without_duplicate(self):
        self.begin()
        self.m.commit_standing(self.plan)
        self.m.apply_live(self.plan)
        self.m.record_live(self.plan)
        with self.assertRaises(OSError):
            self.m.publish(self.plan, lose_reply=True)
        self.m.restart()
        self.m.publish(self.plan)
        self.assertEqual(len(self.m.terminal_rows), 1)
        self.assertEqual(self.m.observed_outcome(self.plan), "witnessed-historical-completion")
        self.assertEqual(self.m.current_live, "unknown-after-restart")

    def test_retry_does_not_overwrite_a_later_standing_change(self):
        self.begin()
        self.m.commit_standing(self.plan)
        self.m.later_standing_change("later-authorized-value")
        self.m.commit_standing(self.plan)
        self.assertEqual(self.m.current_standing, "later-authorized-value")
        self.assertEqual(self.m.observed_outcome(self.plan), "standing-committed-live-unknown")
        with self.assertRaises(Refused):
            self.m.apply_live(self.plan)

    def test_standing_aba_is_not_an_unchanged_observation(self):
        self.begin()
        self.m.commit_standing(self.plan)
        self.m.later_standing_change("different")
        self.m.later_standing_change(self.plan.desired)
        with self.assertRaises(Refused):
            self.m.apply_live(self.plan)

    def test_restart_before_standing_has_unknown_outcome(self):
        self.begin()
        self.m.restart()
        self.assertEqual(self.m.observed_outcome(self.plan), "outcome-unknown")
        with self.assertRaises(Refused):
            self.m.commit_standing(self.plan)
        with self.assertRaises(Refused):
            self.m.publish(self.plan)

    def test_recorded_prior_epoch_is_historical_not_current_authority(self):
        self.begin()
        self.m.commit_standing(self.plan)
        self.m.apply_live(self.plan)
        self.m.record_live(self.plan)
        self.m.restart()
        self.m.publish(self.plan)
        self.assertEqual(self.m.terminal_rows[self.plan.operation][1], 0)
        self.assertEqual(self.m.current_live, "unknown-after-restart")
        with self.assertRaises(Refused):
            self.m.apply_live(self.plan)

    def test_crash_at_each_stage_preserves_only_evidenced_history(self):
        for cut in range(5):
            with self.subTest(cut=cut):
                model = Model()
                model.begin(self.plan, authorized=True)
                steps = (model.commit_standing, model.apply_live,
                         model.record_live, model.publish)
                for step in steps[:cut]:
                    step(self.plan)
                model.restart()
                if cut < 3:
                    with self.assertRaises(Refused):
                        model.publish(self.plan)
                    self.assertNotEqual(model.observed_outcome(self.plan),
                                        "witnessed-historical-completion")
                else:
                    model.publish(self.plan)
                    self.assertEqual(model.observed_outcome(self.plan),
                                     "witnessed-historical-completion")
                    self.assertEqual(model.terminal_rows[self.plan.operation][1], 0)
                self.assertEqual(model.current_live, "unknown-after-restart")


if __name__ == "__main__":
    unittest.main()
