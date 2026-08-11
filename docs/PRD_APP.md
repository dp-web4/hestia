# PRD — the Hestia app

**Status:** draft for review. Lead: claude-code (CBP), at dp's direction 2026-08-08.
**Reviewers owed:** kimi, codex (out of usage), legion, GPT. **Not ratified.**
**Amended by decision 0014** (#297, GPT-reviewed): the app is a *member with its own harness
LCT*, not a dashboard on a daemon; identity and governance are separate domains; presence is a
profile and Sovereign remains an office. Sections below are updated where 0014 rules.

**Scope:** the owner-facing application. Does not restate `PRD.md` (product) or `PRD_GOVERNANCE.md`
(society); both are assumed and cited.

---

## 1. Mandate, in one sentence

`PRD.md` §4.5 names three relying parties and then says of the first:

> **"Unsettled for the human one: the owner is a *named* consumer, not yet a *served* one."**

**The app is how the owner becomes served.** Everything below is subordinate to that. If a decision
makes the evidence more complete but the owner less able to act on it, the decision is wrong.

---

## 2. What exists — measured, 2026-08-08 at `a745180`

### 2.1 There are two UIs, and the one that is used is not the app

| | daemon web dashboard | Tauri app (`app/`) |
|---|---|---|
| size | **2,816 lines** (`core/src/server/dashboard/index.html`) | 38 source files |
| approve / deny escalations | **~100-107** (kimi's word-bounded count; my 116 used a looser tokenisation) | **none** |
| constellation | — | **none** |
| hubs | — | read-only list (126 lines) |
| in practice | **this is what dp uses** | not released, not used |

The app's API module (`app/src/lib/tauri.ts`) defines **21 invoke call sites: 12 reads and 9 writes**
(kimi, verified at `a745180`). My first count said 14/12/2 — I grepped components with `sort -u`,
which deduped and missed the module's full surface. The writes are `operator_sign_in`/`_out`,
`add_remote`, `remove_remote`, `vault_set`, `vault_delete`, `set_preset`, `set_mode`,
`set_daemon_url`.

**The conclusion is unchanged and the characterisation is not:** none of the 21 touches
constellation or hub. But "a monitor" was kinder than the truth — it is a monitor **plus
scattered config writes**, which is a worse starting point, not a better one.

**So the app is today a strictly weaker duplicate of the dashboard, plus a fleet view.** That is the
most important fact in this assessment, and it sets the shape of the work: the app's problem is not
missing panels, it is that it was built as a *monitor* for a persona who needs an *instrument*.

### 2.2 The capability is in the daemon; the app does not reach it

`hestia constellation` ships **12 verbs** (`add`, `add-remote`, `list`, `remove`, `proof`, `enroll`,
`revoke`, `enrolled`, `present`, `serve-owner`, `serve-owners`, `cosign-serve`). `hestia hub` ships
**connect / join / list / show / disconnect / set-member-key / send-secret / notify / notifications**
plus pairing.

The app exposes **none** of it. This is the fleet's recurring shape one layer up: *the mechanism
exists and is under-connected.* Most of this PRD is therefore **exposure and arrangement**, not
construction — and any sprint that reads as "build constellation" is mis-scoped.

### 2.3 There is no artifact

No desktop bundle is released on any platform. The only public artifact is an Android APK from
2026-06-13, older than the daemon it pairs with. `PRD.md` §11 already calls release cadence *"the
largest gap between what this document promises and what a user can obtain."*

> A prior readiness audit of mine claimed a Windows MSI existed. It did not; the filename appeared
> in no repository but my own audit. Corrected at `shared-context@5c18b89a`. Recorded here because
> **an app PRD written against an imagined artifact is the same error one level up.**

### 2.4 What shipped on the DASHBOARD since this baseline (2026-08-11, `v0.0.4-29`)

The measured state above is the **Tauri app**. The **daemon web dashboard** — the surface dp actually
uses — moved substantially after `a745180`, and toward this PRD's own IA (§4), not away from it:

- **Two top-level views, Agents and Hubs, with a masthead switch** (`#348`/`#349`). The hub surface
  was a strip at the bottom of the agents screen; it is now a peer view. This is the dashboard
  reaching the same split §4.1 proposes for the app — *Activity* (agents/local governance) vs
  *Communities* (hubs) — arrived at from the other end. The switch defaults intelligently: a hestia
  with no local agents and no trust history opens on Hubs (its whole screen on a mobile/hub-only
  node), matching this PRD's "hubs is the dominant surface where there is nothing local to govern."
- **The trust box is now contextual** (`#349`): *All* selected → one line per **harness** (aggregate
  level, actions, role count); one harness selected → **role trust** for that harness with the full
  tensor/receipts on drill-in. This is §4.3 progressive disclosure made operable in the dashboard.
- **Idle-but-known harnesses are surfaced** (`v0.0.4-29`): a member idle for days (kimi-code) shows
  its most recent standing with an "idle Nd/Nmo" marker rather than vanishing. This is a **stopgap**
  for the deeper fix now specified in **[`PRD_TRUST_CACHE.md`](PRD_TRUST_CACHE.md)** — trust lives in
  the vault as a situational cache, read for display, recomputed on a trigger, never re-derived per
  poll. The dashboard trust surface is the first consumer of that cache.
- Operator **escalation/scope banners stay global**, above whichever view is mounted — a pending
  decision is never hidden behind a tab, which is R0 (§3) holding under the new structure.

The point for the app: the dashboard is now a working reference for the IA this PRD argues, and the
app's job (§2.1) is still to become the *instrument* the dashboard is proving out, not to re-invent it.

---

## 3. The primary persona is no longer unevidenced

`PRD.md` §11: *"The primary persona is unevidenced. Every capability we have shipped was driven by
the tertiary persona (the agents)... the roadmap will keep being argued from a persona we have never
watched use the product."*

**2026-08-06 → 08 is an observation of that persona.** dp operated this system continuously for two
days. What was watched, in dp's own words:

- *"i'm just rubberstamping because i can't see who's doing what and why, and being flooded with
  false positives."*
- *"we just have 3 harnesses on one machine and it's already a mess."*
- On being shown an approval panel: *"none of the acts in the record match the numbers you provided."*

And measured alongside it: **215 of 215 escalation decisions made by the operator**, zero by any
agent; **87% of escalations from one member**; **314 of 314** escalations carrying no link to the act
they appeal.

This is exactly §11's *"escalation fatigue is the fail-open the corpus tests cannot see... an owner
trained by forty prompts a day to click yes has become a fail-open that lives in a person, not in a
type."* It is no longer a predicted risk. **It happened, to the primary user, this week.**

**Design consequence, and the single most important requirement in this document:**

> **R0 — the app is judged by decisions the owner can make well, not by information it displays.**
> A screen that increases what the owner knows while leaving them unable to act is a regression. The
> metric is not prompts served; it is prompts *not needed*, and confidence in the ones that remain.

---

## 4. Information architecture — the requirement that governs the rest

dp: *"logical hierarchical UI that is easily navigable on mobile or desktop, with all functions
reachable without cluttering the screen by non-salient data."*

Today: **eight flat sidebar routes** (Dashboard, Vault, Chain, Delegations, Hubs, Policy, Fleet,
Settings). Flat lists do not survive a phone, and they force every concept to the top level at equal
weight — which is why "Chain" (an audit substrate) sits beside "Hubs" (a thing the owner joins).

### 4.1 Three places, not eight

Organised by **what the owner is thinking about**, not by which subsystem serves it:

| place | the owner's question | contains |
|---|---|---|
| **Me** | *"who am I, and what is mine?"* | identity, **devices/constellation**, vault, assurance tier |
| **Communities** | *"who am I part of?"* | hubs: discover, join, membership, roles, peers |
| **Activity** | *"what happened, and what needs me?"* | pending decisions, agents/fleet, history/chain, policy |

**Settings is not a place.** Configuration lives where the thing being configured lives. A settings
screen is where functions go to become unreachable.

**Rationale for exactly three:** each maps to a distinct mental model that already exists outside
this product (my stuff / my groups / what's going on). Web4 concepts attach to those models rather
than replacing them — the owner should never need to learn the word "constellation" to use one.

### 4.2 Salience: one surface answers "does anything need me?"

The default view is **not** a dashboard of metrics. It is the set of things awaiting the owner —
usually empty. Empty is the correct and most common state, and it must *look* correct rather than
look broken.

Everything else is reachable in **at most two taps** and shown only when asked for. Chain entries,
trust tensors, tool histograms, derivation internals: all present, none default.

> **R1 — non-salient data is never on a default path.** If a datum cannot change what the owner does
> in the next minute, it does not appear until requested.

> **R1a — safety/governance status is surfaced usefully and prominently, never buried in a drawer**
> (dp, 2026-08-11). Coverage — *is each harness actually governed, or is a gate MISWIRED and failing
> OPEN?* — is the single most consequential thing the owner can be wrong about, and it is the
> counterpart to R1: it is *always* salient. It must be readable at a glance on the primary surface,
> not behind a click. A drawer that shows "nothing wrong" on a fully-governed box reads as "useless"
> and gets removed — losing the alarm for the day a gate *is* miswired. The requirement is that the
> status live where the owner already looks. **Met in the dashboard by:** a colored coverage dot on
> each harness chip (green governed · amber not-fully-governed · **red MISWIRED — fails open**) and a
> coverage badge in the header of that harness's role-trust view. The specific rendering is an
> implementation of the requirement, not the requirement — the invariant is *prominent, glanceable,
> per-harness*, and `miswired` must be the loudest state because it is the one that fails open.

### 4.3 Progressive disclosure, three depths

Every decision surface renders at three depths, and **the owner chooses the depth, never the app**:

1. **Plain** — what is being asked, in a sentence, with the two or three facts that bear on it.
2. **Evidence** — what the system knows and how it knows it: identity basis, prior acts, what
   changes if approved.
3. **Raw** — the chain entry, the digest, the policy trace.

This is `PRD.md` §4.2 (*invisible security*) and §4.5 (*evidence, not verdict*) made operable: depth
3 always exists, depth 1 is always enough for a safe default, and the app never collapses evidence
into a verdict on the owner's behalf.

### 4.4 One layout, two shapes

`PRD.md` §4.4 requires one binary across desktop and mobile. **Mobile is the constraining form and
therefore the design target**; desktop is mobile's information architecture with more shown at once,
never a different structure. Three places become a bottom tab bar on mobile and a narrow rail on
desktop. A function reachable on one and not the other is a defect, not a platform difference.

---

## 5. Constellation management — the most important part

dp ranked this first in importance. It is also the capability with **zero** app surface today.

### 5.1 What it is, in owner terms

*"All my devices, as one."* The constellation is what makes the owner's **assurance tier** real: the
hub derives the tier from **enrolled** devices, so devices are not a convenience — they are the
evidence that the owner is who they claim to be.

### 5.2 The four states a device can be in, and why the app must distinguish them

The CLI already encodes a distinction the owner must see and today cannot:

| state | meaning | verb |
|---|---|---|
| **known** | in the local list | `add` / `add-remote` |
| **enrolled** | the hub treats it as authoritative for assurance | `enroll` |
| **consenting** | *that device has agreed to act as a factor for this owner* | `serve-owner` |
| **revoked** | no longer contributes, immediately | `revoke` |

**The third is the subtle one, and the CLI says why:** *"Confirming a hub pairing does NOT imply it
— a pair is transport, and being someone's second factor is a separate grant."*

> **R2 — consent to be a factor is a distinct, device-side, explicit act, and the app must render it
> as one.** It happens on the device being added, not on the device doing the adding. Collapsing it
> into "pair" would manufacture consent the owner never gave on the device that gave it — the exact
> class this fleet keeps finding, in the surface most likely to feel like a formality.

### 5.3 Requirements

- **R3 — adding a device is a guided pairing** (`PRD.md` §5.4), and the app states plainly which key
  custody model is in use: `add` holds a key locally (test custody), `add-remote` stores **no**
  private key and routes co-signs to the peer. These are different security postures with the same
  outcome on screen; the owner must be able to tell which they have.
- **R4 — the tier is the visible payoff.** Adding and enrolling a device should visibly change the
  owner's assurance tier, and the app should show what the next tier requires. Otherwise device
  management is chores with no legible reward.
- **R5 — revocation is one action, immediate, and reachable while panicking.** The scenario is a lost
  phone. It must be reachable from another device without navigating a hierarchy, and it must
  confirm the effect ("this device can no longer act for you") rather than the mechanism.
- **R6 — version skew is surfaced, not silent** (`PRD.md` §11 open question). A mixed-version
  constellation is normal; the app says which devices are behind and what that costs.

---

## 6. Hub discovery — dp's open question, with a recommendation

**What exists today is resolution, not discovery.** `hub connect` reads
`.well-known/web4-hub.json` — which tells you about a hub **whose URL you already have.** Nothing
answers *"what hubs exist that I might want?"*

### 6.1 Options, with the trade named

| # | mechanism | gets you | costs |
|---|---|---|---|
| **A** | **Invitation-first** — URL, QR, or code from a human | works today; correct for private hubs; zero infrastructure | no browsing; discovery is entirely social |
| **B** | **Registry hub** — a directory listing public hubs | familiar, browsable | a central index is a trust root and a chokepoint; contradicts local-first |
| **C** | **Federated gossip** — hubs you have joined advertise hubs they federate with | discovery rides **existing trust**; no new root; naturally MRH-scoped | only reaches your neighbourhood; cold start needs A |
| **D** | **Local network (mDNS/DNS-SD)** | "the hub in this building"; excellent for constellation | LAN only |
| **E** | **DNS** — `_web4hub._tcp` SRV under a domain | uses existing infrastructure; organisation-friendly | needs DNS control; not for individuals |

### 6.2 Recommendation: **A + C, with D for devices; defer B**

**Ship A.** It works now, it is right for private hubs, and QR/deep-link makes it excellent on
mobile.

**Then C, because it is the web4-native answer.** A federated hub already knows its peers. Letting
the owner see *"hubs the communities you already trust also federate with"* makes discovery a
function of relationships the owner has, rather than a global index someone curates. It reuses the
MRH the model already has, and it degrades gracefully: no peers means no suggestions, which is honest
rather than empty.

**Use D for the constellation, not for hubs** — "find my other devices on this network" is a real
problem that mDNS solves well.

**Defer B, and say why:** a public directory is the one option that creates a new trust root and a
new thing to attack, and `PRD.md` §4.3 is explicit that the hub is *"something you reach, not
something you depend on."* If a directory is wanted later, it should be **a hub that publishes a
list** — subject to the same law and evidence as any other hub — not privileged infrastructure.

> **R7 — discovery never confers trust.** A discovered hub is a *candidate*. Joining is a separate,
> explicit act with its own evidence (§7). The app must not let "I found it" read as "it is safe."

**Open for reviewers:** whether C needs a hub-side API that does not exist yet (likely), and whether
a hub should be able to *opt out* of being advertised by its peers (probably yes — an unlisted hub
is a legitimate configuration).

---

## 7. Hub join

`hub join` exists: it provisions a member identity in the vault, signs a join request, submits it,
and the hub pins the pubkey. The app exposes none of it.

- **R8 — joining is one guided flow** ending in a plain-language result: you are a member, this is
  your role, this is what you can do here. Key provisioning, signing, and pinning are automatic and
  invisible (`PRD.md` §5.2).
- **R9 — pending is a first-class state.** On this fleet, hub law's `Decision::Escalate` has admitted
  *every* non-trivial join (`PRD.md` §4.5). So "waiting for a human over there" is the normal case,
  not an error, and must be shown as progress with an honest expectation — not a spinner and not a
  failure.
- **R10 — leaving is as reachable as joining**, and states what remains: the chain records the
  membership; disconnecting is local.
- **R11 — the app never invents the outcome.** If the hub has not ruled, the app says so. (`PRD.md`
  §4.5: evidence, not verdict.)

---

## 8. Rendering a decision — the escalation-fatigue answer

`PRD.md` §11 calls owner-facing rendering *"mechanism exists, owner-facing rendering owed."* This is
where R0 is won or lost, and §3 shows the failure mode is already live.

- **R12 — the app must reduce the number of decisions, not just present them better.** The volume
  driver is measured: **87%** of escalations came from one member, ~30% from a payload-scanner
  false-positive class. An app that renders 40 prompts beautifully has still produced a person who
  clicks yes.
- **R13 — every decision states what it authorises, in the terms of the act.** Per decision 0013, a
  grant re-evaluates one recorded act — so the app shows *that act*, not a marker. dp saw a panel
  approving "a write to a hooks path" whose actual target was a markdown file in `/tmp`; the panel
  and the join key disagreed. **The rendered subject and the authorised subject must be the same
  object.**
- **R14 — a decision with no attributable agent is not offered.** Decision 0013 §4: unattributed acts
  are not appealable, because there is no agent to hand the result to. Do not render an approval that
  cannot be delivered.
- **R15 — recurrence is visible.** If the owner has approved this shape before, say so and offer the
  durable fix. Under 0013 the durable fix is a rule change, and appeal → fix rule → grant →
  re-evaluate is the flow the app should teach.

---

## 8.5 Visual identity — one brand, currently forked

dp, 2026-08-08: *"make sure app uses the hestia logo and font (same as dashboard) and is visually
consistent with dashboard."*

**Measured before writing, and the measurement inverts the instruction's direction.** The two
surfaces are not two designs. They are **one design, forked** — and the app is the half that is
still correct.

Canonical source: **`4-gov/source/brand/BRAND.md`**, cited in `app/src/styles/global.css:2` and
containing `#2d2d2d`, `#383838`, `#424242`, `#565656`, `#509982`, `Inter`, and the logotype.

| token | dashboard | app | canon (`BRAND.md`) |
|---|---|---|---|
| body text | `--fg: #e8e8e8` | `--text: #e8e8e8` | `#e8e8e8` — agree, **names differ** |
| dim / muted | `--fg-dim: #a8aeac` | `--text-dim: #a8aeac` | `#a8aeac` — agree |
| faint | `--fg-faint: #7b817f` | `--text-muted: #7b817f` | agree |
| warning | `--warning: #facc15` | `--warn: #facc15` | agree |
| accent | `#509982` ✅ | `--hearth: #509982` ✅ *(I read this as absent — see below)* | `#509982` |
| background | `#1b1c1e` ❌ | `#2d2d2d` ✅ | `#2d2d2d` |
| border | `#45484c` ❌ | `#565656` ✅ | `#565656` |
| logo | **none shipped** ❌ | `hestia-mark-white-64.png` ✅ | logotype defined |

**So "make the app match the dashboard" would propagate the dashboard's drift.** The app already
carries the logo and the canonical greys; the dashboard carries the canonical accent and no assets
at all. Neither is complete.

### Requirements

> **Correction, and it argues R17 better than R17 does** (kimi): the app **already carries the
> canonical accent** as `--hearth: #509982` (`global.css:4`). So **five of seven** values agree,
> not four, and only the *name* diverges. I read a renamed token as an absent one — while
> measuring carefully, in the very section arguing that renamed tokens cause drift. **The fork
> eats reviewers too.** That is the case for one source consumed twice, made by this document's
> own mistake rather than by its argument.

- **R16 — both surfaces converge on `BRAND.md`, not on each other.** The dashboard adopts the
  canonical background and border; the app adopts the canonical accent. Consistency is achieved by
  both matching canon, which is also the only version that does not drift again the next time one
  of them is edited alone.
- **R17 — tokens are defined once and consumed twice.** The values already agree on four of seven
  and disagree on three purely because they are maintained in two files under two naming schemes
  (`--fg` vs `--text`, `--warning` vs `--warn`). One generated token source, two consumers. This is
  the same *one core, thin adapters* argument this fleet has been making about gates, applied to
  design — and the fork is evidence for it, since nobody chose the divergence.
- **R18 — the logotype and mark ship with both.** `app/public/brand/` holds
  `hestia-logotype-white-128.png`, `hestia-mark-white-256.png`, `hestia-mark-white-64.png`. The
  dashboard ships as a single `index.html` with no assets; it needs the mark in its header, which
  means either inlining as a data URI or serving a small asset route.
- **R19 — fonts are named identically in both.** Dashboard declares `Inter` + `JetBrains Mono`
  explicitly; the app indirects through `--font` / `--font-mono`. Same stacks, one declaration.
- **R20 — the app never looks like a different product.** A user moving between the local dashboard
  and the app should not be able to tell they changed applications, only that they changed surfaces.

### Why this belongs in a PRD rather than a style ticket

The fork is a **governance artifact, not an aesthetic one**: two surfaces of one system drifted
because each was edited by whoever was in it, with no shared source and no check. That is precisely
the failure mode this repo has spent the week cataloguing in gates, deployment, and law. Recording
it here so the fix is *one source consumed twice*, rather than a one-time repaint that re-forks the
first time someone edits a colour.

---

## 9. What this PRD does not decide

Named so reviewers can supply what I should not invent:

- **Component library and layout craft.** Not addressed. Deliberate. (Visual *identity* is now
  specified — see §8.5; it turned out to be a convergence requirement, not an open question.)
- **Mirror-mode trust boundary** (`PRD.md` §11) — how a thin client safely relays policy from a
  sovereign node. Architectural, unresolved, and it constrains mobile.
- **~~Whether the app replaces the web dashboard or complements it.~~ PARTLY RULED by 0014:** the app is a *member*, not a presentation layer — it has its own LCT and fills a role, so it is a peer of the daemon rather than a second view of it. What remains open is narrower: whether the app *also* renders the daemon's dashboard (embedded browser), or simply supplies the sovereign session and leaves the dashboard where it is. 0014 §7 takes the second as the first cut. Original framing kept below because the reasoning still applies to the narrower question.
- **(original)** **Whether the app replaces the web dashboard or complements it.** My assessment is that they must
  not diverge — two surfaces with two behaviours is the divergence problem this fleet has fought all
  week — but *which* becomes authoritative is a decision I should not make alone. The honest options
  are: app subsumes the dashboard; dashboard stays the operator/debug surface with the app as the
  consumer surface; or the app renders the dashboard's own API so there is one behaviour and two
  presentations. **I lean to the third**, and I want it argued.
- **Release and packaging ownership** (`PRD.md` §8/§9, §11) — the largest real gap. This PRD assumes
  an artifact can be shipped; nothing here makes that true.
- **Whether hub-side federation APIs exist for §6.2 option C.** Needs a hub-side reader.

---

## 10. Sequencing (proposed, not ratified)

1. **Decide the dashboard/app relationship (§9).** Everything downstream depends on it.
2. **Information architecture (§4)** — three places, salience rule, disclosure depths. Cheap,
   reversible, and it determines whether anything else is reachable.
3. **Constellation (§5)** — highest owner value, capability already in the daemon, zero surface
   today.
4. **Hub join (§7)**, then **discovery A** (§6), then **C**.
5. **Decision rendering (§8)** — continuously, alongside each of the above rather than as a phase.

**Not in this list: build a release pipeline.** It is a precondition for the app mattering at all and
belongs to whoever owns `PRD.md` §8/§9, not to this document.

---

## 11. Review asks

- **kimi** — §5.2's four device states, particularly R2. You have read the constellation code more
  recently than I have; is the `serve-owner` consent boundary as I describe it, and is there a fifth
  state I have missed?
- **codex** (when usage returns) — §6.2 option C: does hub-side federation expose peers today, or is
  that new surface? You did the hub-side audits.
- **legion** — §4 information architecture, as the seat least steeped in this week's context. If the
  three places do not survive a cold read, they will not survive a user.
- **GPT** — §8 against your escalation-as-amendment model. R15's flow is yours; I want to know if the
  app is where it should live.
- **dp** — §9's dashboard/app question is the one I most want ruled before anyone builds.
