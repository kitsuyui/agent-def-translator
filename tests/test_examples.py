from __future__ import annotations

import re
import shutil
from pathlib import Path

from agent_def_translator import check_skill_drift

ROOT = Path(__file__).resolve().parents[1]
GENERATED_SKILL_ROOT = (
    ROOT / "examples" / "skills" / "claude" / "skills" / "hello"
)
BUNDLED_RESOURCE_PATHS = [
    "assets/sample.txt",
    "references/usage.md",
    "runbook.md",
    "scripts/hello.sh",
    "templates/greeting.txt",
]


def test_hello_skill_example_matches_the_current_generator(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "skills"
    shutil.copytree(ROOT / "examples" / "skills", output_dir)

    assert (
        check_skill_drift(
            definitions_dir=ROOT / "examples" / "skill-definitions",
            output_dir=output_dir,
            targets=("claude",),
        )
        == []
    )


def test_hello_skill_example_includes_its_bundle() -> None:
    files = [
        path.relative_to(GENERATED_SKILL_ROOT).as_posix()
        for path in sorted(GENERATED_SKILL_ROOT.rglob("*"))
        if path.is_file()
    ]

    assert files == [
        "SKILL.md",
        *BUNDLED_RESOURCE_PATHS,
    ]


def test_hello_skill_example_references_its_bundle() -> None:
    text = (GENERATED_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    for resource_path in BUNDLED_RESOURCE_PATHS:
        assert f"]({resource_path})" in text
        assert (GENERATED_SKILL_ROOT / resource_path).is_file()


def test_hello_skill_example_is_project_agnostic() -> None:
    text = (GENERATED_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    forbidden_terms = [
        "ss",
        "my-coding-agents",
        "nightly",
        "orchestrator",
        "handoff",
        "bridge",
    ]
    assert not any(
        re.search(rf"\b{re.escape(term)}\b", text) for term in forbidden_terms
    )


def test_skill_definition_example_is_project_agnostic() -> None:
    text = (ROOT / "examples" / "skill-definitions" / "hello.toml").read_text(
        encoding="utf-8",
    )

    forbidden_terms = [
        "ss",
        "my-coding-agents",
        "nightly",
        "orchestrator",
        "handoff",
        "bridge",
    ]
    assert not any(
        re.search(rf"\b{re.escape(term)}\b", text) for term in forbidden_terms
    )


def test_mcp_example_is_project_agnostic() -> None:
    text = (ROOT / "examples" / "mcp" / "openai-docs.toml").read_text(
        encoding="utf-8",
    )

    forbidden_terms = [
        "ss",
        "my-coding-agents",
        "nightly",
        "orchestrator",
        "handoff",
        "bridge",
    ]
    assert not any(term in text for term in forbidden_terms)


def test_plugin_definition_example_is_project_agnostic() -> None:
    text = (
        ROOT / "examples" / "plugin-definitions" / "hello-bundle.toml"
    ).read_text(
        encoding="utf-8",
    )

    forbidden_terms = [
        "ss",
        "my-coding-agents",
        "nightly",
        "orchestrator",
        "handoff",
        "bridge",
    ]
    assert not any(term in text for term in forbidden_terms)
