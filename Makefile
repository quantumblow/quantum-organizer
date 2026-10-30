.PHONY: test lint fmt build-ui dev

test:
	.venv/bin/python -m pytest -q

lint:
	.venv/bin/ruff check src tests
	.venv/bin/mypy src

fmt:
	.venv/bin/ruff format src tests

build-ui:
	cd frontend && npm install && npm run build

dev:
	.venv/bin/qorg serve --data ./data --port 8080
