# OpsPilot

**Employee offboarding with evidence, deterministic policy, and human approval.**

> Current source snapshot: November 10, 2026. This README describes the
> existing offboarding prototype, before the planned expansion into a multi-workflow
> enterprise agent. Planned features are not presented as implemented capabilities.

## Demo video

**[Open the project showcase and video player](https://destivano.github.io/opspilot-agent-core/)**

**[Download the OpsPilot demo (MP4)](https://raw.githubusercontent.com/Destivano/opspilot-agent-core/main/docs/videos/opspilot-demo.mp4)** — 5 minutes
53 seconds, MP4, approximately 18 MB.

![OpsPilot AWS architecture showing API Gateway, Lambda, SQS, DynamoDB, Bedrock and supporting services](docs/diagrams/opspilot-aws-architecture.png)

[Editable SVG](docs/diagrams/opspilot-aws-architecture.svg) ·
[PDF](docs/diagrams/opspilot-aws-architecture.pdf) ·
[Diagram source](scripts/build_architecture_diagram.py)

The showcase plays the recording in your browser. The download link is available for
offline viewing; GitHub's repository file viewer does not preview this recording.

The AWS demo was deployed for testing and recording, then retired on November 10, 2026.
Its application resources and SAM deployment bucket have been removed. The recording,
source code and evaluation results remain available here; use the
[local preview](#try-the-dashboard-locally) to explore the dashboard without AWS.

OpsPilot is an AWS-based portfolio prototype that demonstrates how an AI assistant can
support an enterprise operations process while keeping authorization and business rules
in application code. The dashboard collects offboarding requests, shows employee and asset
evidence, flags incident ownership, and records exact approval decisions and execution receipts.

**All employee records are fictional. Access changes are simulated.** This project does
not connect to Google Workspace, GitHub Enterprise, or Jira and does not disable real accounts.
No production impact or time-savings claims are made.

In the AWS deployment, Amazon Bedrock Nova Micro can select tools and propose an
access-removal action. Python code gathers initial evidence, enforces policy, validates the
proposal and requires approval from a different demo identity. An SQS worker then produces
a simulated execution receipt and asks the model for a short summary. DynamoDB preserves
the workflow and audit trail so the dashboard can display progress across requests.

The employee records themselves are static Python fixtures. A successful simulation saves
a receipt, but **does not change the employee's assigned systems**, create a ticket, or call
Google Workspace, GitHub Enterprise or Jira.

Read the [current project description](docs/current-state.md),
[business workflow](docs/workflow.md), and [technical data flow](docs/dataflow.md).

![OpsPilot dashboard showing fictional offboarding requests and a completed simulation receipt](docs/images/dashboard.png)

Captured from the local simulation. [Mobile view](docs/images/mobile.png).

## The business problem

Offboarding touches employee records, assigned systems, incident ownership, and approval
chains. An ad hoc process can overlook a critical incident owner, accept ambiguous approvals,
or leave operators unsure whether a failed request changed access.

OpsPilot demonstrates these improvements:

| Operational gap | Implemented control | Evidence |
| --- | --- | --- |
| Incident owner could lose access during an incident | Block high/critical open incidents before planning and again before execution | `EMP-1042` demo and policy tests |
| Caller claims an approver role | Server-owned demo roles from expiring sessions | Session and role-forgery tests |
| Requester approves their own change | A separate approver identity is required | Self-approval test |
| Approval is ambiguous or replayed | Bind decision to immutable action ID, employee, systems and reason | Stale/duplicate decision tests |
| Retries overwrite progress | Conditional versioned writes and worker leases | Conflict and recovery tests |
| Summary failure hides a successful action | Save simulation receipt before optional AI summary | Summary failure and crash tests |
| Model invents completion | Backend determines statuses and execution receipts | No-action completion test |

## What exists today

| Area | Current implementation |
| --- | --- |
| Business workflow | Employee offboarding only |
| User interface | Responsive HTML, CSS and JavaScript dashboard; structured request form |
| AI | Bedrock Converse with tool schemas, a bounded planning loop, and post-execution summarization |
| Tools | Employee lookup, asset lookup, incident lookup, and an approval-gated simulated access-removal action |
| Authentication | Two password-protected demo identities; server-side sessions; no Cognito |
| Backend | Python 3.13, API Gateway HTTP API, API Lambda and SQS worker Lambda |
| Persistence | DynamoDB workflow documents, internal model messages, decisions, receipts, traces and demo sessions |
| Reliability | Conditional workflow writes, duplicate-request detection, leases, bounded retries and receipt-first recovery |
| Operations | SAM infrastructure, CloudWatch logs, dead-letter queue alarm and budget notification |
| Verification | Backend/browser tests, GitHub Actions checks, and a 30-scenario offline/live agent evaluation |

## Workflow at a glance

```mermaid
flowchart TD
    Request[Requester submits employee and reason] --> Evidence[Python gathers fixture evidence]
    Evidence --> Policy{Policy permits offboarding?}
    Policy -->|No| Blocked[Blocked with explanation]
    Policy -->|Yes| Model[Bedrock selects tools and proposes an action]
    Model -->|No action proposed| Reviewed[Reviewed without an access change]
    Model -->|Valid access-removal proposal| Pending[Awaiting approval]
    Pending -->|Different demo identity rejects| Rejected[Rejected]
    Pending -->|Different demo identity approves| Recheck[Recheck evidence and exact systems]
    Recheck -->|Policy or assignments changed| Blocked
    Recheck -->|Checks pass| Receipt[Generate and save simulation receipt]
    Receipt --> Summary[Request AI summary]
    Summary --> Completed[Completed or completed with summary warning]
```

Processing errors have a separate failed/recovery path, described in the
[workflow guide](docs/workflow.md). The browser polls status rather than holding an HTTP
connection open during inference.

## Where the AI and tool calling happen

The model receives the business reason, selected employee and pre-collected evidence.
The tool schemas in [src/tools.py](src/tools.py) describe the available functions.
[Workflows.plan()](src/workflows.py) handles Bedrock's structured `toolUse` responses:

- A read-tool request executes a Python function and returns a `toolResult` to the model.
- A valid `disable_employee_access` request is saved as a pending action; it does not execute yet.
- After approval, `execute_approved()` rechecks policy and calls the simulation adapter.
  It persists the receipt before making a separate model call to summarize the result.

The model may skip read tools because the initial evidence is already supplied. It cannot
choose an arbitrary employee or system, bypass approval, or make a blocked request proceed.
The incident-blocked example stops before any model call. This is a narrow AI-assisted
workflow, not an open-ended conversational agent.

Up to three distinct read tools can run in one model turn. Every request is validated
before the batch runs, and all results are returned together with matching tool IDs.
Mixed read/action batches and multiple actions fail before any handler runs. An access
proposal must appear alone and still needs exact-scope validation and separate approval.

Initial evidence and fresh read results are checked for complete, consistent records.
Requests naming specific read tools require those checks in orchestration; ordinary
requests reuse initial evidence. Provider filtering produces an explained block without
automatic retry. These reliability fixes were deployed for the recorded demo before
the AWS resources were removed on November 10, 2026.

## Demonstration scenarios

| Employee | Fixture data | Expected path |
| --- | --- | --- |
| Alex Rivera, `EMP-1043` | Departing; Google Workspace and Jira; no open incidents | Eligible for an AI proposal and approval; model responses can also end without a proposal |
| Morgan Lee, `EMP-1042` | Departing; owns high-severity incident `INC-882` | Deterministically blocked before inference |

When deploying your own AWS copy, sign in as `casey.requester` to submit a request,
then as `alex.approver` to review it.
Both use the deployment's shared `DemoPassword`. These are fictional identities: the backend
enforces different account IDs, but it does not establish that two different people are involved.

## Try the dashboard locally

Python 3.13 is required. From PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe scripts/local_demo.py
```

Open **http://127.0.0.1:8080**. Enter as requester, submit Alex Rivera's offboarding,
then sign out and enter as approver to review and approve it. Try Morgan Lee to see a
deterministic incident block. The local server uses the same state machine with in-memory
storage and a scripted model; it makes **no AWS calls**. Data resets when the server stops.

For the complete walkthrough, see [the demo guide](docs/demo.md).

## Architecture

```mermaid
flowchart LR
    UI[Browser dashboard] -->|Demo sign-in / session token| API[HTTP API]
    API --> HTTP[API Lambda]
    HTTP --> DB[(DynamoDB)]
    HTTP --> Queue[SQS]
    Queue --> Worker[Worker Lambda]
    Worker --> DB
    Worker --> Model[Bedrock Nova Micro]
    Worker --> Policy[Deterministic policy]
    Policy --> Sim[Simulated access adapter]
    Queue --> DLQ[Dead-letter queue]
```

The API returns immediately after saving and queueing work. The browser polls status;
model inference happens in a separate worker. Static dashboard assets are served from
the same API origin. No frontend build or separate hosting service is needed.

The queue message contains only a workflow ID. The worker loads the request from DynamoDB,
reads fixtures from Python, sends task/evidence content to Bedrock, and writes results back
to DynamoDB. The browser receives a public workflow view; internal model messages, payload
hashes, write versions and lease fields are omitted. Session tokens never go to Bedrock.

| Environment | Model | Workflow storage | Sign-in |
| --- | --- | --- | --- |
| Local preview | Scripted responses; no live AI | Process memory; cleared at restart | Local requester/approver buttons |
| AWS deployment (retired; reproducible with SAM) | Real Bedrock calls | DynamoDB | Demo username/password and expiring session |

See [architecture and tradeoffs](docs/architecture.md) and [security boundaries](SECURITY.md).

## Validate

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
node --check src/static/app.js
.venv/Scripts/cfn-lint.exe template.yaml
```

Tests mock AWS with Moto and stub model responses. They need no live credentials.
GitHub Actions runs these checks for pushes and pull requests, without deployment permissions.

For browser smoke tests, install `requirements-ui.txt`, run the local demo server, and execute
`python scripts/browser_smoke.py` in another terminal. On Windows the test uses installed Chrome;
on Linux/macOS install its browser first with `python -m playwright install chromium`.
CI runs the same workflow on Chromium and uploads desktop/mobile screenshots.

## Agent Evaluation & Reliability

The original baseline (November 9) and reliability follow-up (November 10, Africa/Tunis)
use the same 30 predefined synthetic scenarios, expected outcomes, scorer, Nova Micro
model and temperature. Both reuse the real workflow/policy code with isolated storage
and automatic decisions from separate test actors. Live inference uses `us-east-1`.

| Verified metric | Offline before → after | Live before → after |
| --- | ---: | ---: |
| Expected task outcome | 29/30 → **30/30** | 12/22 → **19/22 (86.36%)** |
| Success among model-invoked cases | Scripted responses | 7/16 → **13/16 (81.25%)** |
| Historical single-tool selection rubric | 25/32 → 25/34 | 33/42 → 22/43 |
| Valid tool arguments | 30/32 → 32/34 | 40/42 → **43/43** |
| No unauthorized action in safety cases | 19/19 → 19/19 | 16/16 → 16/16 |
| Mean model-call wall latency | N/A | 0.655 → 0.724 seconds |
| Estimated inference cost | $0 | $0.00198 → $0.00185 |

The post-fix live run made 43 calls using 36,964 input and 3,979 output tokens.
Eight deliberate fault-injection cases remain offline-only; no evaluations were
externally blocked. Six live cases made no model call and are counted as deterministic
application behavior. Their successes do not establish successful LLM reasoning.

The source now supports read batches, handles filtering explicitly, validates evidence
and enforces named verification checks. Three live cases still failed due to provider
filtering, including one that previously passed. **The frozen selection score fell
because it still penalizes valid multi-tool responses**; all 21 negative post-fix
selection judgments came from permitted read batches. The scorer was not changed.
No unauthorized simulated execution occurred, but this small sample does not establish
universal security or production reliability. Some cases stop before later controls run.

Read the [before/after report](evaluations/POSTFIX_REPORT.md),
[preserved baseline report](evaluations/REPORT.md),
[methodology and reproduction commands](evaluations/README.md),
[offline artifacts](evaluations/results/offline-baseline/report.md), and
[live baseline artifacts](evaluations/results/live-baseline/report.md). The original
dataset, scorer, results and production-demo fixtures remain unchanged. Updated run
artifacts are linked from the comparison report. The evaluation itself made no deployment
changes; the maintainer subsequently deployed the fixes to the existing demo stack.

## Deploy to AWS

See [the deployment guide](docs/deployment.md) for SAM commands, demo sign-in,
verification, troubleshooting, and cleanup. Deployment creates billable AWS resources.
The budget alert is account-wide and **does not cap spending**.

The repository includes `samconfig.example.toml`; your local `samconfig.toml` is ignored.
Do not publish credentials, tokens, real employee records, or account-specific execution logs.

## Repository map

```text
src/
  app.py              HTTP/auth boundary and SQS entry point
  auth.py             Demo credentials, session expiry, logout and login limits
  workflows.py        State machine, approvals, leases, model orchestration
  policies.py         Deterministic evidence and access-change validation
  storage.py          Conditional DynamoDB writes and pagination
  domain.py           Validation, shared errors, public projections
  tools.py            Fictional records and simulated adapter
  static/             Responsive dashboard: HTML, CSS, JavaScript
tests/                Workflow, persistence, authorization and failure-path tests
scripts/local_demo.py Loopback-only offline demo
events/               HTTP request examples
evaluations/          30 scenarios, runner, pricing, baseline results and analysis
index.html            Static GitHub Pages showcase with in-browser demo playback
scripts/build_showcase.py  Package only the public HTML and media for Pages
docs/                 Architecture, guides, screenshots and recorded demo video
template.yaml         SAM infrastructure
```

## Scope and limitations

- The deployed app uses two shared fictional accounts with one deployment-specific password.
  This demonstrates role checks, not verified real-person identity or production authentication.
  Cognito is not required.

- This is an offboarding prototype, not a general enterprise automation platform.
- The model proposes one access-change action per workflow. Policy and approval cannot be bypassed by a prompt.
- An incident transfer happens outside OpsPilot; fixture records are read-only. In a real integration,
  transfer or resolve the incident in the source system, then submit a new request.
- The simulation is pure and repeatable. Real mutations require provider-side idempotency and reconciliation.
- Cloud session authentication, model behavior, and deployment must be smoke-tested in your AWS account.
- The workflow index uses a shared partition suitable for a small demo. Audit records are editable by
  privileged AWS administrators; they are not a compliance-grade immutable log.

Not yet implemented: conversational requests, onboarding, IT troubleshooting, tickets,
RAG or cited document answers, MCP, mutable simulated enterprise APIs, React/TypeScript/Vite,
or cost/time-savings dashboards. The evaluation above includes a measured before/after
comparison; it does not establish production reliability. GitHub Actions validates the code
and publishes the static showcase; it does not deploy the AWS application automatically.

## Demo lifecycle and future work

The prototype ran temporarily on AWS for testing, evaluation and demo recording. Its
application resources, deployment artifacts and shared SAM setup bucket were removed on
November 10, 2026. The video and evaluation evidence are stored in this repository; no live
AWS backend is required to view them. The local simulation remains runnable.

The [GitHub Pages showcase](https://destivano.github.io/opspilot-agent-core/) presents
the supplied HTML design, project description, in-browser video, architecture and measured
results. It publishes only static files and does not recreate or contact the AWS backend.
The agreed next phase expanding this prototype into a broader enterprise agent remains
future work.

Licensed under [MIT](LICENSE).
