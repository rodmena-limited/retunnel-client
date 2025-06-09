#!/bin/bash
# Run all tests with coverage

cd /mnt/blockstorage/ngrok/rewrite/retunnel-client

echo "Running all unit tests with coverage..."
uv run pytest \
    tests/test_protocol.py \
    tests/test_config.py \
    tests/test_exceptions.py \
    tests/test_utils.py \
    tests/test_api.py \
    tests/test_connection.py \
    tests/test_cli_unit.py \
    tests/test_client_unit.py \
    tests/test_client_unit_extended.py \
    -v --cov=retunnel --cov-report=term-missing --cov-report=xml

echo ""
echo "Coverage report generated in coverage.xml"