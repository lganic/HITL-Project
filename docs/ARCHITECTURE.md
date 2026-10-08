# Architecture and decisions

## Scope chosen before implementation

This is a local, single-owner research prototype for small Python tasks. It has
six distinct workflows and an interactive terminal control room. It produces
real source trees, structured SRS/ADR artifacts, test evidence, approvals, and
versioned merges. It supports real configurable LLM requests. It does not provide
multi-tenant authentication, remote deployment, or an autonomous shell.

| Module | Responsibility |
|---|---|
| `workflows.py` | Explicit state registry, gate metadata and rejection destinations |
| `engine.py` | Phase orchestration, bounded contexts, invariants, retries and iteration |
| `store.py` | SQLite transactions, leases, immutable artifacts, human decisions, action journal and event log |
| `agents.py`, `schemas.py` | Stateless role prompts, distinct strategies, typed validated results, evidence reference validation |
| `providers.py`, `config.py` | OpenAI-compatible HTTP provider, per-role model/provider routing, timeouts, response-size limits, no credential logging |
| `policy.py`, `runner.py` | Deny-by-default recipes, exact execution scopes, sandbox checks and output preservation |
| `cli.py` | Local human authentication, inspect/compare/decide, interactive console, exports and recovery |
| `examples/` | Explicitly labelled scripted-agent demo; no automatic-approval mode in the application |

## Extension interfaces

| Interface | Contract |
|---|---|
| `provider.complete(role, messages, schema)` | Return `(JSON result, provider metadata)`; no tools or state authority |
| `Agents.run(role, context)` | Validate the strict role schema, filenames and evidence references; attach invocation provenance |
| `Engine.step(project)` / `Engine.run(project)` | Execute one automatic state / stop at the next human gate |
| `Engine.decide(project, gate_id, digest, action, feedback, payload, actor, token)` | Authenticate human authority and validate the exact pending proposal before transitioning |
| `runner.fingerprint()` | Identify configured execution environment and trusted harness |
| `runner.run(files, tool, execution_id)` | Execute a broker-authorized fixed recipe; return bounded stdout/stderr, exit status and measured checks |
| `runner.cancel(execution_id)` | Stop the exact uncertain execution before recovery opens another approval gate |
| `Engine.export(project)` | Return auditable project/artifact/decision/event/execution records, excluding control credentials |

The engine and broker are the trusted boundary. Custom in-process adapters
must be reviewed code, never scripts supplied by a model.

## Data flow and trust boundaries

The engine constructs allowlisted role contexts from immutable artifacts. A
provider receives only that context and a role schema. Agent results are data:
they cannot call the engine, access the approval credential, write to the
database, mutate main, or execute commands. The engine validates schemas,
filenames, referenced evidence, and preconditions before committing results.

Humans interact with the control interface. A locally generated capability file
(owner read/write only) authenticates control operations; its hash is in SQLite.
Agents and sandboxed candidate processes never receive the capability file,
database, host environment, or provider credentials. This is separation from
untrusted model output, not protection against the machine's owner editing the
program/database. Deploy behind an authenticated service before multi-user use.

Every gate presents proposal, rationale, artifact evidence, risks, alternatives,
and available actions. `approve`, `reject`, `modify`, and `info` have distinct
semantics. `info` creates an explanation without advancing. No default answer
means approval. An exact gate ID and digest are required on decision submission.

## Persistence and versioning

SQLite (stdlib) is the durable source of truth. A project has an iteration,
state, status, revision, working references, canonical source version, and
lease. Artifacts contain JSON payloads, content hashes, producer and version.
Gate and decision rows preserve review context. An append-only event log records
the actual ordering. Execution rows record authorization, input hashes,
timestamps, status, stdout/stderr and exit status.

Each successful state commit atomically adds its artifacts, updates the project,
and appends events. A running claim is committed before external work. Recovery
of an uncertain command requires another human gate rather than replaying a
possibly already-executed operation. Checkpoint records survive process exit.
Leases serialize a project; different projects can proceed independently.

**A7: snapshot merging.** Candidates are independent immutable copies of one
baseline. A merge checks that the canonical baseline has not moved, records the
selected complete tree and parent hash, and advances main in one transaction.
It is an actual local source merge with exportable files, but not a GitHub PR or
Git merge. A Git adapter is future work; no outside repository is changed.

## Independent generation and review

Planning and implementation A emphasize a minimal contract-driven solution; B
emphasizes boundary cases and an alternative decomposition. Requests are fresh,
stateless conversations; B cannot see A's private plan or candidate. Both see
the human-approved common approach and fixed acceptance contract. Each sees its
own plan and code when revising. Distinct configured models/providers can be
used for A/B and each reviewer. Context hashes and routing are recorded.

Reviewers receive both candidates and the same measured evidence, but neither
receives the other's report. One emphasizes correctness and requirement
coverage; the other operational risk and maintainability. Reports contain
claims with artifact references and separate differences, failures, risks and
tradeoffs. Numerical recommendation scores are rejected by the schema.

This establishes information isolation and different strategies, **not
statistical independence**. Shared training data/models can produce correlated
errors. Human review and common tests remain necessary.

## LLM provider and bounded architecture exploration

The default application path is a real HTTP provider; there is no silent demo
fallback. Provider configuration contains base URL, model, key environment
variable name, timeout, optional JSON response mode, and per-role overrides.
HTTP is allowed only for loopback local-model servers; remote endpoints require
HTTPS. Credentials are environment inputs and omitted from artifacts/logs.
Redirects are disabled. Invalid output fails closed and is explicitly retried.

Architecture exploration first asks an agent for queries, executes bounded
read-only searches over the bundled pattern catalog, then asks it to compare
alternatives using the observations. Refinement consumes human feedback and
the same evidence. This intentionally implements a small action/observation
loop rather than a large agent framework or unrestricted web search.

References used for implementation: [ReAct authors' project](https://react-lm.github.io/),
[Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
[Docker run](https://docs.docker.com/engine/containers/run/).
The proposal's cited papers were not substituted for its modified diagrams.

## Tool permissions and execution

Only fixed `static_analysis`, `python_tests`, and combined `python_checks`
recipes exist. No agent-provided command strings, shell expansions, dependency
installation, network use, deployment, or filesystem mounts are accepted.
The human reviews exact recipe, artifact scope and sandbox configuration.
Static analysis is Python syntax plus a deliberately small risk scanner,
not a claim of a complete type checker or vulnerability analyzer.

Live execution uses a preinstalled, digest-pinned Docker image with a read-only
source mount and root filesystem, network disabled, dropped capabilities,
no-new-privileges, non-root UID, memory/CPU/PID limits, bounded time and output.
No database, credential, Git metadata, or host environment is mounted. The tool
broker checks human permission immediately before launch. Changed sandbox
fingerprints invalidate scope. A missing sandbox stops execution; it never
falls back to running model-generated Python on the host.

**A8: reproducible demonstration.** This environment has no Docker and cannot
create a network namespace. The packaged demonstration therefore uses explicitly
scripted agent responses and an allowlisted fixture runner that can execute
only the exact bundled, human-authored demo source/test hashes. It is unavailable
through live application configuration. Demonstration tests execute real Python;
LLM reasoning and human approvals in that script are simulated and labelled.
The real HTTP adapter is exercised against a local protocol test server.

## Tradeoffs and assumptions

| Decision | Benefit | Cost / limit |
|---|---|---|
| Python standard library; explicit state machines | Easy setup, visible control logic, small dependency surface | No distributed scheduling or agent framework integrations |
| CLI and local browser GUI | Both use the same engine, evidence and explicit approval gates | Single-owner local control; no multiuser authentication |
| JSON artifacts in SQLite | Atomic state/version/approval commits | Large codebases require an external object store |
| Single owner capability | Separate human authority from model output | Not enterprise identity/RBAC or nonrepudiation |
| Fixed sandbox recipes | Narrow, auditable permissions | Python-only, no arbitrary build systems |
| Common planner tests locked before implementations | Candidates cannot weaken their acceptance tests | AI tests may share blind spots; human must review them |
| Human decision plus passing evidence to merge | Avoids accepting demonstrably failing code | Cannot waive a failed check in this prototype |
| Manual deployment/defer record | Preserves the PDF's human-only boundary | Cannot independently prove a deployment occurred |

Other source ambiguities A1–A6 and their selected interpretations are in
`PROCESS_MODEL.md`. These are implementation choices, not claims that the PDF
defines thresholds, storage, authentication, or a particular programming stack.

## Graphical control room (v0.2)

`hitl_se/gui.py` serves packaged HTML/CSS/JS over a loopback-only standard-library
HTTP server. `ControlRoom` connects all GUI actions to the existing engine and
store. It creates separate demo/live engines and dispatches bounded background
jobs per project. Polling provides current project states without blocking the
UI. Structured decision forms submit the displayed immutable gate/digest.
`HTTPProvider` accepts an optional in-memory credential map, preserving the CLI's
existing environment-based behavior. Shared demo fixtures now live in
`hitl_se/demo_fixtures.py`; `examples/fixtures.py` retains compatibility imports.
Runner pipe capture uses bounded reader threads for Windows compatibility.
See `GUI.md` for controls, startup, concurrency limits and the local trust boundary.
