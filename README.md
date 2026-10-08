# HITL-SE: human-governed agentic software engineering

A runnable research prototype implementing the supplied **CSE 5695 Project
Source List** process, including the authoritative development revision on
pages 4–5. Humans select the direction, authorize consequential actions, and
decide what is accepted. Agents produce proposals, code, evidence and explanations.

The prototype includes six workflows, a browser GUI and interactive CLI, resumable
SQLite state, immutable versioned artifacts, configurable real LLM calls,
independent implementation/review contexts, sandbox execution controls, an audit
trail, automated tests, and an end-to-end demonstration.

## Open the GUI

Extract the archive and double-click **`Launch_GUI.bat`** on Windows (Python
3.11+ required). On macOS use `Launch_GUI.command`; on Linux open
`launch_gui.pyw` with Python. The control room opens in your browser.

Start with **Interactive demo → New project → Run to next checkpoint**. Review
proposals, source comparisons and measured test output, then submit decisions
from the form. No API key or Docker is needed for the fixed demo. The GUI also
supports live projects, provider settings, all human checkpoints, rework,
recovery and source/audit downloads. The CLI is still fully available.

Optional terminal launch: `python -m hitl_se gui`.
See **[docs/GUI.md](docs/GUI.md)** for setup, the demo walkthrough and a complete
control map. Live deployment remains a manual human action recorded in the app.

## Try the executable demonstration

Use Python 3.11+ on Windows, Linux, macOS, or WSL2. There are **no application Python
dependencies**. From the extracted `hitl-se` directory:

```bash
python3 -m unittest discover -s tests -v
python3 -m examples.demo --out my-demo
```

Use a new/empty demo output directory. Open `my-demo/DEMO_REPORT.md` and
`my-demo/audit.json`. The pre-run result is in `demo_output/`.

The demo uses **scripted agents and simulated human decisions**, clearly marked
in its records. Its tests execute actual, fixed Python source. One candidate
initially fails Unicode handling, both reviewers report that evidence, and a
human modification decision causes another implementation/evaluation round.
The selected implementation finally passes eight tests and static analysis.
Nothing is deployed. This demonstrates orchestration; it does not measure LLM
reasoning quality or actual stakeholder understanding.

To try the checkpoints yourself immediately, without an API key or Docker:

```bash
python3 -m examples.demo --interactive
```

This uses the same fixed demo task and scripted agents, but **you** inspect the
artifacts and make the human decisions in the real control room. Its persistent
state is `.hitl-demo/`. The strict fixture allowlist cannot execute arbitrary
source. At the first development final checkpoint, inspect B's Unicode failure
and choose `modify` to see a corrected independent implementation round.

## Start a live project

```bash
python3 -m hitl_se --workspace .hitl init
```

Edit `.hitl/config.json` using `config.example.json` as a guide:

1. Set a real provider model ID and base URL. The adapter uses the
   OpenAI-compatible `/chat/completions` protocol. It works with compatible
   hosted providers and local servers; API compatibility still depends on the
   chosen endpoint/model. Set `json_mode` to false if a local server does not
   support `response_format`; schema validation still applies.
2. Set the environment variable named by `api_key_env`. For example, in a
   trusted terminal: `export HITL_API_KEY='your-key'`. Keep secrets out of source,
   goals, artifacts and configuration JSON. For a local unauthenticated model
   server, use an empty `api_key_env` and a loopback HTTP URL.
3. Install/start Docker and manually prepare a Python image. The framework will
   **not pull images or install packages**. For example:

```bash
docker pull python:3.12-slim
docker image inspect python:3.12-slim --format '{{index .RepoDigests 0}}'
```

Copy the returned `python@sha256:...` value into `runner.image`. That command
is a human setup step, not an agent tool. Docker Desktop under WSL2 is suitable
for Windows users. The actual candidate runner uses a non-root UID, read-only
mounts, no network, dropped capabilities and bounded resources. No database,
human credential or API credential is mounted.

Then start the control room:

```bash
python3 -m hitl_se --workspace .hitl console
```

Enter a project name and concrete stakeholder requirements. `run` advances
automatic work **only until the next human checkpoint**. Closing the terminal
preserves progress; use the same workspace and project ID to resume.

Live LLM calls may incur provider charges. All calls are explicit project work;
the default configuration has no selected model, and no demo fallback is used.

## Human control room

| Command | Purpose |
|---|---|
| `run` / `step` | Advance to the next gate / execute one state |
| `show` | Inspect full proposal, risks, alternatives, source and evidence |
| `artifacts` / `artifact ID` | List versions / read an entire artifact |
| `compare` | Read the A/B source diff at development review |
| `decide` | Approve, reject, modify, or ask for information; prompts for the required human selection |
| `log` | View chronological actions and human decisions |
| `recover` | Explicitly retry failed/interrupted work after the lease expires if necessary |
| `rework` | Return from stopped testing to development planning for source corrections |
| `export PATH` | Write the canonical accepted source into an empty directory |
| `quit` | Stop and retain state |

Always inspect the proposal's actual artifacts before deciding. Agent confidence
and recommendations are not authorization. `info` asks a question while the
checkpoint stays pending; the answer is also stored as an artifact. A rejection
routes to the appropriate prior stage. A modification regenerates work and
requires subsequent review. No blank input counts as approval.

At development checkpoint 1, explicitly select A, B, or a corrected custom
approach and authorize the displayed fixed test/static recipes. At checkpoint 2,
inspect both source versions, raw test output, diff, and independent reports.
Select a passing candidate or request modifications. There is no score ranking
or automatic winner. Source “merge” means atomic promotion of the selected tree
to this prototype's canonical version; it does not modify an external Git repo.

Every testing action has its own policy **and** human gate, even when the same
command is proposed again. Unknown/deployment commands cannot be approved.
Final completion requires human verification and passing current evidence.
Deployment is text assistance followed by a human's manual/deferred record.

## Individual CLI operations

```bash
python3 -m hitl_se --workspace .hitl new normalizer --goal 'Create solution.py with normalize_whitespace(text): collapse Unicode whitespace and reject non-strings.'
python3 -m hitl_se --workspace .hitl list
python3 -m hitl_se --workspace .hitl run PROJECT_ID
python3 -m hitl_se --workspace .hitl inspect PROJECT_ID
python3 -m hitl_se --workspace .hitl artifacts PROJECT_ID
python3 -m hitl_se --workspace .hitl artifact ARTIFACT_ID
```

To submit a decision, copy the exact gate ID and digest from `inspect`:

```bash
python3 -m hitl_se --workspace .hitl decide PROJECT_ID \
  --gate GATE_ID --digest PROPOSAL_DIGEST --action approve \
  --feedback 'I checked the requirements and acceptance criteria.'
```

Architecture decisions need `--payload '{"selection":"OPTION_ID"}'`.
Development plan approval needs
`--payload '{"selection":"A","allow_evaluation":true}'`.
Final development approval needs `--payload '{"selection":"A"}'`.
Use `console` if JSON payloads are inconvenient; it asks for the right fields.

Exports and recovery:

```bash
python3 -m hitl_se --workspace .hitl export PROJECT_ID audit.json
python3 -m hitl_se --workspace .hitl export-source PROJECT_ID accepted-source
python3 -m hitl_se --workspace .hitl export-source PROJECT_ID tested-source --tested
python3 -m hitl_se --workspace .hitl recover PROJECT_ID
```

`--tested` includes the testing phase's extra tests. An uncertain execution is
stopped by its exact container name during recovery and returns to a human gate;
it is never silently replayed. Restore Docker first if recovery cannot confirm
container cleanup. The default lease is 600 seconds. After a hard interruption,
wait until the recorded lease expires. Don't manually edit the database to skip
the lease or checkpoints. Ordinary provider failures can be recovered immediately.

Preserve the whole workspace directory when moving machines, including SQLite
WAL files if the app is active and the owner-only `human.key`. The credential is
for local control, never for agents. Prefer backing up after stopping the app or
using SQLite's backup mechanism. Exported audit reports deliberately omit it.

## Configuration and independence

`roles` entries override the default provider's model, base URL and key variable
for specific roles. Supported role names are in `hitl_se/agents.py`. Assign
different providers/models to `planner_b`, `implementer_b` and `reviewer_b` when
desired. A and B use different prompts, separate stateless requests, independent
candidate snapshots, and no sibling private context, even when one provider is
used. This reduces information sharing; it does **not** establish statistical
independence or eliminate correlated errors.

Use provider timeouts and a lease longer than the longest state operation
(architecture exploration makes two sequential model calls; development
evaluation executes two bounded recipes). For example, the defaults use a
120-second provider timeout, 30-second recipe timeout and 600-second lease.

## Deliverable map

| Deliverable | Location |
|---|---|
| Formal states, branches, approvals, all 11 testing stages | `docs/PROCESS_MODEL.md` |
| Source-page/diagram traceability | Final table in `docs/PROCESS_MODEL.md` |
| Architecture, interfaces, design tradeoffs and assumptions | `docs/ARCHITECTURE.md` |
| Executable framework | `hitl_se/` |
| Setup/configuration | This README and `config.example.json` |
| Behavioral, adversarial, transport and CLI tests | `tests/` |
| Reproducible end-to-end run and evidence | `examples/`, `demo_output/` |
| Verification results and coverage | `docs/VERIFICATION.md` |
| Limitations and future work | `docs/LIMITATIONS.md` |
| Supplied source document | `docs/source/CSE-5695-Project-Source-List.pdf` |

The source proposal defines the process. Storage, thresholds, authentication,
runner, local snapshot merge and CLI are explicitly documented implementation
choices. The obsolete 1–3 development scores are not implemented.
