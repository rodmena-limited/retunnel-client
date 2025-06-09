from setuptools import find_packages, setup

with open("VERSION", "r") as version_file:
    version = version_file.read().strip()

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="retunnel",
    version=version,
    packages=find_packages(include=["retunnel", "retunnel.*"]),
    install_requires=[
        "aiohttp>=3.8.0",
        "websockets>=11.0",
        "msgpack>=1.0.0",
        "typer[all]>=0.9.0",
        "rich>=13.0.0",
        "pyyaml>=6.0",
        "pydantic>=2.0.0",
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
            "pytest-mock>=3.10.0",
            "aioresponses>=0.7.4",
        ]
    },
    entry_points={
        "console_scripts": [
            "retunnel=retunnel.client.cli:app",
        ],
    },
    python_requires=">=3.9",
    description="ReTunnel - Securely expose local servers to the internet",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://retunnel.com",
    author="ReTunnel Team",
    author_email="retunnel-support@rodmena.co.uk",
    license="MIT",
    license_files=("LICENSE",),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: System :: Networking",
        "Topic :: Internet :: WWW/HTTP",
        "Operating System :: OS Independent",
    ],
    keywords="tunnel, ngrok, localhost, webhook, http, https, tcp, reverse-proxy",
)
