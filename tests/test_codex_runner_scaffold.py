from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _commit_repo(path: Path, message: str = "seed repo") -> str:
    _git(["init", "-b", "main"], path)
    _git(["config", "user.name", "Test"], path)
    _git(["config", "user.email", "test@example.invalid"], path)
    _git(["add", "."], path)
    _git(["commit", "-m", message], path)
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


def _create_scaffold_repo(tmp_path: Path, name: str) -> tuple[Path, str]:
    scaffold_src = tmp_path / name
    scaffold_src.mkdir()
    (scaffold_src / ".scaffold").mkdir()
    (scaffold_src / "templates").mkdir()
    (scaffold_src / "results").mkdir()
    (scaffold_src / "logs").mkdir()
    (scaffold_src / "scripts").mkdir()
    (scaffold_src / "prompts").mkdir()
    (scaffold_src / ".scaffold" / "manifest.yaml").write_text(
        f"name: {name}\nversion: 0.1.0\n", encoding="utf-8"
    )
    _write_executable(
        scaffold_src / ".scaffold" / "bootstrap.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p .enoch .omx results\n"
        "cp templates/run_notes.template.md run_notes.md\n"
        "cp templates/project_decision.template.json .enoch/project_decision.json\n"
        "cat > .scaffold-used.yaml <<'YAML'\n"
        f"scaffold_name: {name}\n"
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
    (scaffold_src / "templates" / "run_notes.template.md").write_text(
        f"# Run Notes for {name}\n", encoding="utf-8"
    )
    (scaffold_src / "templates" / "project_decision.template.json").write_text(
        json.dumps({"decision": "pending", "scaffold": name}) + "\n", encoding="utf-8"
    )
    commit = _commit_repo(scaffold_src, f"seed {name}")
    return scaffold_src, commit


def _create_catalog_repo(
    tmp_path: Path,
    *,
    default: str,
    scaffolds: dict[str, str],
    fmt: str = "json",
) -> Path:
    catalog = tmp_path / f"scaffold-catalog-{fmt}"
    catalog.mkdir()
    if fmt == "json":
        (catalog / "catalog.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "default": default,
                    "scaffolds": [
                        {"name": name, "repo": repo, "tags": [name]}
                        for name, repo in scaffolds.items()
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    elif fmt == "yaml":
        entries = []
        for name, repo in scaffolds.items():
            entries.append(
                "  - name: {name}\n"
                "    repo: scaffolds/{name}\n"
                "    clone_url: {repo}\n"
                "    status: seed\n".format(name=name, repo=repo)
            )
        (catalog / "catalog.yaml").write_text(
            "version: 0.1.0\n"
            "namespace: scaffolds\n"
            f"default: {default}\n"
            "scaffolds:\n"
            + "".join(entries)
            + "selection_rules:\n"
            + "  - If no domain scaffold exists, start from scaffold-enoch-worker-artifact.\n",
            encoding="utf-8",
        )
    else:  # pragma: no cover - helper guard.
        raise ValueError(fmt)
    _commit_repo(catalog, "seed catalog")
    return catalog


def _create_fake_codex(tmp_path: Path) -> Path:
    fake_codex = tmp_path / "fake-codex"
    _write_executable(
        fake_codex,
        "#!/usr/bin/env bash\nset -euo pipefail\nlast=''\nargs=(\"$@\")\n"
        "for ((i=0; i<${#args[@]}; i++)); do\n"
        '  if [[ "${args[$i]}" == "--output-last-message" ]]; then last="${args[$((i+1))]}"; fi\n'
        "done\n"
        "cat >/dev/null\n"
        'if [[ -n "$last" ]]; then mkdir -p "$(dirname "$last")"; echo OK > "$last"; fi\n'
        'echo \'{"type":"session","session_id":"fake-session"}\'\n',
    )
    return fake_codex


def _run_runner(
    tmp_path: Path, env_updates: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("do work\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    runner = Path(__file__).resolve().parents[1] / "deploy" / "enoch_codex_runner.sh"
    env = os.environ.copy()
    env.update({"CODEX_BIN": str(_create_fake_codex(tmp_path))})
    env.update(env_updates)
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
    result.project = project  # type: ignore[attr-defined]
    return result


def test_codex_runner_bootstraps_default_scaffold_from_catalog(tmp_path: Path) -> None:
    scaffold_src, scaffold_commit = _create_scaffold_repo(
        tmp_path, "scaffold-enoch-worker-artifact"
    )
    catalog = _create_catalog_repo(
        tmp_path,
        default="scaffold-enoch-worker-artifact",
        scaffolds={"scaffold-enoch-worker-artifact": f"file://{scaffold_src}"},
    )
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_CATALOG_URL": f"file://{catalog}",
        },
    )

    project: Path = result.project  # type: ignore[attr-defined]
    assert result.returncode == 0, result.stderr
    assert "scaffold selected: scaffold-enoch-worker-artifact" in result.stderr
    assert "scaffold bootstrap ok" in result.stderr
    assert (project / "run_notes.md").is_file()
    assert (project / ".enoch" / "project_decision.json").is_file()
    assert (project / ".omx" / "project_decision.json").is_file()
    scaffold_used = (project / ".scaffold-used.yaml").read_text(encoding="utf-8")
    assert "scaffold_name: scaffold-enoch-worker-artifact" in scaffold_used
    assert f"scaffold_commit: {scaffold_commit}" in scaffold_used
    assert f"scaffold_source_url: file://{scaffold_src}" in scaffold_used
    session = json.loads(
        (project / ".enoch" / "session.json").read_text(encoding="utf-8")
    )
    assert session["session_id"] == "fake-session"


def test_codex_runner_bootstraps_default_scaffold_from_catalog_yaml(
    tmp_path: Path,
) -> None:
    scaffold_src, scaffold_commit = _create_scaffold_repo(
        tmp_path, "scaffold-enoch-worker-artifact"
    )
    catalog = _create_catalog_repo(
        tmp_path,
        default="scaffold-enoch-worker-artifact",
        scaffolds={"scaffold-enoch-worker-artifact": f"file://{scaffold_src}"},
        fmt="yaml",
    )
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_CATALOG_URL": f"file://{catalog}",
        },
    )

    project: Path = result.project  # type: ignore[attr-defined]
    assert result.returncode == 0, result.stderr
    assert "scaffold selected: scaffold-enoch-worker-artifact" in result.stderr
    scaffold_used = (project / ".scaffold-used.yaml").read_text(encoding="utf-8")
    assert "scaffold_name: scaffold-enoch-worker-artifact" in scaffold_used
    assert f"scaffold_commit: {scaffold_commit}" in scaffold_used
    assert f"scaffold_source_url: file://{scaffold_src}" in scaffold_used


def test_codex_runner_bootstraps_explicit_scaffold_from_catalog(tmp_path: Path) -> None:
    default_src, _ = _create_scaffold_repo(tmp_path, "scaffold-enoch-worker-artifact")
    benchmark_src, benchmark_commit = _create_scaffold_repo(
        tmp_path, "scaffold-enoch-benchmark-results"
    )
    catalog = _create_catalog_repo(
        tmp_path,
        default="scaffold-enoch-worker-artifact",
        scaffolds={
            "scaffold-enoch-worker-artifact": f"file://{default_src}",
            "scaffold-enoch-benchmark-results": f"file://{benchmark_src}",
        },
    )
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_CATALOG_URL": f"file://{catalog}",
            "ENOCH_SCAFFOLD_NAME": "scaffold-enoch-benchmark-results",
        },
    )

    project: Path = result.project  # type: ignore[attr-defined]
    assert result.returncode == 0, result.stderr
    assert "scaffold selected: scaffold-enoch-benchmark-results" in result.stderr
    scaffold_used = (project / ".scaffold-used.yaml").read_text(encoding="utf-8")
    assert "scaffold_name: scaffold-enoch-benchmark-results" in scaffold_used
    assert f"scaffold_commit: {benchmark_commit}" in scaffold_used
    assert f"scaffold_source_url: file://{benchmark_src}" in scaffold_used


def test_codex_runner_can_still_bootstrap_direct_scaffold_url(tmp_path: Path) -> None:
    scaffold_src, scaffold_commit = _create_scaffold_repo(
        tmp_path, "scaffold-enoch-worker-artifact"
    )
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_URL": f"file://{scaffold_src}",
        },
    )

    project: Path = result.project  # type: ignore[attr-defined]
    assert result.returncode == 0, result.stderr
    assert "scaffold selected: direct-url" in result.stderr
    scaffold_used = (project / ".scaffold-used.yaml").read_text(encoding="utf-8")
    assert f"scaffold_commit: {scaffold_commit}" in scaffold_used
    assert f"scaffold_source_url: file://{scaffold_src}" in scaffold_used


def test_codex_runner_unknown_scaffold_name_fails_clearly(tmp_path: Path) -> None:
    scaffold_src, _ = _create_scaffold_repo(tmp_path, "scaffold-enoch-worker-artifact")
    catalog = _create_catalog_repo(
        tmp_path,
        default="scaffold-enoch-worker-artifact",
        scaffolds={"scaffold-enoch-worker-artifact": f"file://{scaffold_src}"},
    )
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_CATALOG_URL": f"file://{catalog}",
            "ENOCH_SCAFFOLD_NAME": "missing-scaffold",
        },
    )

    project: Path = result.project  # type: ignore[attr-defined]
    assert result.returncode == 2
    assert "unknown scaffold: missing-scaffold" in result.stderr
    assert not (project / ".scaffold-used.yaml").exists()


def test_codex_runner_skips_scaffold_when_disabled(tmp_path: Path) -> None:
    result = _run_runner(tmp_path, {"ENOCH_SCAFFOLD_BOOTSTRAP": "0"})

    project: Path = result.project  # type: ignore[attr-defined]
    assert result.returncode == 0, result.stderr
    assert not (project / ".scaffold-used.yaml").exists()
