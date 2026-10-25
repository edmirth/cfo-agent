---
title: Run the tests on GitHub for every PR, and let Render deploy only when they pass
owner: @edmir
milestone: #platform
created: 2026-10-25
---
## Goal
Since card 52, every merge to `main` goes straight to `app.arvaka.no` (`autoDeployTrigger: commit` in `render.yaml`), and nothing runs the tests on the way: they run only when someone runs `./.venv/bin/python -m tests.run` before a PR. A mistake that slips through reaches the customer on the next merge.

## Done when
- [ ] A GitHub Actions workflow installs `requirements.txt` on Python 3.13 and runs `python -m tests.run` on every PR and every push to `main`
- [ ] The frontend builds in the same workflow (`npm ci && npm run build` in `frontend-react/`), so a broken build fails there and not on Render
- [ ] `render.yaml`: `autoDeployTrigger: checksPass` for both services, so Render deploys only a commit whose checks passed
- [ ] `main` is protected on GitHub: a PR cannot be merged while its checks fail
- [ ] A PR with a failing test is shown not to deploy

## Log
- 2026-10-25 (agent): created on @edmir's call, after the first deploys from main.
