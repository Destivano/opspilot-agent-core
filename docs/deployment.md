# Deployment and demo sign-in

## Build and update

From the project root, with Python 3.13, AWS CLI, SAM CLI and an authenticated AWS profile:

```powershell
sam validate --lint
sam build
sam deploy --guided
```

Use your existing stack `opspilot-agent-core` and region `us-east-1`.
Supply your `BudgetEmail`, keep the default `ModelId`, and set the new **`DemoPassword`**
to a private password of 12–128 characters with no spaces. There is no default password.
Do not send it to chat or commit it. If SAM saves parameters, keep the resulting
`samconfig.toml` private; this repository ignores it.

Review the change set. **If migrating from the historical Cognito-based version, the update removes the Cognito user pool,
its client, its groups and any accounts in that pool.** It also removes the JWT authorizer.
Session authentication is now enforced inside the API Lambda. Keep the existing stack;
do not delete/recreate it to upgrade.

The workflow table and dashboard API remain. Any retained Cognito-owned requests are visible to the
demo approver, but their ownership is not reassigned to the new requester. Create new requests
for the demo. Existing local-only prototype rows outside the document schema are not migrated.

SAM may ask about routes without authorization: `/login` and dashboard assets are public;
`/api` checks the server session before accessing workflows. There is no Cognito configuration
and no external identity service required.

If `sam` is not on your PowerShell PATH:

```powershell
& 'C:/Program Files/Amazon/AWSSAMCLI/bin/sam.cmd' build
& 'C:/Program Files/Amazon/AWSSAMCLI/bin/sam.cmd' deploy --guided
```

## Open the dashboard

```powershell
$dashboardUrl = aws cloudformation describe-stacks --stack-name opspilot-agent-core --region us-east-1 --query "Stacks[0].Outputs[?OutputKey=='DashboardUrl'].OutputValue" --output text
Start-Process $dashboardUrl
```

Use these fictional accounts with the **same password you supplied as `DemoPassword`**:

| Username | Role |
| --- | --- |
| `casey.requester` | Create requests and see their workflows |
| `alex.approver` | Review all requests, approve or reject another identity's request |

No account creation, email confirmation, or temporary-password flow is needed. Sessions last
15 minutes. The password protects the deployed demo from casual public access; the two accounts
are shared identities and are not a production identity system.

## Run the AI demo

1. Sign in as `casey.requester` and create an Alex Rivera (`EMP-1043`) request.
2. Wait for Bedrock to propose an action. Inspect the evidence and exact systems.
3. Sign out, sign in as `alex.approver`, and approve the simulation.
4. Inspect the receipt and audit trail.
5. Create a Morgan Lee (`EMP-1042`) request to show the incident policy block.

The deployed app calls Bedrock; the local server uses a scripted model. Access changes in
both environments remain simulated. Follow [the demo guide](demo.md) for the longer walkthrough.

## Cloud smoke checks

- Anonymous `GET /api` and `POST /api` return `401`.
- Wrong passwords fail; the login limit returns `429` after ten attempts per minute per source IP.
- Sign in, then verify requests are scoped to the server-selected account.
- Forged body roles and same-account approval return `403`.
- A different demo account can approve the exact pending action.
- Sign-out revokes the token; expired sessions are rejected even if TTL hasn't removed them.
- Alex's request reaches a simulation receipt; Morgan's is blocked before model use.

Local tests do not replace verification of AWS session storage, IAM grants, Bedrock access and
queue delivery in your deployed account.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Old Cognito login still appears | Rebuild/redeploy, then hard-refresh the browser |
| Incorrect demo password | Use `DemoPassword` from the latest deployment; no default is shipped |
| `401` / expired session | Sign in again; sessions last 15 minutes |
| `429` during login | Wait a minute before retrying |
| Request remains queued | Worker trigger, queue messages and logs; use Resume to retry delivery |
| Request says still processing | Wait for its 150-second lease to expire |
| Model failure | Worker CloudWatch logs, regional model access and Bedrock IAM permissions |
| Provider-filter block | Inspect `model_stop_reason` and `error_kind=provider_filter`; review before creating a new request; Resume is not available |
| Incomplete evidence block | Correct missing/invalid fixture or source fields, then create a new request |
| No action proposed | Create a new request with a clearer offboarding reason |
| Three attempts exhausted | Inspect the audit trail before creating a replacement request |

Local preview access/application logs are in `.local-demo.log`; HTTP handling does not write to
the Windows terminal. Restart the local server after updating its Python source.

Rebuilding/redeploying preserves existing workflow history. A separate maintenance action
can remove old request records without deleting accounts or sessions; refresh the dashboard
afterward. History cleanup alone requires no SAM build or deployment.

## Costs and cleanup

This version provisions **no Cognito resources**. Other services—Bedrock, Lambda, API Gateway,
DynamoDB, SQS and CloudWatch—can still incur charges. Session records reuse the workflow table;
the API rejects expired sessions immediately and DynamoDB TTL removes them asynchronously.
The account-wide USD 2 budget alert is not a spending cap or a project-only cost estimate.

To intentionally remove the entire demo, export any evidence you need and run:

```powershell
sam delete --stack-name opspilot-agent-core --region us-east-1
```

Deletion removes the workflow table and its data. Review SAM's deletion prompts carefully.
