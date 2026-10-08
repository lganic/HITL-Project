# Limits and next steps

## What this prototype proves

The engine executes the proposed lifecycle, suspends at explicit human gates,
preserves revisions and rejection routes, keeps separate implementation/review
contexts, executes bounded checks, records human choices, resumes persistent
state, and has no deployment execution path. The packaged demonstration
includes actual failing and passing Python test runs.

It does **not** prove that LLM output is correct, that agent strategies are
statistically independent, that an approval came from an attentive person, or
that this process improves real development productivity. Those are research
questions requiring evaluation with people and real model runs.

## Practical boundaries

- **Live integrations:** the HTTP provider is implemented and protocol-tested
  against a real local HTTP server. No paid/external model was called during
  this build. Docker invocation/security options are tested with intercepted
  launches; a live container could not run in the build environment. Validate
  your selected provider/model and Docker host before using real generated code.
- **Local owner trust:** the private capability separates control authority
  from model output. Someone with the host account can read the key or edit the
  program/database. This is not enterprise RBAC, verified legal identity,
  signed attestation, or protection from the machine administrator. On Windows,
  keep the workspace in your private user directory or use WSL2; POSIX file
  modes alone are not Windows ACLs.
- **Small source trees:** bounded text trees include Python and common text web
  assets (`.html`, `.css`, `.js`, `.mjs`, `.svg`). Only Python syntax and
  standard-library unittest tests run in the fixed check recipe. Web assets
  require separate human inspection and browser testing; passing Python checks
  do not establish that a web UI works. There is no repository import, dependency installer,
  large-codebase indexing, arbitrary build tool, native binary execution,
  deletion/rename patch protocol, or external CI/Git integration.
- **Snapshot merge:** accepted source is versioned inside SQLite and exported
  to files. It is not a Git branch/PR merge. Main's parent is checked before
  promotion. External repository conflicts require a future adapter.
- **Test evidence:** static analysis covers syntax and a small set of risky
  calls. It is not a full security/type/lint analysis. Common agent-written
  acceptance tests can share blind spots; independent testing mitigates but
  does not eliminate that. Source can import or manipulate test machinery in
  its container, so results are not a cryptographically trustworthy proof
  against deliberately adversarial programs. Reports retain raw outputs for
  human examination and never replace human selection.
- **Sandbox scope:** isolation relies on the user's trusted, patched Docker
  installation and chosen image. This is not a formally verified sandbox.
  Fingerprints cover configured image/limits and trusted harness, not every
  host kernel/daemon detail. Image changes require renewed permission; other
  environmental changes should be surfaced by the human or agent flag.
- **Reasoning strategy:** architectural evidence search is a small local
  pattern catalog. It is ReAct-inspired, not a full LATS tree search or an
  empirical reproduction of either paper. Public rationale is stored, not
  private chain-of-thought. The catalog is intentionally small.
- **Human workload:** the two development checkpoints are preserved, but testing
  requires a per-action decision and separate final sign-off. A long testing
  session can therefore be demanding. The prototype deliberately does not
  infer standing permission from a prior approval.
- **Recovery:** unknown tool execution is not assumed unsuccessful. Recovery
  stops the named container, preserves uncertainty and requests renewed
  authorization. Agent calls interrupted before commit may be repeated and
  incur provider charges; external exactly-once LLM calls are not promised.
- **Deployment and review:** manual deployment and stakeholder activity are
  recorded as human statements, not independently verified remote events. A
  deferred deployment is explicitly distinguishable from a completed one.

## Useful research extensions

1. Run a small, consented study comparing this workflow against single-agent
   coding and the original late-only “double-double” process. Measure defect
   escape, time/cost, revision count, and human ability to explain the chosen
   design. Do not treat acceptance speed alone as understanding.
2. Add authenticated team roles and separate stakeholder/checker/architect/release
   identities, with signed decisions and access-controlled evidence retention.
3. Add a Git worktree adapter, PR diffs, merge-conflict detection and immutable
   CI attestations. Preserve the same human gates and artifact binding.
4. Add sandbox workers with stronger workload isolation, external test oracles,
   reviewed dependency environments, static type checking and vulnerability
   scanning; keep additional execution recipes deny-by-default.
5. Add a web control room over the same engine, with side-by-side reports and
   accessible source/evidence views. Avoid automatic winner highlighting that
   could reproduce the proposal's automation-bias concern.
6. Add project-specific architectural evidence, retrieval provenance, bounded
   search budgets and confidence calibration. Compare provider diversity and
   prompt diversity empirically before claiming independent error reduction.

## GUI scope (v0.2)

The browser control room is local and single-owner. It has no remote hosting,
team authentication, visual in-place source editor, or external Git integration.
Corrections use the process model's feedback-and-regeneration route. The GUI
records manual deployments; it does not deploy. Machine-level Python/Docker
installation and preparation of the sandbox image remain prerequisites.
Polling refreshes approximately every 1.5 seconds. Artifacts and audit exports
are loaded in memory, so this prototype is intended for small research projects.
Windows launchers and portable pipe capture are included; verification in this
deliverable ran on Linux, not a native Windows or macOS host.
