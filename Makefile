# Variables
PYTHON = python3.12
VENV = .venv
PIP = $(VENV)/bin/pip
PYTHON_BIN = $(VENV)/bin/python
ISORT = $(VENV)/bin/isort
BLACK = $(VENV)/bin/black
MYPY = $(VENV)/bin/mypy
PYTEST = $(VENV)/bin/pytest

# Directories
SRC_DIR = genserver
TESTS_DIR = tests

# Default target
all: install lint test

# Create virtual environment
$(VENV):
	$(PYTHON) -m venv $(VENV)

# Install dependencies
install: $(VENV)
	$(PIP) install -r requirements-dev.txt
	$(PIP) install -e .

# Linting with isort
lint-isort:
	$(ISORT) $(SRC_DIR) $(TESTS_DIR)

# Formatting with black
format-black:
	$(BLACK) $(SRC_DIR) $(TESTS_DIR)

# Type checking with mypy
type-check:
	$(MYPY) $(SRC_DIR)

# Run tests with pytest
test:
	$(PYTEST)

# Combined linting, formatting, and type checking
lint: lint-isort format-black type-check

# Clean up
clean:
	rm -rf $(VENV)

.PHONY: all install lint lint-isort format-black type-check test clean
