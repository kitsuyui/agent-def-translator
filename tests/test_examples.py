from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_skill_examples_are_limited_to_hello() -> None:
    skill_dirs = [
        path.name
        for path in sorted((ROOT / "examples" / "skills").iterdir())
        if path.is_dir()
    ]

    assert skill_dirs == ["hello"]


def test_hello_skill_example_is_project_agnostic() -> None:
    text = (ROOT / "examples" / "skills" / "hello" / "SKILL.md").read_text(
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
