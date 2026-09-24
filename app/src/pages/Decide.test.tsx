import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { PendingEscalation } from "../lib/types";

const getDashboard = vi.fn();
const operatorStatus = vi.fn();
const decideGateEscalation = vi.fn();

vi.mock("../lib/tauri", () => ({
  getDashboard: () => getDashboard(),
  operatorStatus: () => operatorStatus(),
  decideGateEscalation: (id: string, approve: boolean, reason: string | null) =>
    decideGateEscalation(id, approve, reason),
}));

const { Decide } = await import("./Decide");

function escalation(over: Partial<PendingEscalation> = {}): PendingEscalation {
  return {
    id: "0a285e01",
    claimed_by: "claude-code",
    role: "seat",
    tool_name: "Bash",
    marker: "deploy/install-members.sh",
    stated_reason: "refresh the member gates",
    stated_detail: "the installed copy is three commits behind",
    opened_at: 1_700_000_000,
    expires_at: 1_700_004_200,
    secs_remaining: 4200,
    bar: "single_approver",
    factors: [],
    operator_alone_suffices: true,
    still_needs: null,
    request_id: null,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Decide", () => {
  it("offers NO decide control when no operator is signed in", async () => {
    // Not "disabled": absent. A greyed button still says the act is yours to
    // perform; without the key nothing here can be signed at all.
    getDashboard.mockResolvedValue({ pending_escalations: [escalation()] });
    operatorStatus.mockResolvedValue({ signed_in: false, lct_id: null });

    render(<Decide />);
    await screen.findByText(/refresh the member gates/);

    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /deny/i })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("offers approve and deny once an operator is signed in", async () => {
    getDashboard.mockResolvedValue({ pending_escalations: [escalation()] });
    operatorStatus.mockResolvedValue({ signed_in: true, lct_id: "lct:web4:mb32:abc" });

    render(<Decide />);
    expect(await screen.findByRole("button", { name: /approve/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /deny/i })).toBeTruthy();
  });

  it("says an approval is necessary-not-sufficient when the bar needs more", async () => {
    // Approving a sovereign_plus_peer escalation and watching nothing happen is
    // the strongest possible teacher that the button is decorative. It is not,
    // and the operator must be able to tell the two cases apart before clicking.
    getDashboard.mockResolvedValue({
      pending_escalations: [
        escalation({ bar: "sovereign_plus_peer", operator_alone_suffices: false, still_needs: ["peer"] }),
      ],
    });
    operatorStatus.mockResolvedValue({ signed_in: true, lct_id: "lct:x" });

    render(<Decide />);
    expect(await screen.findByText(/NECESSARY, NOT SUFFICIENT/)).toBeTruthy();
    expect(screen.getByText(/still needs peer/)).toBeTruthy();
  });

  it("reports a failed look as a failure, never as an empty queue", async () => {
    // "Nothing is waiting on you" and "I could not ask" are different facts, and
    // rendering the second as the first is the inversion this surface prevents.
    getDashboard.mockRejectedValue(new Error("daemon unreachable"));
    operatorStatus.mockResolvedValue({ signed_in: true, lct_id: "lct:x" });

    render(<Decide />);
    await waitFor(() => expect(screen.getByText(/could not read the queue/)).toBeTruthy());
    expect(screen.queryByText(/Nothing is waiting on you/)).toBeNull();
  });

  it("shows the asker as claimed, not as a proved identity", async () => {
    getDashboard.mockResolvedValue({ pending_escalations: [escalation()] });
    operatorStatus.mockResolvedValue({ signed_in: true, lct_id: "lct:x" });

    render(<Decide />);
    expect(await screen.findByText(/claimed, not proved/)).toBeTruthy();
  });
});
