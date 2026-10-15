# Development

Use Python from `.python-version` and [uv](https://docs.astral.sh/uv/). Run
`make setup` after cloning to install locked development dependencies and Git
hooks, then `uv run --locked pi-dvs` to launch the demo.

On Ubuntu, install Qt's runtime libraries first:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends libegl1 libopengl0
```

Hooks live in Git's shared hooks directory. When using multiple worktrees, install
them only after every active checkout has this configuration. Until then, use
`uv run --locked pre-commit run --all-files` and `make check` explicitly.

## Branches and pull requests

Start a short-lived branch from current `main`, named `feat/...`, `fix/...`, or
`chore/...` (agent branches may use `codex/...`). Keep each PR focused on one issue
and use an imperative commit/PR title describing the behavior changed.

Open a PR into `main`, explain the change and verification, and squash merge after
the **Quality gate** passes and review conversations are resolved. Update the
branch when `main` changes. Delete merged branches. Fix a released bug through a
new PR and patch release; revert through a PR when rollback of source is needed.

This is a solo project, so an external approving review is not mandatory: GitHub
does not allow approving your own PR. Read the diff before merging; invite another
reviewer for audio, concurrency, security, and data migration changes.

## Coding standards

- Ruff owns Python formatting, import order, and lint rules; configuration lives
  in `pyproject.toml`. Run `make format` to apply formatting.
- Production code and maintenance scripts pass strict mypy. Annotate interfaces
  and model real value types; explain any narrowly scoped type suppression.
- Use descriptive snake_case Python names. Qt overrides, signals, and QML-facing
  members follow Qt's camelCase names. Keep QML components small and reusable.
- Keep the engine and library independent of Qt and hardware. The presentation
  layer translates actions and confirmed state; it does not duplicate deck state.
  Keep blocking I/O and future audio processing off the GUI thread.
- Prefer immutable domain values and explicit state transitions. Handle expected
  errors at boundaries and show actionable messages. Avoid catch-all exceptions
  that hide defects.
- Add dependencies with `uv add` and commit `pyproject.toml` and `uv.lock` together.
  Keep fixtures synthetic or redistributable and keep secrets out of the repo.

## Verification

Run `make check` before opening a PR. It checks formatting, lint, strict types,
tests with branch coverage, and dependency lock consistency. Tests must exercise
observable behavior, including failure/recovery paths for the changed feature.
Use deterministic engine tests for transitions and real offscreen QML controls
for UI integration. Add a regression test for a reproduced bug. Hardware tests
remain a separate requirement for hardware-dependent features.

The coverage floor in `pyproject.toml` applies to all application code; it is a
regression guard, not a substitute for useful assertions. Avoid lowering it or
excluding code merely to pass CI.

Run `make package` for resource, dependency, packaging, or release changes. It
builds both distributions using the locked backend, installs the wheel and locked
runtime dependencies into a fresh environment, opens the QML window, checks demo
assets, and writes checksums. CI runs this on both supported Python versions on
macOS and Linux. It does not establish macOS 13 or Raspberry Pi hardware support;
minimum-OS and real-device validation need manual runs.

See [releasing](docs/releasing.md) for development/production separation, release
promotion, and rollback.
