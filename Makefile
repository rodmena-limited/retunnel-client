.PHONY: help test test-cov lint format format-check typecheck clean install install-dev build upload check

# Use Python 3.9 via uv
PYTHON := uv run --python 3.9 python
PIP := uv run --python 3.9 pip

# Default target
help:
	@echo "Available targets:"
	@echo "  test         Run tests with coverage"
	@echo "  test-quick   Run tests without coverage"
	@echo "  lint         Run flake8 linting"
	@echo "  format       Format code with isort and black"
	@echo "  format-check Check if code is properly formatted"
	@echo "  typecheck    Run mypy type checking"
	@echo "  clean        Clean build artifacts"
	@echo "  install      Install package"
	@echo "  install-dev  Install package with dev dependencies"
	@echo "  build        Build distribution packages"
	@echo "  upload       Upload to PyPI"
	@echo "  check        Run all checks (format, lint, typecheck, test)"

# Test targets
test:
	$(PYTHON) -m pytest

test-quick:
	$(PYTHON) -m pytest -x --no-cov

test-verbose:
	$(PYTHON) -m pytest -vv

# Code quality
format:
	$(PYTHON) -m isort retunnel tests
	$(PYTHON) -m black retunnel tests

format-check:
	$(PYTHON) -m isort --check-only --diff retunnel tests
	$(PYTHON) -m black --check --diff retunnel tests

lint:
	$(PYTHON) -m flake8 retunnel tests

typecheck:
	$(PYTHON) -m mypy retunnel

# Package management
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

install:
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

build: clean
	$(PYTHON) -m build

upload: build
	$(PYTHON) -m twine upload dist/*

# Development workflow
check: format lint typecheck test