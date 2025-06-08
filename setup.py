from setuptools import find_packages, setup

with open("VERSION", "r") as version_file:
    version = version_file.read().strip()

setup(
    name="retunnel",
    version=version,
    packages=find_packages(
        include=["retunnel"]
    ),  # Find packages under retunnel/
    install_requires=[],  # No dependencies for now
    description="ReTunnel - Securely expose local servers to the internet",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://retunnel.com",
    author="ReTunnel Team",
    author_email="retunnel-support@rodmena.co.uk",
    license="MIT",
    license_files=(
        "LICENSE",
    ),  # Explicitly include the LICENSE file - KEEP THIS!
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: System :: Networking",
        "Topic :: Internet :: WWW/HTTP",
    ],
)
