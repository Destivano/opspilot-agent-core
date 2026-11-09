# OpsPilot

**Employee offboarding with evidence, deterministic policy, and human approval.**

> Current implementation snapshot: November 9, 2026. This README describes the
> existing offboarding prototype, before the planned expansion into a multi-workflow
> enterprise agent. Planned features are not presented as implemented capabilities.

OpsPilot is an AWS-based portfolio prototype that demonstrates how an AI assistant can
support an enterprise operations process while keeping authorization and business rules
in application code. The dashboard collects offboarding requests, shows employee and asset
evidence, flags incident ownership, and records exact approval decisions and execution receipts.

**All employee records are fictional. Access changes are simulated.** This project does
not connect to Google Workspace, GitHub Enterprise, or Jira and does not disable real accounts.
No production impact or time-savings claims are made.

In the deployed application, Amazon Bedrock Nova Micro can select tools and propose an
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
| Verification | Automated backend tests and Playwright browser checks; GitHub Actions validation configuration |

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

## Demonstration scenarios

| Employee | Fixture data | Expected path |
| --- | --- | --- |
| Alex Rivera, `EMP-1043` | Departing; Google Workspace and Jira; no open incidents | Eligible for an AI proposal and approval; model responses can also end without a proposal |
| Morgan Lee, `EMP-1042` | Departing; owns high-severity incident `INC-882` | Deterministically blocked before inference |

On AWS, sign in as `casey.requester` to submit a request, then as `alex.approver` to review it.
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
| AWS deployment | Real Bedrock calls | DynamoDB | Demo username/password and expiring session |

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
docs/                 Architecture, demo, deployment and publishing guides
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
AI scenario evaluations, baseline comparisons, or cost/time-savings dashboards. Software tests
are not a substitute for an AI evaluation dataset. GitHub Actions currently validates the code;
it does not deploy the application automatically.

## Planned lifecycle, not current functionality

The agreed next phase expands this prototype into the broader enterprise agent. The full
application will run temporarily for testing, evaluation and demo recording. After artifacts
are exported, its AWS resources will be removed. A separate static GitHub Pages showcase
will retain the project description, results and video without depending on a live backend.
That showcase and the broader platform are future work; this documentation update does not
deploy, delete or change application resources.

Licensed under [MIT](LICENSE).
