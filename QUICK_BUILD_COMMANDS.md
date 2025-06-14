# Quick Build and Publish Commands for ReTunnel Client

## 1. Setup Build Environment

```bash
# Go to the client directory
cd /mnt/blockstorage/ngrok/rewrite/retunnel-client

# Create/activate virtual environment (if not using uv)
python3 -m venv build-env
source build-env/bin/activate

# Install build tools
pip install --upgrade pip setuptools wheel build twine

# Or if using uv (recommended)
uv pip install --upgrade build twine
```

## 2. Pre-Build Checks

```bash
# Run all quality checks
make check

# Or manually:
make format       # Format code
make lint        # Run linting
make typecheck   # Type checking  
make test        # Run tests
```

## 3. Build the Package

```bash
# Clean previous builds
make clean

# Build the package
make build

# Or manually:
python -m build

# This creates:
# - dist/retunnel-2.0.0-py3-none-any.whl
# - dist/retunnel-2.0.0.tar.gz
```

## 4. Test the Build Locally

```bash
# Create test environment
python -m venv test-install
source test-install/bin/activate

# Install the wheel
pip install dist/retunnel-2.0.0-py3-none-any.whl

# Test it works
retunnel --help
retunnel http 8000

# Cleanup
deactivate
rm -rf test-install
```

## 5. Upload to TestPyPI (Optional but Recommended)

```bash
# Upload to test repository
python -m twine upload --repository testpypi dist/*

# You'll be prompted for:
# Username: __token__
# Password: <your-test-pypi-token>

# Test installation
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ retunnel
```

## 6. Upload to PyPI

```bash
# Upload to production PyPI
make upload

# Or manually:
python -m twine upload dist/*

# You'll be prompted for:
# Username: __token__  
# Password: <your-pypi-token>
```

## 7. Verify Installation

```bash
# In a new environment
pip install retunnel==2.0.0

# Test
retunnel --version
```

## Complete One-Liner (if everything is set up)

```bash
make clean && make check && make build && make upload
```

## Using GitHub Actions (Automated)

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install build twine
    
    - name: Build package
      run: python -m build
    
    - name: Publish to PyPI
      env:
        TWINE_USERNAME: __token__
        TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
      run: twine upload dist/*
```

## Notes

- Make sure `VERSION` file contains the version you want to release
- Ensure all tests pass before building
- Consider using semantic versioning (MAJOR.MINOR.PATCH)
- Always test with TestPyPI first for new releases
- Keep your PyPI tokens secure (use environment variables or keyring)