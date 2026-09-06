# Network destination binding

**Status:** design requirement / threat-model companion  
**Extends:** [`PRD_ASSURANCE.md`](PRD_ASSURANCE.md) FR-3, [`PRD_FLEET_OPENBOT_EXECUTION_SUBSTRATE.md`](PRD_FLEET_OPENBOT_EXECUTION_SUBSTRATE.md) §§2.1/2.6/4.3  
**Motivating disclosure:** [CVE-2026-85666](https://www.cve.org/CVERecord?id=CVE-2026-85666), OGX <= 1.3.1 MCP `server_url` SSRF

## 1. Requirement

Hestia's portable-decision target already says that a policy decision binds the **exact request** and an **audience**. For networked effectors, this document makes one implication explicit:

> **The destination actually reached by the executor is part of the exact governed act.**

A decision that authorizes "use MCP", "call tool X", "perform HTTP request", or even "contact service Y" is not sufficient if caller-controlled fields can redirect the privileged executor to another network authority after the decision.

This requirement is protocol-neutral. MCP is one motivating example.

---

## 2. Why the distinction matters

CVE-2026-85666 affected OGX's OpenAI-compatible `/v1/responses` MCP path. A caller-supplied `server_url` was consumed by the server-side MCP client without the private-address validation applied to sibling URL inputs. In a default unauthenticated starter deployment, this could make the OGX process connect to loopback/private/link-local/cloud-metadata destinations from its own network position, with caller-supplied header/authorization values.

The direct bug is SSRF. The governance failure shape is a **confused deputy**:

```text
caller/model controls descriptor
        |
        v
policy sees "MCP/tool request"
        |
        v
privileged executor interprets descriptor as destination authority
        |
        v
actual effect occurs against a different resource boundary
```

The mistake is treating the destination as transport detail rather than action semantics.

---

## 3. Canonical act requirements

For governed network effects, the canonical act should carry enough typed information to distinguish the capability from the concrete authority it will exercise.

Candidate fields/semantics:

- mechanism/tool identity;
- effect (`communicate_outward`, `read_data`, `write_data`, etc.);
- logical service/capability identity where known;
- requested target descriptor;
- canonical audience / authority;
- transport scheme;
- credential reference and credential audience where applicable;
- redirect policy;
- destination-resolution policy;
- payload/request digest where binding the exact body matters;
- executor/run identity.

The schema does not need to freeze DNS addresses. It does need to define what constitutes the **same authorized audience** and what constitutes a new target requiring a new decision.

---

## 4. Resolve before policy, verify again at effect

The OpenBot execution-substrate PRD already requires the action boundary to see **resolved state**. Network targets are another instance of that rule.

A high-assurance path is:

```text
request
  -> resolve typed destination/audience
  -> classify effect
  -> Hestia decision bound to target + audience + obligations
  -> executor verifies decision
  -> executor resolves/connects under the authorized resolution policy
  -> actual destination is checked against the decision
  -> effect
  -> witnessed outcome
```

If a redirect, DNS change, proxy rewrite or other runtime event crosses the authorized audience boundary, the old decision is not spendable on the new target.

A relying service/executor that cannot verify this property must advertise a lower assurance profile.

---

## 5. Credential audience is inseparable from destination authority

A credential should not be modeled as a generic bearer object that becomes safe merely because Hestia approved "use credential C."

The governed question is closer to:

> may principal P exercise credential/capability C for operation O against audience A under law L now?

Requirements:

- brokered/presented credentials are audience-bound where the underlying mechanism permits;
- a caller-controlled target cannot rebind a credential to another audience;
- redirects across credential audience fail or require re-authorization;
- raw credential export remains a distinct, higher-consequence act;
- evidence records the intended audience without recording secret material.

This is the network counterpart of the vault doctrine that credentials are capabilities, not strings.

---

## 6. Address classes and resolution hazards

The enforcement layer should explicitly account for:

- loopback;
- private RFC1918 / ULA space;
- link-local addresses;
- cloud metadata services;
- IPv4/IPv6 alternate encodings;
- DNS rebinding / time-of-check-to-time-of-use changes;
- redirects;
- proxies;
- Unix sockets / named pipes or equivalent local transports;
- service-discovery aliases.

This does **not** imply that private/local destinations are globally forbidden. Hestia itself is local-first. It means that reaching a privileged local/private target must be an explicit authority decision rather than an accidental consequence of an arbitrary URL field.

---

## 7. Assurance mapping

### A1 - cooperative gate

The in-process hook may inspect and classify destination metadata, but an agent at the same privilege can potentially bypass the hook and open its own socket. Useful for mistakes; not containment.

### A2 - external enforcement

The executor/relying service accepts a Hestia decision bound to the actual target/audience and refuses target substitution. Removing the agent-side hook does not grant broader network reach through that executor.

### A3+

OS/container/network topology additionally prevents the cognitive process from routing around the broker/executor with ambient network authority.

This document therefore reinforces rather than changes the existing assurance vocabulary.

---

## 8. Conformance / red-team cases

At minimum:

1. MCP/tool request swaps `server_url` after authorization;
2. public hostname resolves directly to loopback/private/link-local target;
3. approved public target redirects to private target;
4. DNS answer changes between policy evaluation and connect;
5. credential approved for audience A is presented to B;
6. alternate IPv4/IPv6 representation reaches a forbidden class;
7. proxy configuration causes the executor to reach a different authority;
8. a valid Hub/service descriptor names a malicious target;
9. executor reports an actual destination inconsistent with the decision.

For A2, the expected property is:

> **the executor cannot turn one approved destination into a different destination without a new valid decision.**

---

## 9. Relation to Hub and SAGE

- **SAGE** should resolve being-local capability requests into typed destination-bearing acts before handing consequential external effects to Hestia.
- **Hub** may carry provenance-bearing service/endpoint descriptors, but discovery or valid authorship does not create connection authority.
- **Hestia** binds identity/role/delegation/law to the resolved act.
- **The executor/relying party** is where A2 becomes real: it verifies the decision against what it will actually contact.

No layer should silently widen another layer's authority through transport metadata.
