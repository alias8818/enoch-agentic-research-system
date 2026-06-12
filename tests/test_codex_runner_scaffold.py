from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_codex_runner_bootstraps_scaffold_before_exec(tmp_path: Path) -> None:
    scaffold_src = tmp_path / "scaffold-src"
    scaffold_src.mkdir()
    (scaffold_src / ".scaffold").mkdir()
    (scaffold_src / "templates").mkdir()
    (scaffold_src / "results").mkdir()
    (scaffold_src / "logs").mkdir()
    (scaffold_src / "scripts").mkdir()
    (scaffold_src / "prompts").mkdir()
    (scaffold_src / ".scaffold" / "manifest.yaml").write_text(
        "name: scaffold-enoch-worker-artifact\nversion: 0.1.0\n", encoding="utf-8"
    )
    _write_executable(
        scaffold_src / ".scaffold" / "bootstrap.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p .enoch .omx results\n"
        "cp templates/run_notes.template.md run_notes.md\n"
        "cp templates/project_decision.template.json .enoch/project_decision.json\n"
        "cat > .scaffold-used.yaml <<'YAML'\n"
        "scaffold_name: scaffold-enoch-worker-artifact\n"
        "scaffold_version: v0.1.0\n"
        "scaffold_commit: unknown\n"
        "YAML\n"
        "echo bootstrap_ok\n",
    )
    _write_executable(
        scaffold_src / ".scaffold" / "smoke.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "test -f run_notes.md\n"
        "test -f .enoch/project_decision.json\n"
        "python3 -m json.tool .enoch/project_decision.json >/dev/null\n"
        "echo smoke_ok\n",
    )
    (scaffold_src / "templates" / "run_notes.template.md").write_text("# Run Notes\n", encoding="utf-8")
    (scaffold_src / "templates" / "project_decision.template.json").write_text(
        json.dumps({"decision": "pending"}) + "\n", encoding="utf-8"
    )
    _git(["init", "-b", "main"], scaffold_src)
    _git(["config", "user.name", "Test"], scaffold_src)
    _git(["config", "user.email", "test@example.invalid"], scaffold_src)
    _git(["add", "."], scaffold_src)
    _git(["commit", "-m", "seed scaffold"], scaffold_src)
    scaffold_commit = subprocess.check_output(
        ["git", "-C", str(scaffold_src), "rev-parse", "HEAD"], text=True
    ).strip()

    fake_codex = tmp_path / "fake-codex"
    _write_executable(
        fake_codex,
        "#!/usr/bin/env bash\nset -euo pipefail\nlast=''\nargs=(\"$@\")\n"
        "for ((i=0; i<${#args[@]}; i++)); do\n"
        "  if [[ \"${args[$i]}\" == \"--output-last-message\" ]]; then last=\"${args[$((i+1))]}\"; fi\n"
        "done\n"
        "cat >/dev/null\n"
        "if [[ -n \"$last\" ]]; then mkdir -p \"$(dirname \"$last\")\"; echo OK > \"$last\"; fi\n"
        "echo '{\"type\":\"session\",\"session_id\":\"fake-session\"}'\n",
    )
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("do work\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()

    runner = Path(__file__).resolve().parents[1] / "deploy" / "enoch_codex_runner.sh"
    env = os.environ.copy()
    env.update(
        {
            "CODEX_BIN": str(fake_codex),
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_URL": f"file://{scaffold_src}",
        }
    )
    result = subprocess.run(
        [
            str(runner),
            "--run-id",
            "test-run",
            "--project-id",
            "test-project",
            "--project-dir",
            str(project),
            "--prompt-file",
            str(prompt),
            "--sandbox",
            "read-only",
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "scaffold bootstrap ok" in result.stderr
    assert (project / "run_notes.md").is_file()
    assert (project / ".enoch" / "project_decision.json").is_file()
    assert (project / ".omx" / "project_decision.json").is_file()
    scaffold_used = (project / ".scaffold-used.yaml").read_text(encoding="utf-8")
    assert f"scaffold_commit: {scaffold_commit}" in scaffold_used
    assert f"scaffold_source_url: file://{scaffold_src}" in scaffold_used
    session = json.loads((project / ".enoch" / "session.json").read_text(encoding="utf-8"))
    assert session["session_id"] == "fake-session"


def test_codex_runner_skips_scaffold_when_disabled(tmp_path: Path) -> None:
    fake_codex = tmp_path / "fake-codex"
    _write_executable(
        fake_codex,
        "#!/usr/bin/env bash\nset -euo pipefail\ncat >/dev/null\necho '{\"type\":\"session\",\"session_id\":\"fake-session\"}'\n",
    )
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("do work\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    runner = Path(__file__).resolve().parents[1] / "deploy" / "enoch_codex_runner.sh"
    env = os.environ.copy()
    env.update({"CODEX_BIN": str(fake_codex), "ENOCH_SCAFFOLD_BOOTSTRAP": "0"})

    result = subprocess.run(
        [
            str(runner),
            "--run-id",
            "test-run",
            "--project-id",
            "test-project",
            "--project-dir",
            str(project),
            "--prompt-file",
            str(prompt),
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert not (project / ".scaffold-used.yaml").exists()
