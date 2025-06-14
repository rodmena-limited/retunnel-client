# Building and Publishing ReTunnel Client

This guide covers the complete process for building and publishing the ReTunnel client to PyPI.

## Prerequisites

1. **Python Version**: Python 3.9+ (the package supports 3.9-3.12)
2. **Build Tools**: Install required build tools
   ```bash
   pip install --upgrade pip setuptools wheel build twine
   ```
3. **PyPI Account**: Create accounts at:
   - https://pypi.org (for production releases)
   - https://test.pypi.org (for testing)

## Pre-Release Checklist

1. **Update Version**
   ```bash
   # Edit VERSION file
   echo "2.0.1" > VERSION
   ```

2. **Update Changelog**
   ```bash
   # Create or update CHANGELOG.md with release notes
   ```

3. **Run All Tests**
   ```bash
   # Install dev dependencies
   make install-dev
   
   # Run all checks
   make check
   ```

4. **Check Package Metadata**
   ```bash
   # Verify setup.py and pyproject.toml have correct info
   # - Author email
   # - Project URLs
   # - Description
   # - Keywords
   ```

## Building the Package

### 1. Clean Previous Builds
```bash
make clean
```

### 2. Build Distribution Packages
```bash
# Using Makefile
make build

# Or manually
python -m build
```

This creates:
- `dist/retunnel-2.0.0-py3-none-any.whl` (wheel distribution)
- `dist/retunnel-2.0.0.tar.gz` (source distribution)

### 3. Verify the Build
```bash
# Check the contents of the wheel
unzip -l dist/retunnel-*.whl

# Check the contents of the tarball
tar -tzf dist/retunnel-*.tar.gz

# Verify all files are included
# Should contain: retunnel/, README.md, LICENSE, etc.
```

## Testing the Package

### 1. Test Installation in a Clean Environment
```bash
# Create a test virtual environment
python -m venv test-env
source test-env/bin/activate  # On Windows: test-env\Scripts\activate

# Install from the wheel
pip install dist/retunnel-*.whl

# Test the CLI
retunnel --help
retunnel http 8000  # Test actual functionality

# Clean up
deactivate
rm -rf test-env
```

### 2. Test with TestPyPI (Recommended)
```bash
# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*

# Test installation from TestPyPI
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ retunnel
```

## Publishing to PyPI

### 1. Configure PyPI Credentials

Create `~/.pypirc`:
```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-<your-api-token>

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-<your-test-api-token>
```

### 2. Upload to PyPI
```bash
# Using Makefile
make upload

# Or manually
python -m twine upload dist/*
```

### 3. Verify the Release
```bash
# Wait a few minutes for PyPI to update
pip install retunnel==2.0.0
```

## Post-Release

1. **Create Git Tag**
   ```bash
   git tag -a v2.0.0 -m "Release version 2.0.0"
   git push origin v2.0.0
   ```

2. **Create GitHub Release**
   - Go to https://github.com/your-org/retunnel/releases
   - Create new release from the tag
   - Add release notes
   - Upload the wheel and tarball as assets

3. **Update Documentation**
   - Update README with new version
   - Update any version-specific documentation

## Troubleshooting

### Common Issues

1. **Missing files in package**
   - Check MANIFEST.in includes all necessary files
   - Verify package_data in setup.py

2. **Import errors after installation**
   - Ensure all packages are listed in find_packages()
   - Check __init__.py files exist in all packages

3. **Dependency conflicts**
   - Use compatible version ranges in requirements
   - Test with minimum and maximum versions

### Validation Commands

```bash
# Check package metadata
python setup.py check

# Validate distribution files
twine check dist/*

# Test import
python -c "import retunnel; print(retunnel.__version__)"
```

## Automated Release Process

Consider setting up GitHub Actions for automated releases:

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: '3.9'
    - name: Install dependencies
      run: |
        pip install build twine
    - name: Build package
      run: python -m build
    - name: Publish to PyPI
      env:
        TWINE_USERNAME: __token__
        TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
      run: twine upload dist/*
```

## Summary

The complete release process:

1. Update VERSION file
2. Run `make check` to ensure quality
3. Run `make build` to create distributions
4. Test installation locally
5. Upload to TestPyPI and verify
6. Run `make upload` to publish to PyPI
7. Create git tag and GitHub release

For questions or issues, contact: support@retunnel.com