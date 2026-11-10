# Architecture and engineering decisions

This document covers the current offboarding prototype. See the
[project description](current-state.md), [business workflow](workflow.md), and
[data-flow reference](dataflow.md) for the complete current-state documentation.

## Trust boundaries

The deployed app has two fictional accounts: `casey.requester` and `alex.approver`.
Both use the `DemoPassword` supplied at deployment. No password is shipped in frontend code
or committed to Git. `/login` validates it on the server and issues a random 256-bit session
token; DynamoDB stores only its SHA-256 hash, account name and expiry. `/api` verifies the
session with a consistent read before performing any operation. Caller-supplied roles,
identity fields and fabricated gateway claims are ignored.

Sessions expire after 15 minutes, even before DynamoDB TTL cleanup. Sign-out deletes the
session. Login attempts are limited to ten per source IP per minute, in addition to API
throttling. Failed credentials get the same error for unknown usernames and wrong passwords.
Password rotation prevents new logins with the old password; existing sessions last until logout
or expiry. Tokens are held only in browser memory.

These accounts demonstrate two workflow roles, not verified real-person identity. Anyone who
knows the shared demo password can sign in as either account. The same account cannot approve
its own request, but this is not production separation of duties. Use fictional data only.
Production would require a managed identity provider or SSO and independently assigned roles.

Requesters see their own workflows; approvers see all demo workflows. Privileged AWS users
with table-write or Lambda-configuration access can bypass these application boundaries.

## Workflow states

```text
queued → running → awaiting_approval → queued_execution → executing → completed
             │             │                                ├→ completed_with_warning
             ├→ blocked    └→ rejected                     └→ blocked
             ├→ reviewed (no action proposed)
             └→ failed

failed / expired running → queued
failed / expired executing → queued_execution
```

Completed, reviewed, rejected and blocked workflows cannot be reopened. Resolve policy
conditions and start a new request; failed/interrupted work has the bounded Resume path below.
The code permits only one access-change proposal per workflow. Decisions bind to a stable
action hash including workflow identity and the full proposed input. Duplicate matching decisions
return the saved state; opposing decisions and stale action IDs are rejected.

## Policy and model responsibilities

The worker always gathers employee, asset, and incident evidence in code. Unknown employees,
non-departing employees, missing assigned systems, and unresolved high/critical incidents block
the workflow before a model call. Model-proposed employee and system identifiers must match
the request and exact assigned-system set. The worker re-reads evidence before executing an
approved proposal. Changed assignments require a new workflow, never silent expansion of approval.

The model can call read tools for the selected employee and propose a mutation. It cannot invoke
the mutation through the general tool dispatcher. An answer without a proposal produces `reviewed`,
not a false offboarding completion. Each workflow has a six-turn planning budget; retries do not
reset already saved turns. User and model strings render as escaped text in the UI.

Each model response may contain up to three distinct read tools. All names, exact
selected-employee arguments and unique IDs are validated before any handler executes.
Results are grouped into one user message with matching tool IDs. Mixed read/mutation
batches and multiple actions are rejected without partial execution. Individual read errors
are recorded as correlated error results and stop planning. Mutation proposals must appear
alone and retain the exact-action approval path.

Evidence schemas are validated before policy/inference and again on fresh read results;
missing security fields produce an explicit block. Requests naming allowlisted read tools
require those checks in orchestration, with actual results traced separately from model calls.
Provider filtering creates an explained, terminal block without automatic retry. Truncation,
malformed responses, context limits and unknown stop reasons produce controlled failures.
The [evaluation comparison](../evaluations/POSTFIX_REPORT.md) measures the changes against
preserved original results, including remaining provider-filter failures and the limitations
of the frozen single-tool selection rubric.

## Persistence, retries, and side effects

Every workflow document update checks the prior version. Session records and login counters
use separate operations in the same table. Critical workflow reads are strongly consistent.
The list uses a paginated, eventually consistent index; selected details use a direct consistent read.
Request IDs are scoped to the authenticated owner's identity and hashed into workflow IDs.
The same ID with different employee/reason data is a conflict.

Queue workers atomically claim a 150-second lease; the Lambda timeout is 120 seconds.
The SQS visibility timeout is 720 seconds. Duplicate deliveries during an active lease do no work.
Expired workers can be reclaimed by queue redelivery or the Resume command. Each workflow has
at most three worker attempts; the SQS dead-letter queue is a separate delivery-failure boundary.
Normal caught processing failures become `failed` and need an operator's Resume decision.

Saving a workflow and sending an SQS message are not transactional. If delivery fails, the API
returns the saved queued workflow with a warning. Retrying Start with the same payload or using
Resume re-dispatches it safely. A process death between save and send leaves a visible queued
workflow that the operator can resume. A production system could use a DynamoDB Streams outbox.

The simulated adapter produces a deterministic receipt from the action ID. If a worker dies after
the simulated effect but before saving the receipt, replay returns the same receipt. If the receipt
is already saved, recovery skips execution and only finishes the summary. This is **not a promise
of exactly-once real-world side effects**: a real adapter needs its own idempotency support and
reconciliation for ambiguous timeouts.

## Deployment and operational tradeoffs

- Separate API/worker IAM roles: the API cannot invoke Bedrock; only the worker can.
- Same-origin static dashboard: simple deployment, with Lambda invocation cost per asset request.
- No tokens in browser local/session storage; tokens live in memory and expire after 15 minutes.
  Refreshing the page requires sign-in again. Sign-out revokes the server session when the request succeeds.
- Shared index partition and owner filter: suitable for a portfolio workload; use owner/tenant-specific
  indexes, explicit tenancy, and a review-queue index before scaling.
- DynamoDB documents are bounded below the item-size limit. Inputs and model turns are bounded.
- Seven-day CloudWatch logs, SQS dead-letter metric alarm, and an account-wide budget alert.
  The metric alarm has no notification subscriber configured; inspect it in CloudWatch.
- Fixtures are static, including incident ownership. No fake transfer button or external integration claim.
- Existing prototype table rows are retained but do not appear in the new index/document schema.
  New request IDs include authenticated owner identity; old workflows are not migrated or executable.

## References

- [HTTP API quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html)
