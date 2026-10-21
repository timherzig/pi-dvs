.PHONY: setup lint typecheck test check format package xwax-smoke xwax-linux-smoke xwax-macos-smoke link-build link-test

setup:
	uv sync --locked --all-groups
	uv run --locked pre-commit install --hook-type pre-commit --hook-type pre-push

lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .

typecheck:
	uv run --locked mypy

test:
	uv run --locked pytest

check: lint typecheck test
	uv lock --check

format:
	uv run --locked ruff format .

package:
	uv sync --locked --all-groups
	uv build --clear --no-build-isolation
	uv export --locked --no-default-groups --no-emit-project --output-file dist/requirements.txt
	uv run --locked python scripts/check_package.py

xwax-smoke:
	docker build -t pi-dvs-xwax-smoke -f scripts/xwax/Dockerfile .
	docker run --rm --network none -v "$(CURDIR):/app:ro" pi-dvs-xwax-smoke

link-build:
	scripts/link/build.sh

link-test:
	scripts/link/build.sh --prepare
	cd scripts/link && cargo fmt --check
	cd scripts/link && RB_LITE_TEST=1 cargo test --locked
	RB_LITE_TEST=1 cargo test --locked --manifest-path scripts/link/build/rbxport/Cargo.toml -p rbl-nfs --lib

xwax-macos-smoke:
	@test "$$(uname -s)" = Darwin
	@set -eu; scratch=$$(mktemp -d); trap 'rm -rf "$$scratch"' EXIT; \
	sh scripts/xwax/build.sh "$$scratch/engine"; \
	"$$scratch/engine/check-realtime" "$$scratch/engine/import" "$(CURDIR)/tests/fixtures/usb/Contents/Élise/Café 東京.wav"; \
	"$$scratch/engine/check-coreaudio-native" "$$scratch/engine/import" "$(CURDIR)/tests/fixtures/usb/Contents/Élise/Café 東京.wav"; \
	uv run --locked python scripts/check_xwax.py --engine "$$scratch/engine/xwax" --importer "$$scratch/engine/import"; \
	uv run --locked python scripts/check_streaming_xwax.py --engine "$$scratch/engine/xwax" --importer "$$scratch/engine/import"

# Native ARM64 CI uses the same pinned engine and probes as the Docker target.
xwax-linux-smoke:
	@test "$$(uname -s)" = Linux
	@set -eu; scratch=$$(mktemp -d); trap 'rm -rf "$$scratch"' EXIT; \
	sh scripts/xwax/build.sh "$$scratch/engine"; \
	"$$scratch/engine/check-realtime" "$$scratch/engine/import" "$(CURDIR)/tests/fixtures/usb/Contents/Élise/Café 東京.wav"; \
	PYTHONPATH=src python3 scripts/check_xwax.py --engine "$$scratch/engine/xwax" --importer "$$scratch/engine/import"; \
	PYTHONPATH=src python3 scripts/check_streaming_xwax.py --engine "$$scratch/engine/xwax" --importer "$$scratch/engine/import"
