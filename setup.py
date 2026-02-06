"""Setup script for agentwatch-cli."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="agentwatch-cli",
    version="0.1.5",
    author="AgentWatch",
    author_email="support@agentwatch.io",
    description="Connect your local Moltbot gateway to AgentWatch cloud",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/helivan-research/agentwatch-cli",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.9",
    install_requires=[
        "httpx>=0.24.0",
        "python-socketio>=5.8.0",
        "websockets>=12.0,<15.1",
    ],
    entry_points={
        "console_scripts": [
            "agentwatch-cli=agentwatch_cli.cli:main",
        ],
    },
)
