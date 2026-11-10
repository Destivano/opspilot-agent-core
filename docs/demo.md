# Demonstration walkthrough

## Local walkthrough

1. Run `python scripts/local_demo.py` from the activated project virtual environment.
2. Open `http://127.0.0.1:8080` and enter as **requester**.
3. Create a request for **Alex Rivera / EMP-1043**, with reason `Final working day`.
4. Wait for **Awaiting approval**. Show the employee record, two assigned systems,
   absence of incidents, exact action ID, and audit trail. The requester has no approval control.
5. Sign out and enter as **approver**. Select the request and approve the simulation.
6. Show **Completed**, the saved simulation receipt and the two distinct actor identities in the trace.
7. Sign out and return as requester. Submit **Morgan Lee / EMP-1042**.
8. Show **Policy blocked**, the `INC-882` incident and the instruction to transfer/resolve ownership.
   There is no approval action and no model call for this blocked request.
9. Create another Alex Rivera request, switch identities, and reject it to demonstrate a terminal decision.

Local preview identities are intentionally available only in `scripts/local_demo.py`, which is
outside the SAM `CodeUri`. Deployed code does not accept local preview tokens.

## Cloud walkthrough

Use the same steps with `casey.requester` and `alex.approver`, using the shared demo password
you chose during deployment. Roles are assigned by the server; no account setup is required.
The actual model may choose different read tools or return a review without a proposal;
the backend still enforces the same business rules and approval boundary. Valid read batches
can contain up to three tools; the audit trail shows which reads actually executed.
Provider-filtered responses produce an explained `blocked` outcome and cannot be resumed;
review the request before creating a new one. Other failures may show `failed`; inspect
the error and worker logs and use Resume only for an eligible, recoverable failure.

The maintainer confirmed deploying the reliability fixes on November 10, 2026. Saved AWS
requests persist across builds/deployments. Removing old workflow records is a separate
maintenance action; after removal, refresh the dashboard to start with an empty queue.
Deleting history does not require `sam build` or `sam deploy`.

## API demonstration

Request examples are in `events/`. After sign-in through an API client, hold your access token
in a local session variable; never commit it. Send `start.json` as the JSON body to `POST /api`.
Poll `GET /api?workflow_id=<returned-id>` until a decision is required. Populate the returned
action ID in `approve.json`, then submit it with the separate approver's token.

Repeat the same start payload to show duplicate handling. Change the reason under the same
request ID to show `409`. Send `approve-denied.json` with a requester token to show that an
asserted body role grants no authority. Send an outdated action ID to show stale approval rejection.

## Evidence for GitHub and interviews

The README includes desktop and mobile screenshots captured from the verified local demo.
Re-running the browser smoke script writes new captures to the ignored `test-results/` directory.
These are local simulation evidence, not proof of a successful AWS deployment.

Capture a short recording or screenshots showing:

- The queue with completed and blocked requests.
- Evidence and exact proposed systems before approval.
- The incident block and its resolution guidance.
- A simulation receipt with actor/timestamp trace.
- A passing CI run.
- The [before/after evaluation](../evaluations/POSTFIX_REPORT.md): 29/30 to 30/30 offline
  passes and 12/22 to 19/22 live passes, with remaining filter failures disclosed.

Explain which tests demonstrate a control, rather than claiming unmeasured production impact.
Only use the fictional fixtures. Do not publish tokens, identifiers from real users,
AWS account identifiers, or employee records.

Useful narrative: “I separated model planning from authorization, enforced incident checks
in application code, bound approval to an exact action, and tested failure recovery around the
execution receipt.”
