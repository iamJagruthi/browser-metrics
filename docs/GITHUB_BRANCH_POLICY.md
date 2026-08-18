# GitHub branch policy — admin setup

Repository: **iamJagruthi/browser-metrics**

## Goal

| Branch | Who can push | How code lands |
|--------|----------------|----------------|
| **`dev`** | All teammates | `git push origin dev` or PR into `dev` |
| **`main`** | Nobody directly | PR from `dev` → `main` only (maintainer merge) |

## Step 1 — Set default branch to `dev`

GitHub → **Settings** → **General** → **Default branch** → switch to **`dev`** → Update.

New clones and PRs will target `dev` by default.

## Step 2 — Protect `main` (block direct pushes)

GitHub → **Settings** → **Branches** → **Add branch protection rule**

**Branch name pattern:** `main`

Enable:

- [x] **Require a pull request before merging**
  - (Optional) Require approvals — use 1 if you want review before production
- [x] **Do not allow bypassing the above settings**
- [x] **Restrict who can push to matching branches** → leave empty *or* only allow yourself / release managers
- [ ] Allow force pushes — **off**
- [ ] Allow deletions — **off**

Save changes.

Direct `git push origin main` from teammates will be **rejected by GitHub**.

## Step 3 — Keep `dev` open for the team

Do **not** add a protection rule that blocks pushes to `dev` (unless you later want PR-only on `dev` too).

Teammates workflow:

```bash
git checkout dev
git pull origin dev
git push origin dev
```

## Step 4 — Local hook (every developer)

After clone, run once:

```powershell
.\scripts\install-git-hooks.ps1
```

This blocks accidental `git push origin main` on their machine before GitHub even sees it.

## Step 5 — Optional automation (API)

If you have a GitHub PAT with `repo` admin scope:

```powershell
$env:GITHUB_TOKEN = "ghp_..."
.\scripts\setup-github-branch-protection.ps1
```

## Promote `dev` → `main` (production)

Only via pull request on GitHub:

1. Open PR: base **`main`**, compare **`dev`**
2. Review + merge
3. Teammates continue on `dev`; `main` stays stable
