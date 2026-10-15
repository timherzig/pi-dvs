.PHONY: setup lint typecheck test check format package

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
