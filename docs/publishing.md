# Publish to GitHub

1. Run all checks in the README and review the diff.
2. Confirm `.aws-sam/`, `.venv/`, `.uv-cache/`, and `samconfig.toml` are ignored with
   `git status --short --ignored`. None of them should be staged.
3. Review the MIT license and replace its generic copyright holder if you prefer your own name.
4. Add a short demo recording/screenshots using fictional records after the cloud smoke check.
5. This checkout already has `origin` configured as
   `https://github.com/Destivano/opspilot-agent-core.git`. Confirm it with `git remote -v`, then push:

```powershell
git add .
git diff --cached --stat
git diff --cached
git commit -m "Build approval-controlled offboarding demo with dashboard and tests"
git branch -M main
git push -u origin main
```

If a remote already exists, inspect `git remote -v` before changing it. Do not overwrite another
project's remote or force-push history. Run a secret scan using your preferred tool before making
the repository public; ignored files do not remove secrets that were committed previously.

Suggested description: “AWS offboarding prototype with Bedrock-assisted planning, deterministic
incident policy, session-authenticated demo approvals, recoverable workflows, and an operations dashboard.”

Suggested topics: `aws`, `serverless`, `bedrock`, `python`, `human-in-the-loop`, `it-operations`.
Check that the Actions workflow passes on GitHub before adding a CI badge to the README.
