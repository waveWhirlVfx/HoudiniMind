.PHONY: verify lint format-check test typecheck format

verify: lint format-check test

lint:
	ruff check .

format-check:
	ruff format --check .

test:
	pytest -q

typecheck:
	mypy src/houdinimind

format:
	ruff check . --fix
	ruff format .
