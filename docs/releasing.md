# Development and releases

`main` is the integration branch. Development happens on short-lived branches,
then reviewed PRs merge with a passing **Quality gate**. Releases are immutable
version tags from `main`, not a separately maintained production branch.

## Continuous integration

`.github/workflows/checks.yml` tests Python 3.12 and 3.13 on macOS and Ubuntu.
A separate required Linux job builds the pinned, patched xwax binary and runs
`make xwax-smoke` with dummy decks; it does not establish hardware compatibility.
A macOS native job runs `make xwax-macos-smoke` with fake-host routing checks
and dummy/progressive engine tests; it does not open audio hardware. Both native
jobs are required by the quality gate. A separate Linux job runs `make link-test` against loopback CDJ clients using the
pinned Rust helper and dependency patch. The Python wheel excludes that GPL
executable; helper distribution needs the corresponding source and notices.
Every Python/platform combination checks repository hygiene, formatting, lint, strict types,
behavior tests, branch coverage, lock consistency, and installation of the built
wheel with its resources. Linux installs Qt's EGL/OpenGL libraries for headless
tests. One stable `Quality gate` check reports the whole matrix for branch rules.

Actions and hooks are pinned to commit SHAs; Dependabot proposes weekly dependency
and action updates. Keep version comments alongside action pins. Updates need the
same checks and compatibility review as application changes. Test jobs have read
access only; the release job alone receives write access to create a draft.

## Publish a version

1. Bump `project.version` in `pyproject.toml`, run `uv lock`, and merge that PR.
   Use `MAJOR.MINOR.PATCH`. For the initial demo the version is `0.1.0`.
2. From a clean, up-to-date `main`, create and push an annotated tag matching that
   version. Example for the initial release:

   ```sh
   git switch main
   git pull --ff-only
   git tag -a v0.1.0 -m 'Release 0.1.0'
   git push origin v0.1.0
   ```

3. The Release workflow verifies that the commit belongs to `main` and the tag
   matches the package version, reruns CI, then creates a **draft GitHub Release**
   with the exact tested wheel, source archive, hashed runtime requirements, and
   checksums. It promotes the CI artifacts without rebuilding them. A failure
   stops release creation. If draft creation succeeded, review the existing draft
   instead of rerunning its creation job.
4. Download the draft assets and test them on the personal Apple Silicon Mac
   (including the minimum supported macOS version before claiming it is verified).
   Check search, both decks, playback protection, failed-load recovery, and artwork.
   Review release notes and publish the draft in GitHub when ready.

Tagging deliberately requests a release build; publication remains a human
decision. Never move a published tag or overwrite released artifacts. Fix a bad
version with a new patch release. No release is created just by merging a PR.

## Install and roll back

Keep released installations separate from the development checkout and its
`.venv`. Download all four assets for a version into a new folder. Verify checksums
and install into a fresh environment; these commands run inside that folder:

```sh
shasum -a 256 -c SHA256SUMS
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --require-hashes -r requirements.txt
uv pip install --python .venv/bin/python --no-deps ./*.whl
.venv/bin/pi-dvs
```

Keep the previous release folder until the new version is verified. To roll back,
close the application and run the previous folder's `.venv/bin/pi-dvs`. Do not
update an installation in place during a set. The Python artifact defaults to
silent simulation and can connect to a separately built xwax engine; it does not
establish production audio-appliance readiness. Automatic Raspberry Pi deployment,
health checks, and service rollback will be added with the hardware/boot milestone.

## Appliance implementation reference

For #7, see [PiDeck startup and deployment lessons](pideck-reference.md#startup-and-deployment--7).
Use its separation of soundcard setup and launch configuration as precedent, with
owned services and bounded recovery. Its old image and broad process-killing
launcher are not deployment instructions for this project.

## GitHub repository policy

The versioned desired ruleset is `.github/rulesets/main.json`: pull requests,
GitHub Actions' `Quality gate`, current base branch, resolved review threads,
linear history, and blocked force-push/deletion. It intentionally requires zero
external approvals for this solo repository. There are no admin bypass actors.
Repository merge settings should allow squash merge only and delete merged
branches. Feature branches remain writable normally.

`.github/rulesets/releases.json` blocks deleting or force-updating `v*` release
tags, while allowing maintainers to create new version tags.

Ruleset JSON is configuration for GitHub's API, not an automatically applied
workflow. Apply it only after a branch running the new `Quality gate` is available,
so the initial PR can satisfy the check. When changing policy, update the file and
GitHub together; inspect existing rulesets and update the matching ID rather than
creating duplicates. See [GitHub's ruleset documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).
