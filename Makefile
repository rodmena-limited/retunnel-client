.PHONY: help test test-cov lint format format-check clean install install-dev build

# Default target
help:
	@echo "Available targets:"
	@echo "  test         Run tests without coverage"
	@echo "  test-cov     Run tests with coverage"
	@echo "  lint         Run linting checks (isort + black)"
	@echo "  format       Format code with isort and black"
	@echo "  format-check Check if code is properly formatted"
	@echo "  clean        Clean build artifacts"
	@echo "  install      Install package"
	@echo "  install-dev  Install package in development mode"
	@echo "  build        Build package"
	@echo "  ci           Run all CI checks (format-check + test-cov)"

# Test targets
test:
	python -m pytest

test-cov:
	python -m pytest --cov=retunnel --cov-report=xml --cov-report=term-missing

# Linting and formatting
lint: format-check

format:
	python -m isort .
	python -m black .

format-check:
	python -m isort --check-only --diff .
	python -m black --check --diff .

# Package management
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

install:
	python -m pip install .

install-dev:
	python -m pip install -e .

build:
	python -m build

# CI/CD target
ci: format-check test-cov