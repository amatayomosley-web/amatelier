.PHONY: setup test lint format demo clean build publish

setup:
	pip install -e ".[dev]"

test:
	pytest --cov=src --cov-report=term-missing

lint:
	ruff check src tests
	mypy src

format:
	ruff check --fix src tests
	ruff format src tests

demo:
	python examples/first_run/run.py

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

build: clean
	python -m build

# Publish is performed by CI via trusted publishing; this target is manual fallback only.
publish: build
	python -m twine upload dist/*
