"""Offline model of one possible reach-change recovery contract; NOT runtime code.

The model assumes a durable per-operation standing receipt, a durable live-effect
receipt, and a chain that enforces operation-ID uniqueness. Those mechanisms are
not established by this model. It neither authorizes nor performs a real grant.
"""
from dataclasses import dataclass, field


class Refused(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    operation: str
    actor: str
    binding: str  # Synthetic stand-in for a canonical, authority-bound plan digest.
    desired: str


@dataclass
class Model:
    epoch: int = 0
    current_standing: str = "initial"
    current_live: str = "initial"
    intent: Plan | None = None
    intent_epoch: int | None = None
    standing_generation: int = 0
    standing_receipts: dict[str, tuple[Plan, int]] = field(default_factory=dict)
    live_receipts: dict[str, tuple[Plan, int]] = field(default_factory=dict)
    terminal_rows: dict[str, tuple[Plan, int]] = field(default_factory=dict)
    _applied_live: tuple[Plan, int] | None = None

    def begin(self, plan: Plan, *, authorized: bool) -> None:
        if not authorized:
            raise Refused("authority not established")
        if self.intent is None:
            self.intent = plan
            self.intent_epoch = self.epoch
        elif self.intent != plan:
            raise Refused("operation ID or bound plan mismatch")

    def _require_intent(self, plan: Plan) -> None:
        if self.intent != plan:
            raise Refused("no matching admitted intent")

    def commit_standing(self, plan: Plan) -> None:
        self._require_intent(plan)
        prior = self.standing_receipts.get(plan.operation)
        if prior is not None:
            if prior[0] != plan:
                raise Refused("standing receipt conflicts")
            return  # A retry must not overwrite a later authorized change.
        if self.intent_epoch != self.epoch:
            raise Refused("standing retry after restart needs a separate recovery decision")
        # Assumption: state and operation receipt commit together in one store.
        self.current_standing = plan.desired
        self.standing_generation += 1
        self.standing_receipts[plan.operation] = (plan, self.standing_generation)

    def apply_live(self, plan: Plan) -> None:
        self._require_intent(plan)
        receipt = self.standing_receipts.get(plan.operation)
        if receipt is None or receipt[0] != plan:
            raise Refused("standing effect not established")
        if receipt[1] != self.standing_generation or self.current_standing != plan.desired:
            raise Refused("standing state changed since this operation")
        if self.intent_epoch != self.epoch:
            raise Refused("live outcome after restart needs a separate recovery decision")
        if self._applied_live == (plan, self.epoch):
            raise Refused("live effect already applied in this epoch")
        if plan.operation in self.live_receipts:
            raise Refused("do not replay a witnessed historical live effect")
        self.current_live = plan.desired
        self._applied_live = (plan, self.epoch)

    def record_live(self, plan: Plan) -> None:
        self._require_intent(plan)
        if self._applied_live != (plan, self.epoch):
            raise Refused("live effect not observed in this epoch")
        # Assumption: this observation can be durably bound to the same plan.
        self.live_receipts[plan.operation] = (plan, self.epoch)

    def publish(self, plan: Plan, *, lose_reply: bool = False) -> None:
        self._require_intent(plan)
        live = self.live_receipts.get(plan.operation)
        standing = self.standing_receipts.get(plan.operation)
        if standing is None or standing[0] != plan or live is None or live[0] != plan:
            raise Refused("terminal outcome lacks effect evidence")
        terminal = (plan, live[1])
        prior = self.terminal_rows.get(plan.operation)
        if prior is not None and prior != terminal:
            raise Refused("terminal identity conflicts")
        # Assumption: append is durable and idempotent under operation identity.
        self.terminal_rows[plan.operation] = terminal
        if lose_reply:
            raise OSError("synthetic lost reply after terminal append")

    def restart(self) -> None:
        self.epoch += 1
        self.current_live = "unknown-after-restart"
        self._applied_live = None

    def later_standing_change(self, value: str) -> None:
        self.current_standing = value
        self.standing_generation += 1

    def observed_outcome(self, plan: Plan) -> str:
        """Return evidence-backed history, not a claim about current live authority."""
        self._require_intent(plan)
        terminal = self.terminal_rows.get(plan.operation)
        if terminal is not None:
            if terminal[0] != plan:
                raise Refused("terminal identity conflicts")
            return "witnessed-historical-completion"
        standing = self.standing_receipts.get(plan.operation)
        if standing is not None and standing[0] == plan:
            return "standing-committed-live-unknown"
        return "outcome-unknown"
