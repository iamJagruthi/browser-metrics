## Pull request checklist

**Target branch:** `dev` (not `main`)

- [ ] Branch is up to date with `origin/dev`
- [ ] `.env` and secrets are **not** committed
- [ ] Ran `.\scripts\install-git-hooks.ps1` locally
- [ ] Pushed to `dev` or this PR merges into `dev`

Production releases: open a separate PR from `dev` → `main` (maintainers only).
