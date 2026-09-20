"""Keep release, compatibility, dependency, and automation versions coherent."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_release_and_runtime_versions_are_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    manifest = json.loads((ROOT / "custom_components/kinosail/manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert project["project"]["version"] == manifest["version"]
    assert project["project"]["requires-python"] == ">=3.14.2"
    assert project["tool"]["ruff"]["target-version"] == "py314"
    assert hacs["homeassistant"] == "2026.9.0"
    assert (ROOT / ".python-version").read_text().strip() == "3.14.7"


def test_dependency_versions_match_the_supported_home_assistant_environment() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert project["dependencies"] == ["aiohttp==3.14.3"]
    assert project["optional-dependencies"]["test"] == [
        "complexipy==8.0.1",
        "mutmut==3.8.0",
        "pre-commit==4.6.2",
        "pylint==4.0.8",
        "pytest==9.0.3",
        "pytest-asyncio==1.4.0",
        "pytest-cov==7.1.0",
        "pytest-homeassistant-custom-component==0.13.365",
        "radon==6.0.1",
        "ruff==0.16.8",
        "vulture==2.16",
    ]


def test_automation_refs_are_audited_and_immutable() -> None:
    workflow = (ROOT / ".github/workflows/validate.yml").read_text()

    assert workflow.count("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1") == 3
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0" in workflow
    assert "hacs/action@1ebf01c408f29afcb6406bd431bc98fd8cbb15aa # main" in workflow
    assert "home-assistant/actions/hassfest@58bff37c8947f690ace498be413a9b78d6f30f93 # master" in workflow
