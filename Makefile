.PHONY: setup lint typecheck test check format package xwax-smoke link-build link-test

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
