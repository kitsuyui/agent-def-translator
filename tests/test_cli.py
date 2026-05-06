from __future__ import annotations

from pathlib import Path

from agent_def_translator.cli import main


def test_cli_validate_and_translate(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "agents"
    definitions_dir.mkdir()
    (definitions_dir / "sample.toml").write_text(
        "\n".join(
            [
                'name = "sample"',
                'description = "Sample"',
                'instructions = "Base instructions"',
                "",
                "[targets.codex]",
                'sandbox_mode = "read-only"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "generated"

    assert main(["validate", "--definitions-dir", str(definitions_dir)]) == 0
    translate_args = [
        "translate",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(output_dir),
    ]
    diff_args = [
        "diff",
        "--definitions-dir",
        str(definitions_dir),
        "--output-dir",
        str(output_dir),
    ]
    assert main(translate_args) == 0
    assert main(diff_args) == 0

    generated = output_dir / "codex" / "agents" / "sample.toml"
    generated.write_text("stale", encoding="utf-8")

    assert main(diff_args) == 1


def test_cli_validate_renders_selected_targets(tmp_path: Path) -> None:
    definitions_dir = tmp_path / "agents"
    definitions_dir.mkdir()
    (definitions_dir / "sample.toml").write_text(
        "\n".join(
            [
                'name = "sample"',
                'description = "Sample"',
                'instructions = "Base instructions"',
                "",
                "[targets.claude]",
                'prompt_append_file = "missing.md"',
                "",
                "[targets.codex]",
                'sandbox_mode = "read-only"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    base_args = ["validate", "--definitions-dir", str(definitions_dir)]

    assert main([*base_args, "--target", "codex"]) == 0
    assert main([*base_args, "--target", "claude"]) == 2
