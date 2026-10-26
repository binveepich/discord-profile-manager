# Branching and beta releases

## Layout

- `main` is the release branch. Merge reviewed, tested work into it; tag each beta on `main` (`v0.1.0-beta.1`, then increment the beta number).
- `develop` is the integration branch, created from `refactor/revamped-parallel` after its current work is committed.
- Create short-lived `feature/...` and `fix/...` branches from `develop`.

## Commands from the current checkout

Read-only checks are safe any time:

```powershell
git status --short
git branch --show-current
git branch -a
```

The current worktree must be reviewed and committed on `refactor/revamped-parallel` before creating `develop`:

```powershell
git add -A
git diff --cached --check
git diff --cached --stat
git commit -m "Finish current refactor work"
```

After that commit, create and publish `develop` from the committed refactor branch:

```powershell
git switch -c develop refactor/revamped-parallel
git push --set-upstream origin develop
```

## Daily feature flow

Start each change from an up-to-date `develop` branch:

```powershell
git switch develop
git pull --ff-only
git switch -c feature/<short-name>
```

After implementing, reviewing, and testing the change:

```powershell
git add <changed-paths>
git diff --cached --check
git commit -m "Describe the change"
git push --set-upstream origin feature/<short-name>
git switch develop
git pull --ff-only
git merge --no-ff feature/<short-name>
git push origin develop
```

Use `fix/<short-name>` in place of `feature/<short-name>` for fixes.

## Cut a beta

Only cut a beta after the tested, reviewed `develop` work is merged into `main`:

```powershell
git switch main
git pull --ff-only origin main
git merge --no-ff develop
git push origin main
git tag -a v0.1.0-beta.1 -m "Discord Profile Manager v0.1.0-beta.1"
git push origin v0.1.0-beta.1
```

For the next beta, choose the next unused `v0.1.0-beta.N` tag and use that exact version in both tag commands and the release export command.
