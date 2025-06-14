#!/usr/bin/env python3
"""
Pre-release package checker for ReTunnel client
"""

import os
import sys
from pathlib import Path

def check_file_exists(filepath, required=True):
    """Check if a file exists"""
    exists = Path(filepath).exists()
    status = "✓" if exists else "✗"
    print(f"{status} {filepath}")
    if required and not exists:
        return False
    return True

def check_version_sync():
    """Check if versions are synchronized"""
    version_file = Path("VERSION").read_text().strip()
    
    # Check __init__.py
    init_file = Path("retunnel/__init__.py").read_text()
    init_version = None
    for line in init_file.split('\n'):
        if line.startswith('__version__'):
            init_version = line.split('"')[1]
            break
    
    # Check setup.py uses VERSION file
    setup_file = Path("setup.py").read_text()
    uses_version_file = 'with open("VERSION"' in setup_file
    
    # Check pyproject.toml
    pyproject = Path("pyproject.toml").read_text()
    pyproject_version = None
    for line in pyproject.split('\n'):
        if line.startswith('version ='):
            pyproject_version = line.split('"')[1]
            break
    
    print(f"\nVersion Check:")
    print(f"  VERSION file: {version_file}")
    print(f"  __init__.py: {init_version}")
    print(f"  pyproject.toml: {pyproject_version}")
    print(f"  setup.py reads VERSION: {'✓' if uses_version_file else '✗'}")
    
    return version_file == init_version == pyproject_version

def check_package_structure():
    """Check package structure"""
    print("\nPackage Structure:")
    required_files = [
        "README.md",
        "LICENSE", 
        "VERSION",
        "setup.py",
        "pyproject.toml",
        "MANIFEST.in",
        "retunnel/__init__.py",
        "retunnel/client/__init__.py",
        "retunnel/client/cli.py",
        "retunnel/client/high_performance_model.py",
        "retunnel/core/__init__.py",
        "retunnel/core/protocol.py",
        "retunnel/utils/__init__.py",
    ]
    
    all_exist = True
    for file in required_files:
        if not check_file_exists(file):
            all_exist = False
    
    return all_exist

def check_dependencies():
    """Check if all dev dependencies are installed"""
    print("\nDevelopment Tools:")
    try:
        import build
        print("✓ build")
    except ImportError:
        print("✗ build (pip install build)")
        return False
        
    try:
        import twine
        print("✓ twine")
    except ImportError:
        print("✗ twine (pip install twine)")
        return False
    
    return True

def main():
    """Run all checks"""
    print("ReTunnel Client Package Checker")
    print("=" * 40)
    
    checks = [
        ("File Structure", check_package_structure()),
        ("Version Sync", check_version_sync()),
        ("Build Tools", check_dependencies()),
    ]
    
    print("\nSummary:")
    print("-" * 40)
    all_passed = True
    for name, passed in checks:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n✅ Package is ready for building!")
        print("\nNext steps:")
        print("1. Run: make clean")
        print("2. Run: make build")
        print("3. Check dist/ directory")
        print("4. Run: make upload (or test with TestPyPI first)")
    else:
        print("\n❌ Package needs fixes before building")
        sys.exit(1)

if __name__ == "__main__":
    main()