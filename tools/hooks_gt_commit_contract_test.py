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
    reservation_generation: int | None = None
    authorization: int | None = None
    observed_generation: int | None = None


@dataclass(frozen=True)
class Selection:
    request: Request
    authorization: int
    reservation_generation: int
    reservation_floor: int
    generation: int
    outcome_floor: int


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
        self.disk = dict(generation=0, pending=None, reservation=None,
                         selected=None, closed={})
        self.memory = deepcopy(self.disk)
        self.rows = []
        self.durable = 0
        self.usable = True

    def require(self, value):
        if not value:
            raise Refused()

    def save(self, value, expected_generation, fault=None):
        self.require(self.usable and self.memory["generation"] == expected_generation
                     and self.disk["generation"] == expected_generation)
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
        self.require(self.usable)
        selected = self.memory["selected"]
        return selected.request.operation if selected else None

    def begin(self, request, *, authorized=True, candidate_matches=True,
              dependency_labels=(), expected_generation=None, fault=None):
        self.require(self.usable and authorized and candidate_matches and not dependency_labels)
        self.require(request.member == "member" and all((request.operation, request.candidate,
                                                       request.actor, request.reason)))
        old = self.memory["closed"].get(request.operation)
        if old:
            self.require(old[0] == request)
            return old[1]  # Historical result; NEVER reselect an older certification.
        if self.memory["pending"]:
            self.require(self.memory["pending"] == request)
            return "pending"  # Explicit resume still needs fresh authority below.
        self.require(request.prior == self.selected_id())
        # A saved frontier must survive restart; do not anchor it in volatile rows.
        self.require(self.durable == len(self.rows))
        value = deepcopy(self.memory)
        value["pending"] = request
        value["reservation"] = (self.memory["generation"] + 1, len(self.rows))
        self.save(value, self.memory["generation"] if expected_generation is None
                  else expected_generation, fault)
        return "pending"

    def append(self, row):
        self.require(self.usable)
        self.rows.append(row)
        return len(self.rows) - 1

    def flush(self, fail=False):
        self.require(self.usable)
        if fail:
            self.usable = False
            raise Unknown()
        self.durable = len(self.rows)

    def evidence(self, position, kind, request, reservation_generation, floor):
        self.require(type(position) is int and 0 <= position < self.durable)
        row = self.rows[position]
        self.require(position >= floor and row.kind == kind and row.request == request
                     and row.reservation_generation == reservation_generation
                     and row.signature_valid and row.operator_authorized
                     and row.witness == "expected-witness")
        return row

    def authorize(self):
        """Well-ordered writer; append remains available for adversarial fixtures."""
        self.require(self.usable and self.memory["pending"] is not None)
        return self.append(Row("authorization", self.memory["pending"],
                               reservation_generation=self.memory["reservation"][0]))

    def has_abandonment(self, request, generation, floor, ceiling=None):
        # A row appended after selection cannot abandon that persisted effect.
        end = self.durable if ceiling is None else min(self.durable, ceiling)
        for position in range(floor, end):
            try:
                row = self.evidence(position, "abandoned", request, generation, floor)
                self.require(row.authorization is None and row.observed_generation == generation)
                return True
            except Refused:
                pass
        return False

    def select(self, position, *, authorized=True, candidate_matches=True,
               expected_generation=None, fault=None):
        self.require(self.usable and authorized and candidate_matches)
        request = self.memory["pending"]
        self.require(request is not None and request.prior == self.selected_id())
        generation, floor = self.memory["reservation"]
        self.evidence(position, "authorization", request, generation, floor)
        # The selection barrier covers all staged rows: a volatile abandonment
        # must not become durable after selection and contradict its outcome.
        self.require(self.durable == len(self.rows))
        self.require(not self.has_abandonment(request, generation, floor))
        value = deepcopy(self.memory)
        value["selected"] = Selection(request, position, generation, floor,
                                      self.memory["generation"] + 1, len(self.rows))
        self.save(value, self.memory["generation"] if expected_generation is None
                  else expected_generation, fault)

    def readable_selection(self):
        self.require(self.usable)
        selected = self.memory["selected"]
        if selected:
            self.evidence(selected.authorization, "authorization", selected.request,
                          selected.reservation_generation, selected.reservation_floor)
        return selected

    def observe(self, *, authorized=True):
        """Witness persisted selection (or unchanged prior), with the lock held.

        Disk read is intentional here: outcome evidence observes persistence,
        whereas ordinary readers and transition planning use memory.
        """
        self.require(self.usable and authorized and self.memory == self.disk)
        request = self.memory["pending"]
        self.require(request is not None)
        generation, _ = self.memory["reservation"]
        if self.selected_id() == request.operation:
            selected = self.readable_selection()
            row = Row("applied", request, reservation_generation=generation,
                      authorization=selected.authorization,
                      observed_generation=selected.generation)
        else:
            self.require(request.prior == self.selected_id())
            row = Row("abandoned", request, reservation_generation=generation,
                      observed_generation=self.disk["generation"])
        return self.append(row)

    def finish(self, position, *, authorized=True, expected_generation=None, fault=None):
        self.require(self.usable and authorized)
        request = self.memory["pending"]
        self.require(request is not None)
        generation, floor = self.memory["reservation"]
        if self.selected_id() == request.operation:
            selected = self.readable_selection()
            outcome = "applied"
            row = self.evidence(position, outcome, request, generation, selected.outcome_floor)
            self.require(position > selected.authorization
                         and row.authorization == selected.authorization
                         and row.observed_generation == selected.generation
                         and not self.has_abandonment(request, generation, floor,
                                                     selected.outcome_floor))
        else:
            self.require(request.prior == self.selected_id())
            outcome = "abandoned"
            row = self.evidence(position, outcome, request, generation, floor)
            self.require(row.authorization is None and row.observed_generation == generation)
        value = deepcopy(self.memory)
        value["closed"][request.operation] = (request, outcome)
        value["pending"] = None
        value["reservation"] = None
        self.save(value, self.memory["generation"] if expected_generation is None
                  else expected_generation, fault)


R = Request("op-1", "member", "candidate-1", "operator", "reviewed closure", None)


class ContractTests(unittest.TestCase):
    def prepared(self):
        model = Model()
        model.begin(R)
        pos = model.authorize()
        model.flush()
        return model, pos

    def completed(self):
        model, pos = self.prepared()
        model.select(pos)
        effect = model.observe()
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
                        replace(R, actor="other"), replace(R, reason="other"),
                        replace(R, prior="other")):
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
            effect = m.observe()
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
                    m.authorize()
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
        pos = m.authorize()
        with self.assertRaises(Refused):
            m.select(pos)
        m.flush()
        m.select(pos)
        self.assertEqual(m.readable_selection().authorization, pos)

    def test_signature_validity_is_not_operator_or_witness_authority(self):
        for row in (Row("authorization", R, signature_valid=False),
                    Row("authorization", R, operator_authorized=False),
                    Row("authorization", R, witness="different-witness"),
                    Row("authorization", replace(R, candidate="other")),
                    Row("applied", R)):
            with self.subTest(row=row):
                m = Model()
                m.begin(R)
                pos = m.append(replace(row, reservation_generation=m.memory["reservation"][0]))
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
        pos = m.authorize()
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
        effect = m.observe()
        m.flush()
        m.finish(effect)
        self.assertEqual(m.begin(R), "applied")

    def test_abandonment_requires_its_own_durable_evidence(self):
        m, authorization = self.prepared()
        with self.assertRaises(Refused):
            m.finish(authorization)
        abandoned = m.observe()
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
        pos = m.append(Row("abandoned", R, reservation_generation=1, observed_generation=1))
        m.flush()
        with self.assertRaises(Refused):
            m.finish(pos)

    def test_post_selection_abandonment_cannot_strand_member(self):
        for restart in (False, True):
            for offset in (0, 1):
                with self.subTest(restart=restart, offset=offset):
                    m, authorization = self.prepared()
                    m.select(authorization)
                    selected = m.readable_selection()
                    if offset:
                        m.append(Row("unrelated", R))
                    abandoned = m.append(Row("abandoned", R, reservation_generation=1,
                                             observed_generation=1))
                    self.assertEqual(abandoned, selected.outcome_floor + offset)
                    effect = m.observe()
                    m.flush()
                    if restart:
                        m.restart()
                    before = deepcopy(m.__dict__)
                    with self.assertRaises(Refused):
                        m.finish(abandoned)
                    self.assertEqual(m.__dict__, before)
                    m.finish(effect)
                    self.assertEqual(m.begin(R), "applied")
                    self.assertIsNone(m.disk["pending"])
                    self.assertEqual(m.readable_selection(), selected)
                    self.assertEqual(m.rows[abandoned].kind, "abandoned")
                    successor = replace(R, operation="op-2", candidate="candidate-2",
                                        prior=R.operation)
                    self.assertEqual(m.begin(successor), "pending")

    def test_lost_final_response_is_idempotent_and_does_not_reselect_old_version(self):
        m = self.completed()
        r2 = replace(R, operation="op-2", candidate="candidate-2", prior="op-1")
        m.begin(r2)
        pos = m.authorize()
        m.flush()
        m.select(pos)
        effect = m.observe()
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

    def test_pre_reservation_authorization_cannot_bind_a_later_reservation(self):
        m = Model()
        # Even predicting the next generation cannot backdate authorization.
        pos = m.append(Row("authorization", R, reservation_generation=1))
        m.flush()
        m.begin(R)
        before = deepcopy(m.__dict__)
        with self.assertRaises(Refused):
            m.select(pos)
        self.assertEqual(m.__dict__, before)
        pos = m.authorize()
        m.flush()
        m.select(pos)

    def test_authorization_for_a_different_reservation_is_refused(self):
        m, _ = self.prepared()
        pos = m.append(Row("authorization", R, reservation_generation=0))
        m.flush()
        with self.assertRaises(Refused):
            m.select(pos)
        self.assertIsNone(m.readable_selection())

    def test_pre_selection_receipt_cannot_observe_a_later_selection(self):
        m, pos = self.prepared()
        # Correct-looking future bindings still precede the selection frontier.
        effect = m.append(Row("applied", R, reservation_generation=1,
                              authorization=pos, observed_generation=2))
        m.flush()
        m.select(pos)
        before = deepcopy(m.__dict__)
        with self.assertRaises(Refused):
            m.finish(effect)
        self.assertEqual(m.__dict__, before)
        effect = m.observe()
        m.flush()
        m.finish(effect)

    def test_applied_receipt_must_bind_exact_selection_and_generation(self):
        for changed in (dict(reservation_generation=0), dict(authorization=99),
                        dict(observed_generation=1)):
            m, pos = self.prepared()
            m.select(pos)
            row = Row("applied", R, reservation_generation=1,
                      authorization=pos, observed_generation=2)
            effect = m.append(replace(row, **changed))
            m.flush()
            with self.assertRaises(Refused):
                m.finish(effect)
            self.assertEqual(m.memory["pending"], R)

    def test_abandonment_prevents_selection_before_and_after_restart(self):
        for durable in (False, True):
            m, pos = self.prepared()
            abandoned = m.observe()
            if durable:
                m.flush()
            before = deepcopy(m.__dict__)
            with self.assertRaises(Refused):
                m.select(pos)
            self.assertEqual(m.__dict__, before)
            m.flush()
            m.restart()
            with self.assertRaises(Refused):
                m.select(pos)
            m.finish(abandoned)
            self.assertEqual(m.begin(R), "abandoned")
            self.assertEqual([row.kind for row in m.rows], ["authorization", "abandoned"])

    def test_close_has_stale_generation_cas_for_both_outcomes(self):
        for applied in (False, True):
            m, pos = self.prepared()
            if applied:
                m.select(pos)
            effect = m.observe()
            m.flush()
            before = deepcopy(m.__dict__)
            with self.assertRaises(Refused):
                m.finish(effect, expected_generation=m.memory["generation"] - 1)
            self.assertEqual(m.__dict__, before)
            m.finish(effect)

    def test_readers_use_memory_and_observation_requires_persisted_agreement(self):
        m, pos = self.prepared()
        m.select(pos)
        m.memory["selected"] = None
        self.assertIsNone(m.readable_selection())
        self.assertIsNone(m.selected_id())
        with self.assertRaises(Refused):
            m.observe()
        m.restart()
        self.assertEqual(m.selected_id(), R.operation)

    def test_stale_memory_generation_cannot_overwrite_persistent_state(self):
        for transition in ("begin", "select", "finish"):
            m, pos = self.prepared()
            if transition == "begin":
                m = Model()
                action = lambda **options: m.begin(R, **options)
            elif transition == "select":
                action = lambda **options: m.select(pos, **options)
            else:
                m.select(pos)
                effect = m.observe()
                m.flush()
                action = lambda **options: m.finish(effect, **options)
            m.disk["generation"] += 1  # Another process advanced the vault.
            before = deepcopy(m.__dict__)
            with self.assertRaises(Refused):
                action()
            self.assertEqual(m.__dict__, before)
            # Supplying a newer disk generation cannot bless stale memory.
            with self.assertRaises(Refused):
                action(expected_generation=m.disk["generation"])
            self.assertEqual(m.__dict__, before)


if __name__ == "__main__":
    unittest.main()
