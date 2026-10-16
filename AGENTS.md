# Working in pi-dvs

Before changing code, read [CONTRIBUTING.md](CONTRIBUTING.md) for architecture,
coding standards, and required checks. Use the commands in `Makefile`.

For dependency changes, preserve the macOS compatibility constraint explained in
`pyproject.toml` and update `uv.lock`. For packaging, release, CI, or repository
policy changes, also read [docs/releasing.md](docs/releasing.md).

The demo is silent. Describe hardware and audio behavior as verified only after
testing the actual device. Keep this distinction in tests, documentation, and UI.
