# GUI update verification — v0.2.2

Verified on Linux with Python 3.12 and headless Chromium.

- **60 Python tests passed**, including the original 48, 8 GUI HTTP /
  orchestration integration tests, 2 citation correction tests, and 2 schema correction tests. Result summary: `test-results.txt`.
- **Real-browser end-to-end check passed**, from project creation through every
  required approval to iteration closure. It exercised A/B code views, a failing
  Unicode candidate, modification and renewed evaluation permission, successful
  retesting, task/artefact/activity views, test sign-off, deployment deferral,
  stakeholder notes, source ZIP download, and settings save.
- Desktop screenshots inspected; 390px mobile layout has no document overflow.
- No browser JavaScript errors were reported. JavaScript syntax checks passed.
- Wheel build succeeded and contains the HTML/CSS/JS and demo fixture module.
- Agent evidence prompts now list the exact available artifact and pattern IDs. One model regeneration is allowed for an invalid citation; a second invalid citation remains blocked. A controlled provider test verifies both outcomes.
- A controlled implementation-agent test verifies that misplaced top-level source paths are regenerated inside `files`, and persistent malformed output is rejected. Both schema and evidence mistakes can receive one correction attempt, with at most three calls total.
- No live LLM call or actual deployment was performed. Native Windows/macOS
  launcher execution was not tested in this Linux environment.

New integration coverage includes session/Host/Origin checks, cross-project
artifact rejection, exact stale-gate rejection, failed-candidate acceptance
blocking, information requests that retain the gate, full exports, persistent
resume, demo/live separation, in-memory keys, invalid-config rollback, duplicate
job rejection, settings changes blocked during work, rejection, source rework,
failed-operation recovery, and iteration rollover with artifact history intact.

Reproduce the browser check with `tests/gui_browser.cjs`; see `GUI.md`.

---

## Original prototype verification (retained)

# Verification record

Build environment: Python 3.12.14, Linux. Verification performed 2026-10-08 UTC.

```text
python3 -m unittest discover -s tests -v
Ran 48 tests in 5.006s
OK
```

The captured per-test log is `test-results.txt`. Tests exercise real workflow
transitions and persistent SQLite records. Scripted providers are confined to
the test/demo code; the live application has no fixture provider/runner setting.

## Verified behavior

| Area | Evidence exercised |
|---|---|
| Source sequence | Complete lifecycle, exact 11 testing stages, two development checkpoints, evaluation before reviews, final choice before merge |
| Requirements | Stakeholder questions; reject → Collector; revised model; exact accepted requirements in structured SRS |
| Design | Query → real catalog observations → alternatives; repeated refinement returns through the direction checkpoint; human-selected ADR overrides agent recommendation |
| Human authority | Invalid credential, stale digest, resolved-gate replay, missing evaluation permission, pending-gate blocking, model self-approval fields |
| More information | Explanation saved without state advance; explanation failure leaves the checkpoint pending |
| Development independence | A/B strategy prompts differ; B cannot see A's private plan/code; reviewers each receive both implementations but never the other report |
| Evidence | Real failing/passing candidate tests, source diff, no score field, unknown evidence IDs rejected, source/test path restrictions |
| Final choice/rework | Failed candidate cannot merge; modification reruns both implementations and both reviewers; source merge records correct parent |
| Testing permissions | No execution before approval; exactly-once grant consumption; substituted source, substituted recipe and nonexistent decision rejected |
| Testing interventions | Low confidence, strategy/environment flags, repeated failures, environment drift after approval, and mandatory final verification |
| Testing feedback | Action log → proposal → new policy gate; raw outputs preserved; static-only evidence cannot complete; checks can accumulate for one immutable bundle |
| Persistence/recovery | Pending gate and credential survive reopen; agent failure resumes; concurrent claims denied; resolved gate proposals retained in exports; expired interrupted evaluations/actions require renewed human review |
| Deployment | Deployment tool denied even with an approval attempt; manual/deferred records produce no runner call |
| Stakeholder review | Human demonstration notes and feedback start requirements iteration 2 with the existing accepted baseline |
| HTTP integration | Actual loopback HTTP requests, per-role model routing, JSON request mode, credential header separation, malformed/truncated output, safe error reporting, remote HTTP/credential URL rejection |
| Runner controls | Missing Docker fails closed; launch arguments enforce fixed isolation; unpinned images and unknown tools rejected; output/time limits exercised on harmless fixed subprocesses |
| Human interface | CLI initialization, project creation/listing and private credential handling; interactive console inspect/reject/resume path; terminal control bytes removed |

## End-to-end demo results

`python3 -m examples.demo --out my-demo` executes the actual engine from
stakeholder input through stakeholder review. Five real known-fixture executions:

| Round | Candidate / phase | Tests | Result |
|---|---|---:|---|
| Development 1 | A: split/join | 6 | Pass |
| Development 1 | B: ASCII-only regex | 6 | Fail: Unicode separator case |
| Development 2, human-requested correction | A | 6 | Pass |
| Development 2, human-requested correction | B: Unicode-aware regex | 6 | Pass |
| Testing after human merge selection | A plus independent invariants | 8 | Pass |

All five also run syntax/static checks. The demo audit includes the initial
failure, both reviewer versions, human modification instructions, every policy
decision, raw unittest output, final verification, and explicit deployment
deferral. No real stakeholder statements or human approvals are claimed for
this scripted demonstration.

## Not verified in this environment

- External/paid LLM behavior or model quality: no external API credentials were
  used. The transport is tested, but a selected provider/model must be validated
  in the user's environment.
- A live Docker container: Docker is unavailable here and alternative namespace
  creation is prohibited. Sandbox invocation is inspected by tests; the demo
  only executes exact known fixtures. No untrusted generated code was run on
  the host as a fallback.
- Real deployment, external Git/CI integration, multi-user identity, empirical
  productivity gains or human comprehension. These are outside prototype scope.

Passing tests substantiate the listed scenarios, not a proof that every possible
workflow, provider response, malicious program or host configuration is safe.
