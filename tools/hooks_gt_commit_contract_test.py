"""Executable DESIGN model for certification 3b; no production adapters or authority.

All identities, signatures, durability and persistence below are simulated inputs.
Passing this suite proves model consistency, NOT vault/SQLCipher/fsync correctness.
No runtime may import this file. See docs/HOOK_CERTIFICATION_COMMIT_CONTRACT.md.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
import unittest


@dataclass(frozen=True)
class Request:
    operation: str
    member: str
    candidate: str
    actor: str
    reason: str
    prior: str | None


@dataclass(frozen=True)
class Row:
    kind: str
    request: Request
    witness: str = "expected-witness"
    signature_valid: bool = True
    operator_authorized: bool = True


class Refused(Exception):
    pass


class Unknown(Exception):
    pass


class Model:
    """One member's reservation/selection with independent chain/vault persistence.

    Slot numbers stand in for exact signed (chain-id, position, hash) references.
    A stable witness is a fixture, not a key registry or universal trust threshold.
    """
    def __init__(self):
        self.disk = dict(generation=0, pending=None, selected=None, closed={})
        self.memory = deepcopy(self.disk)
        self.rows = []
        self.durable = 0
        self.usable = True

    def require(self, value):
        if not value:
            raise Refused()

    def save(self, value, expected_generation, fault=None):
        self.require(self.usable and self.disk["generation"] == expected_generation)
        value = deepcopy(value)
        value["generation"] = expected_generation + 1
        self.memory = value  # Deliberately model a setter mutating memory before save.
        if fault == "before_rename":
            self.usable = False
            raise Unknown()
        self.disk = deepcopy(value)
        if fault == "after_rename":
            self.usable = False
            raise Unknown()

    def restart(self):
        self.rows = self.rows[:self.durable]
        self.memory = deepcopy(self.disk)
        self.usable = True

    def selected_id(self):
        selected = self.disk["selected"]
        return selected[0].operation if selected else None

    def begin(self, request, *, authorized=True, candidate_matches=True,
              dependency_labels=(), expected_generation=None, fault=None):
        self.require(self.usable and authorized and candidate_matches and not dependency_labels)
        self.require(request.member == "member" and all((request.operation, request.candidate,
                                                       request.actor, request.reason)))
        old = self.disk["closed"].get(request.operation)
        if old:
            self.require(old[0] == request)
            return old[1]  # Historical result; NEVER reselect an older certification.
        if self.disk["pending"]:
            self.require(self.disk["pending"] == request)
            return "pending"  # Explicit resume still needs fresh authority below.
        self.require(request.prior == self.selected_id())
        value = deepcopy(self.disk)
        value["pending"] = request
        self.save(value, self.disk["generation"] if expected_generation is None
                  else expected_generation, fault)
        return "pending"

    def append(self, row):
        self.require(self.usable)
        self.rows.append(row)
        return len(self.rows) - 1

    def flush(self, fail=False):
        if fail:
            self.usable = False
            raise Unknown()
        self.durable = len(self.rows)

    def evidence(self, position, kind, request):
        self.require(type(position) is int and 0 <= position < self.durable)
        row = self.rows[position]
        self.require(row.kind == kind and row.request == request
                     and row.signature_valid and row.operator_authorized
                     and row.witness == "expected-witness")

    def select(self, position, *, authorized=True, candidate_matches=True,
               expected_generation=None, fault=None):
        self.require(self.usable and authorized and candidate_matches)
        request = self.disk["pending"]
        self.require(request is not None and request.prior == self.selected_id())
        self.evidence(position, "authorization", request)
        value = deepcopy(self.disk)
        value["selected"] = (request, position)
        self.save(value, self.disk["generation"] if expected_generation is None
                  else expected_generation, fault)

    def readable_selection(self):
        self.require(self.usable)
        selected = self.disk["selected"]
        if selected:
            self.evidence(selected[1], "authorization", selected[0])
        return selected

    def finish(self, position, *, authorized=True, fault=None):
        self.require(self.usable and authorized)
        request = self.disk["pending"]
        self.require(request is not None)
        if self.selected_id() == request.operation:
            self.readable_selection()
            outcome = "applied"
        else:
            self.require(request.prior == self.selected_id())
            outcome = "abandoned"
        self.evidence(position, outcome, request)
        value = deepcopy(self.disk)
        value["closed"][request.operation] = (request, outcome)
        value["pending"] = None
        self.save(value, self.disk["generation"], fault)


R = Request("op-1", "member", "candidate-1", "operator", "reviewed closure", None)


class ContractTests(unittest.TestCase):
    def prepared(self):
        model = Model()
        model.begin(R)
        pos = model.append(Row("authorization", R))
        model.flush()
        return model, pos

    def completed(self):
        model, pos = self.prepared()
        model.select(pos)
        effect = model.append(Row("applied", R))
        model.flush()
        model.finish(effect)
        return model

    def test_denied_stale_or_uncertain_candidate_has_no_effect(self):
        for options in (dict(authorized=False), dict(candidate_matches=False),
                        dict(dependency_labels=("unverified",)), dict(expected_generation=3)):
            with self.subTest(options=options):
                m = Model()
                before = deepcopy(m.__dict__)
                with self.assertRaises(Refused):
                    m.begin(R, **options)
                self.assertEqual(m.__dict__, before)
        m = Model()
        with self.assertRaises(Refused):
            m.begin(replace(R, prior="not-current"))
        self.assertEqual(m.disk["generation"], 0)

    def test_one_pending_per_member_and_identical_resume(self):
        m = Model()
        m.begin(R)
        self.assertEqual(m.begin(R), "pending")
        for request in (replace(R, operation="op-2"), replace(R, candidate="other"),
                        replace(R, actor="other"), replace(R, reason="other")):
            with self.assertRaises(Refused):
                m.begin(request)
        self.assertEqual(m.disk["generation"], 1)

    def test_pending_save_uncertainty_never_mints_a_selection(self):
        for fault in ("before_rename", "after_rename"):
            m = Model()
            with self.assertRaises(Unknown):
                m.begin(R, fault=fault)
            with self.assertRaises(Refused):
                m.readable_selection()
            m.restart()
            self.assertIsNone(m.readable_selection())
            self.assertEqual(m.disk["pending"] is not None, fault == "after_rename")

    def test_finish_save_uncertainty_is_reconciled_from_persistent_state(self):
        for fault in ("before_rename", "after_rename"):
            m, pos = self.prepared()
            m.select(pos)
            effect = m.append(Row("applied", R))
            m.flush()
            with self.assertRaises(Unknown):
                m.finish(effect, fault=fault)
            m.restart()
            self.assertIsNotNone(m.readable_selection())
            self.assertEqual(m.disk["pending"] is None, fault == "after_rename")
            if m.disk["pending"]:
                m.finish(effect)
            self.assertEqual(m.begin(R), "applied")

    def test_every_cut_before_selection_leaves_prior_selected(self):
        for cut in ("pending", "append", "durable"):
            with self.subTest(cut=cut):
                m = self.completed()
                prior = m.readable_selection()
                next_request = replace(R, operation="op-2", candidate="candidate-2", prior="op-1")
                m.begin(next_request)
                if cut != "pending":
                    m.append(Row("authorization", next_request))
                if cut == "durable":
                    m.flush()
                m.restart()
                self.assertEqual(m.readable_selection(), prior)
                self.assertEqual(m.disk["pending"], next_request)

    def test_exact_authorization_row_must_be_durable_not_just_an_earlier_row(self):
        m = Model()
        m.append(Row("unrelated", R))
        m.flush()
        m.begin(R)
        pos = m.append(Row("authorization", R))
        with self.assertRaises(Refused):
            m.select(pos)
        m.flush()
        m.select(pos)
        self.assertEqual(m.readable_selection()[1], pos)

    def test_signature_validity_is_not_operator_or_witness_authority(self):
        for row in (Row("authorization", R, signature_valid=False),
                    Row("authorization", R, operator_authorized=False),
                    Row("authorization", R, witness="different-witness"),
                    Row("authorization", replace(R, candidate="other")),
                    Row("applied", R)):
            with self.subTest(row=row):
                m = Model()
                m.begin(R)
                pos = m.append(row)
                m.flush()
                with self.assertRaises(Refused):
                    m.select(pos)
                self.assertIsNone(m.disk["selected"])

    def test_revalidation_revocation_and_cas_at_selection(self):
        for options in (dict(authorized=False), dict(candidate_matches=False),
                        dict(expected_generation=0)):
            m, pos = self.prepared()
            before = deepcopy(m.disk)
            with self.assertRaises(Refused):
                m.select(pos, **options)
            self.assertEqual(m.disk, before)

    def test_barrier_failure_never_selects(self):
        m = Model()
        m.begin(R)
        pos = m.append(Row("authorization", R))
        with self.assertRaises(Unknown):
            m.flush(fail=True)
        with self.assertRaises(Refused):
            m.select(pos)
        m.restart()
        self.assertEqual(m.rows, [])
        self.assertIsNone(m.readable_selection())

    def test_ambiguous_vault_save_is_unusable_until_reload(self):
        for fault in ("before_rename", "after_rename"):
            with self.subTest(fault=fault):
                m, pos = self.prepared()
                with self.assertRaises(Unknown):
                    m.select(pos, fault=fault)
                self.assertIsNotNone(m.memory["selected"])
                with self.assertRaises(Refused):
                    m.readable_selection()
                m.restart()
                self.assertEqual(m.readable_selection() is not None, fault == "after_rename")
                self.assertEqual(m.disk["pending"], R)

    def test_missing_applied_receipt_is_not_a_claim_of_observed_completion(self):
        m, pos = self.prepared()
        m.select(pos)
        m.restart()
        self.assertIsNotNone(m.readable_selection())
        self.assertNotIn(R.operation, m.disk["closed"])
        self.assertEqual(m.disk["pending"], R)
        with self.assertRaises(Refused):
            m.finish(pos)  # Authorization is not an effect receipt.
        effect = m.append(Row("applied", R))
        m.flush()
        m.finish(effect)
        self.assertEqual(m.begin(R), "applied")

    def test_abandonment_requires_its_own_durable_evidence(self):
        m, authorization = self.prepared()
        with self.assertRaises(Refused):
            m.finish(authorization)
        abandoned = m.append(Row("abandoned", R))
        with self.assertRaises(Refused):
            m.finish(abandoned)
        m.flush()
        m.finish(abandoned)
        m.restart()
        self.assertEqual(m.begin(R), "abandoned")
        self.assertIsNone(m.readable_selection())

    def test_selected_operation_cannot_be_relabelled_abandoned(self):
        m, pos = self.prepared()
        m.select(pos)
        pos = m.append(Row("abandoned", R))
        m.flush()
        with self.assertRaises(Refused):
            m.finish(pos)

    def test_lost_final_response_is_idempotent_and_does_not_reselect_old_version(self):
        m = self.completed()
        r2 = replace(R, operation="op-2", candidate="candidate-2", prior="op-1")
        m.begin(r2)
        pos = m.append(Row("authorization", r2))
        m.flush()
        m.select(pos)
        effect = m.append(Row("applied", r2))
        m.flush()
        with self.assertRaises(Unknown):
            m.finish(effect, fault="after_rename")
        m.restart()
        self.assertEqual(m.begin(r2), "applied")
        self.assertEqual(m.begin(R), "applied")
        self.assertEqual(m.selected_id(), "op-2")
        with self.assertRaises(Refused):
            m.begin(replace(R, candidate="changed"))

    def test_restart_refuses_selected_record_with_missing_authorization(self):
        m = self.completed()
        m.rows[0] = replace(m.rows[0], signature_valid=False)
        m.restart()
        with self.assertRaises(Refused):
            m.readable_selection()


if __name__ == "__main__":
    unittest.main()
