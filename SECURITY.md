# Demo authentication boundaries

This is a simulation portfolio project, not a production access-management system.
The two fictional accounts share a deployment-specific password. Anyone who knows it can
use either role. This demonstrates server-side role enforcement, not real-person identity
verification or production separation of duties.

- `POST /login` verifies the password server-side. It is never shipped in frontend code.
- Roles are fixed in `src/auth.py`, not accepted from request JSON or client claims.
- Random session tokens are held in browser memory. Only hashes are stored in DynamoDB.
- The backend checks the 15-minute expiration; DynamoDB TTL cleans up old records later.
- Sign-out deletes the session. If the network request fails, it expires normally.
- Ten login attempts per source IP per minute are allowed. API Gateway also throttles requests.
- The API enforces authentication inside Lambda. Removing the Cognito authorizer does not make
  workflow commands usable without a valid session.
- `DemoPassword` is a CloudFormation `NoEcho` parameter, available only to the API Lambda.
  Privileged AWS administrators can inspect function configuration. Keep saved deployment
  parameters private; `samconfig.toml` is ignored. Do not log passwords or tokens.
- Changing the demo password prevents new logins with the old password; existing sessions
  remain valid until logout or expiry.
- A different demo identity must approve the exact pending action; policy is rechecked before execution.
- Local preview fake tokens are accepted only by `scripts/local_demo.py`, outside SAM's `CodeUri`.
  It binds to loopback and validates Host/Origin. Never expose the local server publicly.

Use fictional employee records only. Before production: managed identity/SSO, MFA, independently
assigned roles, tenant isolation, source-system integration, external-operation idempotency,
immutable audit retention, backup/restore and independent security review are still required.

Do not post credentials, tokens or employee data in public issues. Use private vulnerability
reporting if enabled by the repository owner.
