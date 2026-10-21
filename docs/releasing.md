# Development and releases

`main` is the integration branch. Development happens on short-lived branches,
then reviewed PRs merge with a passing **Quality gate**. Releases are immutable
version tags from `main`, not a separately maintained production branch.

## Continuous integration

CI runs once per PR, on pushes to `main`, on manual dispatch, and as part of a
release. `.github/workflows/checks.yml` focuses on these appliance workflows:

| Required check | What it establishes |
| --- | --- |
| Libraries and app: Linux ARM64 / Python 3.12 | Read-only Device Library and OneLibrary imports, playlists and paths; remote CDJ catalog/audio reads; removal, cancellation and reconnection; two-deck loading/protection and offscreen QML. Full suite with branch coverage, lint/types and installed-wheel smoke. |
| Libraries and app: macOS / Python 3.13 | The same behaviors on the development platform and the other supported Python version. |
| Two-deck xwax: Linux ARM64 | Build the pinned engine natively; exercise audio rendering guards, two actual imports, progressive streaming, failure/recovery and reconnect using dummy decks. |
| Two-deck xwax: macOS | The same engine probes plus fake-host CoreAudio routing checks for development. |
| Serve read-only music to CDJ clients: Linux ARM64 | Build the pinned Rust helper; concurrent loopback CDJ clients browse and read original files, including file-handle, retry and read-budget regressions. |

Guest USBs remain read-only: serving music means reading original bytes over the
network, never editing the Rekordbox database, playlists or audio. Python tests use
independent fixtures and loopback peers; native engine tests use synthetic audio.
These checks cover the component paths, not a single end-to-end physical DJ setup.
The Python wheel excludes the GPL helper; distribution needs its source and notices.

ARM64 runners check the target architecture and dependencies, **not Pi 4 speed,
4 GB memory limits or audible playback**. Two xwax decks plus two CDJs means four
playback decks in the system: the CDJs decode their own audio, not two additional
xwax decks. Before claiming appliance readiness, run the following on the actual
Pi 4B / 4 GB with the PX5 and two CDJs:

1. Mount a guest Rekordbox USB read-only; browse playlists and load both xwax decks.
2. Browse a CDJ-attached USB and load its tracks into both xwax decks.
3. Play both DVS decks while both CDJs browse/load/play music served by the Pi.
4. Exercise source switching, USB removal, network loss and recovery while another
   deck plays. Confirm playback protection and unchanged guest media.
5. Record the build, duration, formats, audio buffer settings, XRUNs, listening
   result, peak memory and temperature/throttling. Include sustained playback and
   repeated loads; passing hosted CI cannot replace this run.

Linux jobs install Qt's EGL/OpenGL libraries for headless tests. One stable
`Quality gate` check requires every job above. Tested distributions from Linux
ARM64 retain the `distributions` artifact name used by the release workflow.

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
