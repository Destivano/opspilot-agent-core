# Publish to GitHub

## Static GitHub Pages showcase

The public showcase is at <https://destivano.github.io/opspilot-agent-core/>.
The supplied root `index.html` is the editable source. It is separate from the application
dashboard at `src/static/index.html` and needs no AWS account or backend to view.

`scripts/build_showcase.py` packages only the HTML, demo MP4, architecture PNG and poster
into the ignored `_site/` directory. It validates relative asset references and refuses
unexpected output files. `.github/workflows/pages.yml` builds that directory and deploys
it using GitHub Pages Actions on relevant pushes to `main` or manual dispatch. Repository
Pages settings use **GitHub Actions** as the publishing source. No AWS credentials or
deployment permissions are used.

```powershell
.venv/Scripts/python.exe scripts/build_showcase.py
.venv/Scripts/python.exe -m http.server 8000 --bind 127.0.0.1 --directory _site
```

Open `http://127.0.0.1:8000/` to preview. Keep assets relative so the same HTML works
under the GitHub project path. Original video and diagram files stay in `docs/`; the
build copies them to the site's expected `assets/` paths without duplicate tracked media.

## Validation

From the project root, after installing `requirements-dev.txt`:

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
node --check src/static/app.js
.venv/Scripts/cfn-lint.exe template.yaml
```

Backend tests mock AWS and model responses; they require no live credentials. GitHub
Actions runs these checks and browser smoke tests. For local browser checks, install
`requirements-ui.txt`, start `scripts/local_demo.py`, and run `scripts/browser_smoke.py`
in another terminal. Windows uses installed Chrome; on Linux/macOS first run
`python -m playwright install chromium`.

## Repository changes

1. Run the validation checks above and review the diff.
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
