# OpsPilot: current project description

Snapshot date: November 10, 2026. This describes the repository's existing implementation,
not the target platform in the future project plan. It is not a fresh audit of deployed AWS resources.

## Project summary

OpsPilot is an AWS serverless, AI-assisted employee-offboarding prototype. A requester selects
a fictional employee and supplies a business reason. The backend collects employee, asset and
incident evidence, checks deterministic business rules, and uses Amazon Bedrock Nova Micro
to prepare a structured access-removal proposal. A different demo identity must approve that
exact proposal before a worker generates a simulated execution receipt. The application retains
request details, model messages, decisions, outcomes and an audit timeline in DynamoDB.

The purpose of the current version is to demonstrate an approval boundary around model-selected
tools, persisted workflow state and recovery from interrupted processing. It does not yet offer
general enterprise assistance or measured business savings.

## User experience

The web dashboard provides a request form, a searchable/filterable queue, employee and asset
evidence, incident details, proposed systems and reason, approval/rejection controls, a receipt
view and an audit trail. The user supplies free text in a reason field, but there is no chat
interface and no conversation in which the assistant asks follow-up questions.

The deployed accounts are `casey.requester` and `alex.approver`. A shared deployment-specific
password grants access to either fictional identity. Server-side roles and owner IDs govern
visibility and approvals. This is demo authentication, not verified individual identity.

## Existing technical implementation

| Layer | What it does |
| --- | --- |
| Browser | Plain HTML/CSS/JavaScript; renders workflow evidence and decisions; polls for progress |
| API Gateway | Routes same-origin asset, login, logout and workflow requests |
| API Lambda | Validates sessions, validates inputs, checks permissions, saves commands and queues work |
| SQS | Carries workflow IDs to the worker; retries delivery failures and supports a dead-letter queue |
| Worker Lambda | Claims work, applies policy, runs the model/tool loop, executes approved simulations and summarizes |
| Bedrock | Selects tools/proposes one access change and summarizes its simulated result |
| Python fixture tools | Return fictional employee, asset and incident records; generate deterministic receipts |
| DynamoDB | Stores workflows, conversation messages, approvals, traces, receipts, sessions and login-limit counters |
| CloudWatch | Receives application logs and exposes a dead-letter queue alarm |
| SAM and GitHub Actions | Define infrastructure and automated validation, respectively |

The local preview replaces AWS persistence with memory, queue delivery with a thread, Bedrock
with scripted responses, and sign-in with local identity buttons. It exercises the same workflow
logic but does not prove live model behavior or AWS integration.

## AI responsibilities versus application responsibilities

The model is responsible for choosing among the supplied tools, constructing a proposed action,
and summarizing a receipt. It may request additional read-tool results before proposing a change.

Application code is responsible for initial evidence gathering, policy decisions, access control,
checking the exact employee/system set, approval validity, actual function dispatch, state
transitions, persistence, retries and terminal status. A model statement alone never creates a
successful execution receipt.

The mutation is a simulation: the adapter returns a repeatable result and the workflow stores
it. No external service or persistent employee access record is modified. The four tool handlers
are in-process Python functions, not separate enterprise HTTP services.

## Demonstrated engineering controls

- Repeated starts with the same owner/request ID and payload reuse the existing workflow.
- Reusing an ID with changed request data produces a conflict.
- An action ID binds approval to the workflow and complete proposed input.
- Same-account approval and caller-supplied role overrides are rejected.
- Policy and assigned systems are checked again immediately before simulated execution.
- Conditional version checks prevent stale workflow writes.
- Leases and attempt limits bound concurrent processing and recovery.
- A saved receipt survives optional summary failure.
- Tests cover authorization, policy, replay, concurrency, failure paths, sessions and browser flows.

These controls demonstrate software behavior. Shared demo accounts do not prove genuine
separation of duties; deterministic simulated receipts do not prove exactly-once execution
against external services; a system prompt is not comprehensive prompt-injection protection.

## Current scope boundary

The project supports offboarding only. There are two employee fixtures, one incident fixture,
and four tool definitions. There are no ticket APIs, onboarding workflows, knowledge documents,
RAG pipeline, citations, MCP servers, conversational clarification, or cross-request memory.

A [30-scenario evaluation baseline](../evaluations/REPORT.md) records 29/30 offline
passes and 12/22 applicable live Bedrock passes. The [reliability follow-up](../evaluations/POSTFIX_REPORT.md)
records 30/30 offline and 19/22 live passes, with the same eight predefined offline-only cases.
The current source supports read batches, controlled provider-filter outcomes, evidence
schemas and enforced named verification. The maintainer confirmed deployment of these
fixes to the existing AWS demo stack on November 10; the evaluation runs themselves
did not deploy infrastructure or modify production data.
Validation includes 143 automated tests and browser smoke checks; tests use
mocked AWS/model behavior and are separate from the recorded live inference runs. There is
no evaluation dashboard or measured productivity/cost improvement over another baseline.

React, TypeScript, Vite, a static GitHub Pages showcase and automated deployment are future
work. Cognito has intentionally been removed from the current template.

## Related documentation

- [README and setup](../README.md)
- [Business workflow and recovery states](workflow.md)
- [Data flow, API boundaries and storage](dataflow.md)
- [Architecture and engineering tradeoffs](architecture.md)
- [Deployment and demo sign-in](deployment.md)
