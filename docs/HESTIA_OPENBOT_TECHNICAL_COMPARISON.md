# Hestia and OpenBot — technical comparison and strategic differentiation

**Status:** external-shareable technical analysis  
**Purpose:** answer the partner/investor question *"How is Hestia different from emerging governed-agent runtimes such as OpenBot?"* without dismissing adjacent work or overstating Hestia's current maturity.  
**Review baseline:** OpenBot `main` at [`88078a4`](https://github.com/CopilotKit/OpenBot/commit/88078a412c52d5e86ee009e4ed1690ecd6c30562), reviewed 2026-08-25 PT; Hestia `main` at `af89203`. Both projects are moving quickly; implementation details should be re-checked before treating this as a procurement comparison.

---

## 1. Executive summary

OpenBot is a serious and technically thoughtful **agent execution substrate**. It gives AI agents computers of their own, browser and file access, MCP tools, policy-controlled action gateways, auditable decisions, human takeover, encrypted credentials, and a framework-neutral AG-UI interface. Its strongest architectural idea is simple and correct: an agent should not execute a consequential action merely because a model emitted a tool call. The action should first pass through a boundary that resolves what the action actually targets, evaluates policy, records the decision, and only then executes or refuses it.

Hestia agrees with that architecture. In fact, Hestia's current Fleet design independently converges on the same move: stop relying only on hooks embedded in third-party harnesses, drive or mediate agents through a gateway, construct a resolved act, apply one law path, witness the decision, and dispatch only after authorization. See [`PRD_FLEET.md`](PRD_FLEET.md).

The important conclusion is therefore **not** that OpenBot is solving the wrong problem. It is solving a necessary lower-layer problem well.

The distinction is that Hestia is trying to solve a larger governance problem above execution:

> **OpenBot primarily governs what a Bot may do. Hestia is designed to establish who the acting entity is, whose authority it exercises, what role it occupies, what evidence supports the decision, what consequences follow from its conduct, and what recourse exists when governance is disputed.**

That difference changes the system's basic object model.

OpenBot's center of gravity is the **Bot + computer + policy + audit row**. Hestia's is the **persistent entity + role/occupancy + delegated authority + law + witnessed action + evidence-derived standing**, connected outward to Web4 hubs and societies.

This does not make Hestia a replacement for OpenBot. The more useful strategic interpretation is almost the reverse:

> **OpenBot can give an agent a computer. Hestia can give that agent a governed identity and a place in a society.**

The execution machinery is highly composable. Hestia should learn from and potentially reuse it rather than competing on browser automation, container supervision, or agent UI plumbing.

---

## 2. OpenBot on its own merit

OpenBot describes itself as a platform for AI coworkers that can be given real access while keeping actions governed. The architecture combines an application UI, API server, PostgreSQL, CopilotKit Intelligence, AG-UI agents, and per-Bot "computers" containing Chromium, a workspace, and persistent browser state. See the [OpenBot architecture](https://github.com/CopilotKit/OpenBot/blob/88078a412c52d5e86ee009e4ed1690ecd6c30562/docs/architecture.md).

The design has several particularly strong properties.

### 2.1 A single action gateway

Browser, file, shell and MCP actions return through a server-side gateway. The intended ordering is:

1. resolve the target;
2. evaluate policy;
3. record the decision;
4. execute only if permitted;
5. separately record execution failure when an allowed act fails.

This is materially better than post-hoc logging. The audit record exists before the side effect, so "allowed but failed" and "never authorized" are distinguishable states.

Hestia has the same ordering invariant in its `begin_action -> dispatch -> record_outcome` model. This convergence is significant because it is an architectural property, not a UI feature.

### 2.2 Policy evaluates resolved state rather than trusting the model's description

For browser actions OpenBot stores snapshots that resolve opaque element references into server-held page information. Policy is evaluated against the server's view of the target rather than merely accepting a caller-supplied label such as "Submit". The policy context can include the Bot, actor, URL/host, resolved element, key, file attributes, command, and MCP server/tool/effect. See [`policy.ts`](https://github.com/CopilotKit/OpenBot/blob/88078a412c52d5e86ee009e4ed1690ecd6c30562/server/src/computer/policy.ts) and [`gateway.ts`](https://github.com/CopilotKit/OpenBot/blob/88078a412c52d5e86ee009e4ed1690ecd6c30562/server/src/computer/gateway.ts).

This matters because a policy boundary based on model-authored prose is not much of a boundary. Hestia's Fleet PRD reaches the same conclusion from a different starting point: its current hook architecture often sees command **text**, which creates both false positives and bypasses. The native-loop design therefore moves toward typed, resolved `ActEnvelope` objects before law evaluation.

### 2.3 Mechanism and effect are separated

OpenBot distinguishes tool mechanism from intended effect. A button may be activated by a click, Enter, or Space; a remote service may expose many separately named write tools. Rules written only against individual tool names are easy to bypass accidentally. OpenBot therefore classifies actions into effects such as `activate`, `read`, `write_file`, `read_tool`, `write_tool`, and `run_command`.

That is exactly the right abstraction pressure. Hestia should preserve the same distinction in its canonical act vocabulary: policy should reason about what an action **does**, not only which adapter happened to carry it.

### 2.4 Skills do not grant capabilities

OpenBot explicitly treats skills as reusable instructions, not authority. Tool selection for a run may be narrowed according to matching skills, but the result is intersected with the tools already granted to the Bot. A skill cannot manufacture a grant merely by naming a tool.

Hestia's role-scope design reaches the same principle from the authority side. [`PRD_ROLE_SCOPE_BRIDGE.md`](PRD_ROLE_SCOPE_BRIDGE.md) treats role skills as role-delivered capability/instruction material, but the role manifest and the member's clearance ceiling still determine what can flow. The shared lesson is load-bearing:

> **Instructions may shape behavior; they must never silently widen authority.**

### 2.5 It treats the agent computer as a real operational boundary

OpenBot is not only a browser wrapper. It has per-Bot workspaces, browser profiles, optional gVisor, Docker supervision, human takeover, screen streaming, shell execution, credential handling, and now Kubernetes/agent-sandbox work tested on EKS. This is the kind of unglamorous infrastructure that takes substantial engineering effort to make reliable.

For Hestia, that is a reason to study it closely rather than dismiss it as "another agent framework."

### 2.6 The engineering culture appears appropriately adversarial

OpenBot is alpha and has meaningful security defects, but the project is unusually explicit about finding them. Recent commits and issues show a repeated pattern: state an invariant, drive the implementation on a real deployment, discover that an assumption was wrong, reproduce the defect, and change the design.

Examples current at this review include:

- [#246](https://github.com/CopilotKit/OpenBot/issues/246): human takeover stopped browser actions but not shell commands or file writes;
- [#237](https://github.com/CopilotKit/OpenBot/issues/237): MCP credential/address binding could allow a stored token to be spent against an unintended address;
- [#226](https://github.com/CopilotKit/OpenBot/issues/226): the all-in-one image placed a Bot shell beside a trust-authenticated owner PostgreSQL instance;
- [#236](https://github.com/CopilotKit/OpenBot/issues/236) and [#158](https://github.com/CopilotKit/OpenBot/issues/158): snapshot generations and computer replacement exposed how subtle resolved-action identity becomes across restarts and replicas.

These are real defects, but the existence and quality of the reports is also evidence of a useful review culture. An adjacent project discovering boundary failures before us is a source of free adversarial design input.

---

## 3. Where the architectures overlap

The overlap is substantial and should be acknowledged directly.

| Concern | OpenBot | Hestia / Fleet |
|---|---|---|
| Local/self-hosted posture | Runs inside the deployment's infrastructure | Local-first daemon; no cloud required for core governance |
| Multi-model / multi-framework | AG-UI endpoint; multiple frameworks/providers | Multi-vendor hooks today; native/provider backends in Fleet PRD |
| Central action mediation | Gateway resolves, decides, records, then acts | One gate core / one authority path / one chain |
| Typed action context | Tool, effect, actor, Bot, page, element, file, MCP, command | Canonical resolved act / `ActEnvelope` direction |
| Deny before side effect | Yes | Yes |
| Record before execution | Audit decision written before execution | Witness decision before dispatch; outcome follows |
| Credential custody | Encrypted server-side vault, write-only APIs | Local encrypted vault; brokered-credential direction |
| Tool grants distinct from instructions | Explicit | Explicit in role scope / skills model |
| Human intervention | Browser takeover, admin policy controls | Escalation, operator decision, peer arbitration path |
| Agent-specific execution environment | Per-Bot computer/container | Fleet PRD needs a gateway execution substrate; A3 is delegated to isolation runtimes |
| Multi-agent work | Coworkers/channels; bot-to-bot proposal | Roles, members, mesh, claimable work, hub societies |

This overlap is strategically positive. It indicates that a meaningful part of Hestia's Fleet direction is not an idiosyncratic architecture invented in isolation; another team working from the execution problem has arrived at many of the same boundary decisions.

---

## 4. The fundamental difference: authorization versus governed standing

The easiest way to confuse the projects is to use the word **governance** for both without defining it.

OpenBot's present governance model is primarily the familiar computer-security stack:

**identity/session -> grants -> policy decision -> permit/refuse -> audit**.

That is necessary. It is also not the full governance model Hestia is building.

Hestia adds several dimensions that change what the record means and what can be done with it.

### 4.1 Persistent cryptographic entity identity

A Bot in OpenBot is a durable application object with a profile and runtime identity. That is sufficient for controlling one deployment.

Hestia's entity is intended to persist across sessions, harnesses and eventually societies as a Web4 LCT-backed member. The acting session is transport; it is not the identity and does not itself confer authority. [`PRD_ASSURANCE.md`](PRD_ASSURANCE.md) makes transport-established identity the hinge requirement for stronger assurance, and [`PRD_FLEET.md`](PRD_FLEET.md) generalizes the session as a witnessed binding of principal LCT, harness LCT, device LCT and role occupancy.

This matters once an entity moves between machines, fills different offices, appears at an external hub, or needs conduct accumulated in one context to be attributable in another.

### 4.2 Roles are authority-bearing offices, not only descriptions

OpenBot coworkers have roles in the ordinary product sense: title, description, visibility, tools and channels.

Hestia uses **role as office**. A member occupies a role under a witnessed, time-bounded occupancy; the role has a manifest; member clearances place an independent ceiling on what may flow through the role; and occupancy expiry removes the derived authority. See [`PRD_ROLE_SCOPE_BRIDGE.md`](PRD_ROLE_SCOPE_BRIDGE.md).

The resulting authority question is not merely:

> Does Bot A have tool X?

It is:

> Is member M presently occupying role R, was that occupancy validly conferred, does R require scope S, is M cleared for S's class, what proof tier is required at act time, and has that proof been produced?

That is a qualitatively different authorization graph.

### 4.3 Delegation and provenance are first-class

Hestia's target act record binds actor, role, instruction/delegation provenance, beneficiary, law version and stable action identity. The reason is that a consequential act is not fully explained by "which process clicked the button." A relying party may need to know whose authority was exercised and through which delegation chain.

That provenance becomes particularly important in multi-agent work, where one agent requests work from another or a role is filled by a different member.

### 4.4 Evidence is meant to outlive the local database

OpenBot's audit trail is an operationally useful PostgreSQL record. It can answer what was permitted, refused and failed within the deployment.

Hestia's stronger target is an **evidence contract**: independently verifiable decisions and witnessed acts that a relying party can evaluate without trusting or even running Hestia. Current Hestia is not yet at that target — [`PRD_ASSURANCE.md`](PRD_ASSURANCE.md) explicitly places the current gate at A1 — but the architecture is oriented toward portable signed decisions, hash-linked evidence, audience binding, replay resistance and externally checkable provenance.

This distinction is central to Web4. A hub should not trust an agent because its local product UI says "trusted." It should be able to inspect evidence and apply its own threshold.

### 4.5 Conduct changes future standing

OpenBot records actions. Hestia additionally derives contextual trust/reputation from witnessed conduct. The current system derives T3/V3 from the chain rather than accepting a self-reported score; the design direction extends that to R6/R7 consequence envelopes and role-aware evidence.

The distinction is:

- **audit:** what happened?
- **standing:** what does the witnessed history imply about this entity in this context, and which receipts support that interpretation?

Hestia deliberately treats the second as a derived interpretation over evidence, not as a universal scalar truth.

### 4.6 Governance includes recourse

OpenBot currently has policy decisions and human takeover/admin controls. Hestia's governance architecture treats **escalation, adjudication and appeal** as part of the constitutional model.

A deny is not supposed to be the end of the conversation. A member may ask a sufficiently permitted resolver before an act, and may challenge the law after a recorded deny. Hestia's current implementation is incomplete here — the governance PRD explicitly documents broken or unfinished appeal links — but the distinction in system design is important:

> A control system asks how to stop unauthorized action. A governance system must also define how governed members can contest and change the rules without routing around them.

### 4.7 Society and federation are part of the object model

OpenBot is currently a deployment-centered system: people, Bots, channels, plugins, policy and audit live within an organization's OpenBot installation.

Hestia is designed as a local sovereign seat that can join Web4 hubs, present members and roles outward, and eventually participate in federation while retaining local authority. Federation is **not built today** and should not be sold as shipped. Hub integration and sealed member/hub channels do exist, but the broader strategic direction is explicitly cross-sovereign rather than one administrative domain.

---

## 5. Side-by-side: what an external technical evaluator should understand

| Dimension | OpenBot | Hestia |
|---|---|---|
| Primary product | Governed AI coworker runtime | Local identity, authority, governance and evidence plane for humans/AI |
| Primary object | Bot/coworker | Persistent member/entity filling roles |
| Agent interoperability | AG-UI | Multi-vendor shims today; native/API/local/subscription paths planned; AG-UI is a candidate adoption |
| Execution environment | Strong focus: browser/workspace/container per Bot | Intentionally not the core differentiator; isolation runtime is a composable lower layer |
| Action boundary | Server gateway + CEL policy | Gate core + law snapshot + escalation/adjudication semantics |
| Action description | Resolved page/tool/file/MCP context | Canonical typed resolved act, with identity/role/delegation provenance |
| Authority | Admin/user grants + policy | Delegation + clearance + role manifest + occupancy + proof tier + local law |
| Audit/evidence | Durable deployment audit rows | Hash-linked witness chain today; portable independently verifiable evidence is explicit target |
| Reputation | Not a central primitive | T3/V3 derived from witnessed history; broader consequence model under development |
| Human intervention | Take browser control; admin controls | Escalation, operator adjudication, peer arbitration, appeal architecture |
| Cross-organization model | Deployment-centered | Hub/society model; federation planned, not yet built |
| Assurance vocabulary | Security boundaries documented operationally | Explicit A0-A4 profiles; current default honestly labeled A1 |
| Infrastructure assumptions | PostgreSQL + CopilotKit Intelligence; Docker/Kubernetes options | Small local daemon, encrypted local state, no Postgres/Kubernetes requirement |
| Edge deployment | Possible but not central | Explicit requirement: runs on small local/Jetson-class nodes |
| Current strength | Execution substrate and productized agent-computer mechanics | Identity, law, witnessed conduct, local-first governance model |
| Current weakness | Alpha boundary defects; limited societal/recourse semantics | Execution/harness substrate less mature; A2+ and federation not shipped |

---

## 6. Where OpenBot is ahead today

A credible comparison should say this plainly.

### 6.1 Agent-computer mechanics

OpenBot has already built much of the machinery needed to give agents persistent browsers, workspaces, interactive screens, shells and per-agent execution contexts. Hestia should not spend months re-learning all of those lessons merely to own every line of code.

### 6.2 AG-UI interoperability

Using AG-UI as the Bot boundary is strategically attractive because it avoids making the runtime synonymous with a particular framework. Hestia's current plugin surface is broader in vendor coverage than many projects, but it is still shim-oriented. A protocol-level agent surface would reduce adapter churn.

### 6.3 Operational deployment experience

OpenBot is exercising Docker, gVisor, Kubernetes, scale-to-zero and replica behavior now. Hestia's design correctly says A3 isolation belongs to an isolation runtime; OpenBot is providing useful evidence about what such a runtime actually requires in production.

### 6.4 Human-in-the-loop browser UX

Watching an agent's screen, taking control, and handing it back is a concrete human experience that Hestia's governance UI can learn from. The current #246 defect also supplies a useful negative requirement: "human has control" must mean **all mutating effectors are stopped**, not only browser clicks.

---

## 7. Where Hestia is intentionally different

The difference should not be marketed as "more features." It is a different layer and therefore a different composition boundary.

### 7.1 Hestia does not want to own every agent loop

The long-term value is not in writing the best browser driver, planner or UI. Those functions will continue to commoditize, migrate between frameworks, and increasingly move into model behavior itself.

Hestia's non-absorbable responsibilities are the ones outside the model:

- credential custody;
- identity/session binding;
- authority and law;
- evidence/witness;
- role/occupancy/delegation;
- consequence and recourse;
- society-level budgets and trust interpretation.

Those remain necessary regardless of which model or harness is fashionable.

### 7.2 Hestia does not claim the agent's local record should be trusted by assertion

The north star is independently verifiable evidence. This is why Hestia separates the actor's statement, policy decision, execution observation, witness observation and adjudication rather than allowing one party to author all of them.

### 7.3 Hestia treats humans and AI as the same category of governed member

The Web4 model is not an "AI management console" with humans outside the ontology. Humans, AI agents, devices, roles and organizations can all participate as entities with relationships and evidence. That becomes important in mixed societies where the question is not "what may our Bots do?" but "which entities are trusted to fill which offices under which law?"

---

## 8. The strategically correct relationship is composition, not denial

There are three plausible responses to a project like OpenBot:

1. dismiss it as a different product;
2. compete by rebuilding all of its lower-layer machinery;
3. treat it as a potential execution substrate and put Hestia's authority/evidence contract across the seam.

The third is the strongest answer.

A concrete integration shape is straightforward:

```text
persistent Hestia member / role / occupancy
                 |
                 v
        canonical resolved act
                 |
                 v
        Hestia law + evidence
         decision / obligations
                 |
        signed portable decision
                 |
                 v
      OpenBot execution gateway
                 |
       browser / file / MCP
                 |
                 v
          observed outcome
                 |
                 v
       Hestia witness/consequence
```

OpenBot becomes the **relying executor**. Hestia does not need to replace its browser, container supervisor or AG-UI endpoint. The executor simply refuses consequential actions unless the Hestia decision verifies for the exact act and audience.

That integration would also be an unusually clean demonstration of Hestia's A2 thesis from [`PRD_ASSURANCE.md`](PRD_ASSURANCE.md):

> killing or removing the agent-side Hestia hook does not authorize the action, because the external executor still requires the decision.

It would be more persuasive than demonstrating the same property only inside Hestia's own codebase.

---

## 9. What we should learn rather than reinvent

The companion implementation document, [`PRD_FLEET_OPENBOT_EXECUTION_SUBSTRATE.md`](PRD_FLEET_OPENBOT_EXECUTION_SUBSTRATE.md), turns the following into concrete requirements:

- evaluate resolved actions, not caller descriptions;
- distinguish effect from mechanism;
- adopt AG-UI interoperability where it fits;
- separate the execution-computer abstraction from governance semantics;
- use per-agent persistent execution contexts rather than a shared ambient host where stronger isolation is required;
- make human-control leases cover every mutating effector;
- make action references session/epoch-aware so restart and replica behavior cannot revive stale state;
- bind credentials to audience/server and rotate atomically;
- keep instructions/skills distinct from capabilities;
- use durable leased work claims for unattended/multi-agent work;
- preserve the distinction between live activity UI and durable evidence;
- test real deployment topology, not merely unit-level assumptions.

What Hestia should **not** import is equally important:

- OpenBot's policy store must not become Hestia's source of authority;
- PostgreSQL or Kubernetes must not become mandatory Hestia infrastructure;
- CopilotKit Intelligence must not become the required memory/session authority;
- an OpenBot Bot profile must not substitute for Hestia entity identity;
- a mutable application audit table must not replace Hestia's evidence contract;
- tool-selection/narrowing must never be treated as a security boundary;
- adding a shell to a bounded member must visibly lower the assurance profile rather than quietly widening the trusted computing base.

---

## 10. Questions investors and partners are likely to ask

### "Why not just use OpenBot?"

If the requirement is "give AI coworkers browsers and tools with centrally administered policies," OpenBot may be a very reasonable answer.

If the requirement extends to persistent cryptographic identity, role-based delegated authority, evidence-derived standing, cross-organization governance, independently verifiable action evidence, and recourse/adjudication, those are not merely deployment settings on the same object model. They are the layer Hestia is being built to supply.

The two can compose.

### "Is Hestia reinventing OpenBot?"

It should not. The overlap is useful evidence that Hestia needs a proper gateway execution boundary. The correct engineering response is to adopt proven protocols and substrate patterns wherever possible and reserve Hestia-specific work for identity, authority, evidence and governance.

### "Could OpenBot add these features?"

Of course. Nothing here should be presented as magically uncopyable.

The defensibility is in **architectural coherence, accumulated evidence semantics, integrations, operating history and the ecosystem built around the model**, not in claiming that another competent team is unable to implement cryptography or roles. Adding the Web4 model to OpenBot would, however, change its fundamental subject of governance from application Bots inside one deployment to persistent entities whose authority and reputation survive sessions and administrative domains.

### "What is actually working in Hestia today?"

The current system has a measured multi-vendor cooperative gate, encrypted vault, witness chain, per-member policy, human escalation, delegation, T3/V3 derivation, dashboard and hub/member-channel plumbing. The repository explicitly labels the present assurance ceiling **A1**. Strong external enforcement, full native-harness operation, hardware-rooted assurance and federation are not shipped claims today. See the current [`README.md`](../README.md) and [`PRD_ASSURANCE.md`](PRD_ASSURANCE.md).

### "What is OpenBot better at today?"

Agent execution. Its per-Bot computers, browser UX, AG-UI boundary and deployment work are more mature than Hestia's planned native execution substrate. That is exactly why it is worth learning from.

---

## 11. Current-state caution

Neither project should be evaluated from architecture diagrams alone.

OpenBot marks itself alpha and its current issue tracker contains real boundary defects. Hestia marks itself R&D and explicitly states that the default gate is cooperative rather than adversarially isolated. Both are healthier for saying so.

The fair comparison is therefore not "which product is already finished?" It is:

- **OpenBot:** a rapidly maturing governed-agent execution environment with strong practical work on the computer/tool boundary;
- **Hestia:** a rapidly maturing governance/evidence architecture whose differentiator begins where ordinary application authorization ends.

The most promising route is to let each layer become good at its own job and define a verifiable seam between them.

---

## 12. One-sentence positioning

For an external technical audience:

> **OpenBot governs an AI worker's access to a computer; Hestia governs the identity, authority, evidence and standing of the entity doing the work — and is designed so an executor such as OpenBot can enforce that governance without having to trust the agent.**

That is the difference worth defending.