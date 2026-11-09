# API examples

These files are HTTP request bodies for `POST /api`, **not** direct Lambda invocation events.
Sign in at `POST /login` with a demo username and your deployment password. Use the
returned `accessToken` in `Authorization: Bearer <token>`.
The local preview accepts its two explicit demo identities only on the local server.

| File | Expected behavior |
| --- | --- |
| `start.json` | Alex Rivera (`EMP-1043`): collect evidence, propose access removal |
| `incident-offboarding.json` | Morgan Lee (`EMP-1042`): blocked by incident `INC-882` before model use |
| `approve.json` | Approve the exact returned action as a different authenticated approver |
| `approve-denied.json` | Send as a requester: `403` despite the forged body role |
| `reject.json` | Reject the pending action as a different approver |
| `resume.json` | Retry dispatch or recover an expired/failed worker attempt |
| `invalid.json` | Authenticated unsupported command: `400` |
| `status.json` | **GET query parameters**, not a POST body: `/api?workflow_id=...` |

Copy `workflow_id` from the start response and `pending_action.action_id` from the status response.
Do not reuse another scenario's IDs. Repeating the same start payload with the same request ID
and authenticated owner returns the existing workflow; changing its payload returns `409`.
The old `ask` command and approval-bypass configuration have been removed.
