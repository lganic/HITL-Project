# Formal process model

Source: *CSE 5695 Project Source List.pdf*, five pages, supplied with this task.
All pages were read as text and rendered; the requirements and testing figures
were additionally inspected at enlarged resolution. Page numbers below are PDF
page numbers. The dated revision on pp. 4–5 overrides the original development
description on pp. 2–3. The old 1–3 scoring mechanism is intentionally absent.

## Notation and global invariants

States prefixed `req`, `design`, `dev`, `test`, `deploy`, and `review` belong to
distinct workflows. A **gate** suspends ordinary execution until a human records
a decision. Every artifact is immutable, versioned, and content hashed. Gates
refer to specific artifact IDs, not mutable filenames. Each decision records
the human identity, feedback, selected alternative, gate ID, proposal digest,
timestamp, and resulting transition.

1. An agent can propose data, never authorize a transition or invoke a tool.
2. No ordinary step is permitted while a gate is pending.
3. Only the human control interface has the approval credential.
4. Approval applies only to the displayed proposal/scope. Changed proposals,
   code, commands, or environments require appropriate renewed review.
5. `info` requests an explanation while leaving the gate pending.
6. Rejection/modification invalidate downstream authorization. Stages replace
   current artifact references when they regenerate work; historical artifacts
   remain in the audit record and cannot authorize later transitions.
7. Failures stop the workflow. Recovery is explicit; an interrupted tool action
   is treated as uncertain and requires renewed human authorization.
8. No deployment tool exists. A deployment record describes a human's action;
   it cannot initiate one.

## Requirements — p. 1 figure, p. 2 continuation

| State | Responsibility and output | Next / branch |
|---|---|---|
| `req.collect` | AI Collector organizes stakeholder needs, asks questions, drafts prioritized requirements and acceptance criteria | Questions → `req.clarify`; otherwise `req.model` |
| `req.clarify` **gate** | Human stakeholder supplies answers, priorities, and missing information | Approve/modify/reject with feedback → `req.collect` |
| `req.model` | AI Modeler derives entities, relationships, constraints, and a requirements model | `req.check` |
| `req.check` **gate** | Human Checker assesses correctness, completeness, consistency, missing assumptions, and need to ask the stakeholder again | Approve → `req.document`; reject/modify → `req.collect` |
| `req.document` | AI Documenter supplies explanatory prose; engine embeds the exact human-approved model in a structured SRS | `design.explore` |

The diagram's “revise” arrow goes from Human Checker to AI agents/iterate and
back to Collector. There is also a horizontal iterate-to-Documenter arrow.
**Resolution A1:** that arrow cannot authorize an unreviewed SRS. Revised work
must pass the Checker again. This follows the surrounding text and the user's
explicit acceptance requirement. Collector clarification is a practical
implementation of the figure's stakeholder questions, not a new AI checker.

## Design — p. 2 figure

| State | Responsibility and output | Next / branch |
|---|---|---|
| `design.explore` | Approved SRS supplied by the human's requirements decision. AI chooses search queries, observes a read-only architecture catalog, compares at least two alternatives | `design.direction` |
| `design.direction` **gate** | Human selects/corrects the architectural direction | Approve → `design.refine`; reject → `design.explore`; modify → `design.refine` |
| `design.refine` | AI incorporates human feedback and evaluates tradeoffs | Normally `design.decision`; on a requested feedback loop → `design.direction` |
| `design.decision` **gate** | Human makes the architectural decision, choosing a specific alternative and recording reasons | Approve → `design.record`; reject/modify → `design.refine`, then `design.direction` |
| `design.record` | Engine writes ADR from selected refined option, human reasons, consequences, alternatives, and supporting artifacts | `dev.plan_a` |

The blue feedback arrow from refinement back to the checkpoint is preserved.
On a loop, acceptance of the already-refined direction goes to the final human
decision. An agent recommendation never chooses the ADR outcome. The catalog
search is a bounded ReAct-inspired action/observation/refinement process, not a
claim to reproduce LATS or its experimental results.

## Development — revised pp. 4–5

| State | Responsibility and output | Next / branch |
|---|---|---|
| `dev.plan_a` | Agent A independently proposes a plan and acceptance tests | `dev.plan_b` |
| `dev.plan_b` | Agent B proposes a plan without seeing A's proposal | `dev.plan_review` |
| `dev.plan_review` **checkpoint 1** | Human selects A/B or a corrected custom approach; reviews both test suites and explicitly authorizes bounded evaluation in the configured sandbox | Approve → `dev.implement_a`; reject/modify → `dev.plan_a` |
| `dev.implement_a` | Agent A implements against frozen baseline, approved approach, own plan, and fixed acceptance tests | `dev.implement_b` |
| `dev.implement_b` | Agent B implements against the same baseline without A's implementation or private conversation | `dev.evaluate` |
| `dev.evaluate` | Automated tests and static analysis evaluate both immutable candidate trees | `dev.review_a` |
| `dev.review_a` | Reviewer A compares both candidates and raw evidence | `dev.review_b` |
| `dev.review_b` | Reviewer B independently compares both; does not see Reviewer A's report | `dev.final` |
| `dev.final` **checkpoint 2** | Human inspects differences, failures, risks, tradeoffs, raw evidence, and source diff | Approve specific candidate → `dev.merge`; modify → both implementations again; reject/change approach → `dev.plan_a` |
| `dev.merge` | Validate selected candidate, test evidence, baseline version, and exact human decision; atomically merge the selected tree into the canonical project snapshot | `test.context` |

**Resolution A2:** checkpoint 1 includes permission for the fixed test/static
recipes on generated candidate trees, with no network or host execution. It is
a bounded scope grant, not permission for arbitrary commands. Checkpoint 2's
`modify` explicitly renews that same scope for a corrected implementation round.
Changing the runner environment sends work to checkpoint 1 again. This keeps
the specified two human checkpoints while enforcing pre-execution permission.

**Resolution A3:** only candidates with successful observed automated checks can
be merged in this prototype. Failures remain visible; there is no unsafe
override. Fixing code repeats evaluation and both independent reviews.

## Testing — p. 3, all 11 numbered stages

| # | Figure label / state | Behavior and branches |
|---|---|---|
| 1 | Repository / Project Context — `test.context` | Capture canonical source, README/CI artifacts if present, SRS, ADR, and configured environment |
| 2 | AI Preparation — `test.prepare` | Gather context; draft objective, constraints, assumptions, test plan, and additional test files |
| 3 | Human Plan Review — `test.plan_review` **gate** | Approve objective and tests → 4; reject/modify → 2. An intervention on a proposed action returns here; approve that reviewed action → 5 |
| 4 | LLM Proposes Next Action — `test.propose` | Store typed command recipe, why, expected result, side effects, confidence, and environment binding; normally → 5; intervention → 3 |
| 5 | Human / Policy Gate — `test.policy` **gate** | Both policy AND human approval required. Approve allowed exact action → 6; reject/modify → 4; info → explanation, remain at 5 |
| 6 | Execute Command — `test.execute` | Run approved recipe in controlled environment; journal execution before starting; retain raw outputs → 7 |
| 7 | AI Summarizes Results — `test.summarize` | Explain outcomes without replacing raw evidence → 8 |
| 8 | Human-Visible Action Log — `test.log` | Record action, approval, raw output, explanations, and results. Continue → 4; repeated failure/low confidence/change → 3; supported completion request → 9 |
| 9 | AI Requests Completion — `test.completion` | AI assembles evidence-based completion request; cannot sign off → 10 |
| 10 | Human Verification & Sign-off — `test.verify` **gate** | Human confirms success using raw evidence. Approve → 11; reject/modify → 2 |
| 11 | DONE — `test.done` | Record testing completion → `deploy.assist` |

The right-hand loop is **8 → 4**, “iterate until success.” It is not a shortcut
around stage 5. The intervention annotations are implemented as follows:

| Annotation | Prototype interpretation (A4) |
|---|---|
| Repeated failure | Two consecutive failed actions → human plan review |
| Low confidence | Agent confidence < 0.70 → human plan review; explicitly visible |
| Major strategy change | Proposal flag → human plan review; rejected policy action is re-proposed |
| Environment/toolchain change | Runner fingerprint drift or proposal flag → human plan review; stale grants cannot execute |
| Completion request | Always requires stage 10; successful tests alone cannot finish |

Thresholds are implementation assumptions; the source does not give numbers.
Final verification requires successful **test and static-analysis evidence for
the current bundle**, not an agent's assertion of success. Tests cannot edit
production code. Needed source changes route through development by explicit
human rework, invalidating testing approvals.

## Deployment — p. 3

`deploy.assist` → `deploy.manual` **human gate** → `review.prepare`.
The assistant provides technical instructions, explanations, validation and
rollback considerations as text. The human records a manual deployment or an
explicit decision to defer deployment. Reject/modify → assistance again. No
shell, provider tool, or workflow transition deploys the project. Deferred
deployment is recorded as deferred, never as deployed (A5).

## Review — pp. 3–4 and p. 1 agile cycle

`review.prepare` drafts demonstration steps and stakeholder questions.
`review.feedback` **human gate** records the demonstration, stakeholder feedback,
and new needs. New requirements start a new iteration at `req.collect`, retaining
the accepted source baseline and previous decisions. Human may close the
iteration at `review.closed` when no new work is requested. Reject/modify returns
to demonstration preparation. Stakeholder responses are human input, not AI
fabrications. Each iteration traverses its own approvals (A6).

## Failure, interruption, and concurrency semantics

Each nonhuman state has `ready`, `running`, or `failed` execution status. A claim
with an expiring lease prevents concurrent ordinary steps. Agent errors,
malformed JSON, invalid artifacts, and disallowed paths fail closed at the same
state. Human recovery retries the failed state with existing upstream artifacts.
An expired running lease allows explicit recovery after interruption. Unknown
testing executions return to stage 5 for a new grant; unknown development
evaluations return to checkpoint 1. Merges and state/artifact commits are atomic
SQLite transactions. More-information calls leave gates pending even on failure.

## Source traceability

| ID | Source evidence | Implementation responsibility | Verification |
|---|---|---|---|
| AG-01 | p. 1 agile ring: requirements/design/develop/test/deploy/review | Workflow dispatch, iteration baseline, review-to-requirements | Full lifecycle and second iteration tests |
| HUM-01 | p. 1 prose: humans review/tweak before next step | Human credential, immutable gate proposals, pending-state guard | Bypass, stale decision, and pending gate tests |
| REQ-01 | p. 1 requirements figure, stakeholder/Collector/Modeler | Collector, clarification, Modeler roles | Requirements ordering and clarification tests |
| REQ-02 | p. 1 Checker revise/accept arrows, p. 2 continuation | Checker gate; rejection to Collector; exact approved SRS model | Rejection and SRS integrity tests |
| DES-01 | p. 2 human requirements → exploration/ReAct-LATS | Approved SRS + bounded query/observation/catalog exploration | Search observations and alternative validation |
| DES-02 | p. 2 checkpoint/refinement/feedback/decision/ADR | Separate direction and decision gates; feedback loop; human-selected ADR | Design rejection/refinement and ADR tests |
| DEV-01 | pp. 4–5 early checkpoint revision | Independent plans + checkpoint 1 before code generation | No implementation before approval |
| DEV-02 | p. 5 two independent implementations | Distinct strategies; frozen contexts; separate candidate snapshots | Context isolation and distinct-source tests |
| DEV-03 | p. 5 tests/static analysis before review | Fixed policy-controlled runner; observed evidence | Sequence and execution-authorization tests |
| DEV-04 | pp. 4–5 evidence, differences, failures, risks, tradeoffs | Independent comparison reports; structured evidence references; no score fields | Reviewer isolation, schema, and evidence tests |
| DEV-05 | p. 5 final checkpoint → merge | Human selection + immutable passing candidate → canonical version | No early/stale/failed merge; rework tests |
| TST-01 | p. 3 testing figure stages 1–3 | Context, plan, human plan gate | Exact 11-stage sequence |
| TST-02 | p. 3 stages 4–6 | Typed proposal, policy + human gate, controlled execution | Denied tools, stale scope, no execution before grant |
| TST-03 | p. 3 stages 7–8, blue loop 8→4 | Summary + persistent raw logs + iteration | Failed action loop and log preservation |
| TST-04 | p. 3 stages 9–11 | Completion request, human verification, DONE | Completion cannot self-approve |
| TST-05 | p. 3 red intervention annotation | Failure/confidence/strategy/environment/completion interventions | Intervention and environment-drift tests |
| DEP-01 | p. 3 deployment prose | Assistance only; human attestation/defer; no deploy tool | Deployment denial and no runner call |
| REV-01 | pp. 3–4 review prose | Demos, actual human feedback, next-iteration requirements | Feedback-to-Collector lifecycle test |
| IMP-01 | User requirements (not specified in PDF) | Persistent SQLite state, configurable providers, interactive CLI, recovery | Restart, provider protocol, CLI, concurrency tests |

The executable state registry is `hitl_se/workflows.py`. This document defines
the interpretation; tests exercise the actual engine rather than only comparing
the registry against itself.

Source document SHA-256: `b8f47c2f2bbea2c77312d78feda4654ca49ecece18070a2b189a30b827b5ed3e`.
