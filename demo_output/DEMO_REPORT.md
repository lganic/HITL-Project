# End-to-end demonstration

This is a deterministic demonstration of the real engine. **Agent responses and
human decisions are scripted and explicitly labelled.** Actual Python source is
tested by the exact-fixture runner. No paid/external LLM was invoked and nothing
was deployed. The live application uses a configurable HTTP LLM provider and
requires Docker to execute generated code.

Task: implement Unicode-aware `normalize_whitespace(text)` with strict type
validation. Candidate A uses split/join. Candidate B initially uses an ASCII-only
regex, fails a Unicode test, and is corrected to a Unicode-aware regex after the
human modification checkpoint. Both reviewers receive raw failures; neither
chooses or merges a candidate.

The run demonstrates requirements rejection, a pending-gate explanation,
architectural refinement and its feedback arrow, two development rounds,
independent reports, policy-gate rejection/re-proposal, all 11 testing stages,
manual deployment deferral, and stakeholder review closure.

## Measured executions

| Evidence | Unit tests | Result | Artifact |
|---|---:|---|---|
| evidence_a v1 | 6 | PASS | art_18c1ea3d2deb4e50b9e8 |
| evidence_b v1 | 6 | FAIL | art_9610812c3e3748819e4b |
| evidence_a v2 | 6 | PASS | art_3e086ce2272b464a951f |
| evidence_b v2 | 6 | PASS | art_40fed2d2d7f74ea6a457 |
| test_result v1 | 8 | PASS | art_e2b84a4dbdf54ae289e5 |

`accepted_source/` contains the merged implementation and locked acceptance
tests; `tested_source/` adds the independent testing suite. `audit.json` includes
full raw outputs, all artifact versions, proposals, decisions and execution
authorization records. No human key or API credential is included.

## Recorded workflow trace

| Event | State | Event type | Next state |
|---:|---|---|---|
| 3 | req.collect | step_completed | req.model |
| 5 | req.model | step_completed | req.check |
| 7 | req.check | human_decision | req.collect |
| 9 | req.collect | step_completed | req.model |
| 11 | req.model | step_completed | req.check |
| 13 | req.check | information_requested |  |
| 14 | req.check | human_decision | req.document |
| 16 | req.document | step_completed | design.explore |
| 18 | design.explore | step_completed | design.direction |
| 20 | design.direction | human_decision | design.refine |
| 22 | design.refine | step_completed | design.decision |
| 24 | design.decision | human_decision | design.refine |
| 26 | design.refine | step_completed | design.direction |
| 28 | design.direction | human_decision | design.decision |
| 30 | design.decision | human_decision | design.record |
| 32 | design.record | step_completed | dev.plan_a |
| 34 | dev.plan_a | step_completed | dev.plan_b |
| 36 | dev.plan_b | step_completed | dev.plan_review |
| 38 | dev.plan_review | human_decision | dev.implement_a |
| 40 | dev.implement_a | step_completed | dev.implement_b |
| 42 | dev.implement_b | step_completed | dev.evaluate |
| 46 | dev.evaluate | step_completed | dev.review_a |
| 48 | dev.review_a | step_completed | dev.review_b |
| 50 | dev.review_b | step_completed | dev.final |
| 52 | dev.final | human_decision | dev.implement_a |
| 54 | dev.implement_a | step_completed | dev.implement_b |
| 56 | dev.implement_b | step_completed | dev.evaluate |
| 60 | dev.evaluate | step_completed | dev.review_a |
| 62 | dev.review_a | step_completed | dev.review_b |
| 64 | dev.review_b | step_completed | dev.final |
| 66 | dev.final | human_decision | dev.merge |
| 68 | dev.merge | step_completed | test.context |
| 70 | test.context | step_completed | test.prepare |
| 72 | test.prepare | step_completed | test.plan_review |
| 74 | test.plan_review | human_decision | test.propose |
| 76 | test.propose | step_completed | test.policy |
| 78 | test.policy | human_decision | test.propose |
| 80 | test.propose | step_completed | test.policy |
| 82 | test.policy | human_decision | test.execute |
| 85 | test.execute | step_completed | test.summarize |
| 87 | test.summarize | step_completed | test.log |
| 89 | test.log | step_completed | test.completion |
| 91 | test.completion | step_completed | test.verify |
| 93 | test.verify | human_decision | test.done |
| 95 | test.done | step_completed | deploy.assist |
| 97 | deploy.assist | step_completed | deploy.manual |
| 99 | deploy.manual | human_decision | review.prepare |
| 101 | review.prepare | step_completed | review.feedback |
| 103 | review.feedback | human_decision | review.closed |
