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
    tmp_path: Path,
    env_updates: dict[str, str],
    *,
    prompt_text: str = "do work\n",
    project_name: str = "project",
    project_id: str = "test-project",
) -> subprocess.CompletedProcess[str]:
    prompt = tmp_path / f"{project_name}-prompt.txt"
    prompt.write_text(prompt_text, encoding="utf-8")
    project = tmp_path / project_name
    project.mkdir()
    runner = Path(__file__).resolve().parents[1] / "deploy" / "enoch_codex_runner.sh"
    env = os.environ.copy()
    env.update(
        {
            "CODEX_BIN": str(_create_fake_codex(tmp_path)),
            "ENOCH_SCAFFOLD_ALLOW_FILE_URLS": "1",
        }
    )
    env.update(env_updates)
    result = subprocess.run(
        [
            str(runner),
            "--run-id",
            "test-run",
            "--project-id",
            project_id,
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


def _create_full_routing_catalog(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    scaffold_names = [
        "scaffold-enoch-worker-artifact",
        "scaffold-enoch-benchmark-results",
        "scaffold-enoch-memory-agent-eval",
        "scaffold-enoch-gb10-gpu-experiment",
        "scaffold-enoch-agent-evidence-ledger",
        "scaffold-enoch-speculative-decoding",
    ]
    scaffolds: dict[str, str] = {}
    commits: dict[str, str] = {}
    for name in scaffold_names:
        src, commit = _create_scaffold_repo(tmp_path, name)
        scaffolds[name] = f"file://{src}"
        commits[name] = commit
    catalog = _create_catalog_repo(
        tmp_path,
        default="scaffold-enoch-worker-artifact",
        scaffolds=scaffolds,
        fmt="yaml",
    )
    return catalog, commits


def test_codex_runner_routes_scaffold_from_prompt_intent(tmp_path: Path) -> None:
    catalog, commits = _create_full_routing_catalog(tmp_path)
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")
    cases = [
        (
            "evidence-ledger",
            "Build an evidence-ledger for falsifiable-claim drift-trap review.",
            "scaffold-enoch-agent-evidence-ledger",
            "matched evidence-ledger/falsifiable-claim/drift-trap intent",
        ),
        (
            "memory-eval",
            "Evaluate memory retrieval and replay for operator-doctrine regressions.",
            "scaffold-enoch-memory-agent-eval",
            "matched memory/retrieval/operator-doctrine/replay intent",
        ),
        (
            "gb10-gpu",
            "Run GB10 GPU CUDA VRAM profiling for model serving.",
            "scaffold-enoch-gb10-gpu-experiment",
            "matched GB10/GPU/VRAM/CUDA/profiling intent",
        ),
        (
            "speculative-decoding",
            "Measure speculative decoding with KV-cache suffix ngram long-context compression.",
            "scaffold-enoch-speculative-decoding",
            "matched speculative-decoding/KV-cache/suffix/ngram/long-context-compression intent",
        ),
        (
            "benchmark-results",
            "Produce benchmark metrics baseline failure-cases for the release.",
            "scaffold-enoch-benchmark-results",
            "matched benchmark/metrics/baseline/failure-cases intent",
        ),
    ]
    for project_name, prompt_text, expected, reason in cases:
        result = _run_runner(
            tmp_path,
            {
                "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
                "ENOCH_SCAFFOLD_CATALOG_URL": f"file://{catalog}",
            },
            prompt_text=prompt_text,
            project_name=project_name,
            project_id=project_name,
        )
        project: Path = result.project  # type: ignore[attr-defined]
        assert result.returncode == 0, result.stderr
        assert f"scaffold selected: {expected}" in result.stderr
        scaffold_used = (project / ".scaffold-used.yaml").read_text(encoding="utf-8")
        assert f"scaffold_name: {expected}" in scaffold_used
        assert f"scaffold_selected_name: {expected}" in scaffold_used
        assert f"scaffold_commit: {commits[expected]}" in scaffold_used
        assert f"scaffold_routing_reason: {reason}" in scaffold_used
        assert "scaffold_routing_deviation: none" in scaffold_used
        assert "scaffold_catalog_commit:" in scaffold_used


def test_codex_runner_routes_unknown_intent_to_fallback_default(tmp_path: Path) -> None:
    catalog, commits = _create_full_routing_catalog(tmp_path)
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_CATALOG_URL": f"file://{catalog}",
        },
        prompt_text="Summarize miscellaneous project notes with no special domain.",
        project_name="unknown-fallback",
        project_id="unknown-fallback",
    )

    project: Path = result.project  # type: ignore[attr-defined]
    assert result.returncode == 0, result.stderr
    scaffold_used = (project / ".scaffold-used.yaml").read_text(encoding="utf-8")
    assert "scaffold_selected_name: scaffold-enoch-worker-artifact" in scaffold_used
    assert (
        f"scaffold_commit: {commits['scaffold-enoch-worker-artifact']}" in scaffold_used
    )
    assert (
        "scaffold_routing_reason: fallback to catalog default: no routing rule matched"
        in scaffold_used
    )
    assert "scaffold_routing_deviation: fallback-default" in scaffold_used


def test_codex_runner_explicit_scaffold_name_overrides_intent_routing(
    tmp_path: Path,
) -> None:
    catalog, _ = _create_full_routing_catalog(tmp_path)
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_CATALOG_URL": f"file://{catalog}",
            "ENOCH_SCAFFOLD_NAME": "scaffold-enoch-benchmark-results",
        },
        prompt_text="This mentions GB10 GPU CUDA but explicit override should win.",
        project_name="explicit-override",
        project_id="explicit-override",
    )

    project: Path = result.project  # type: ignore[attr-defined]
    assert result.returncode == 0, result.stderr
    scaffold_used = (project / ".scaffold-used.yaml").read_text(encoding="utf-8")
    assert "scaffold_selected_name: scaffold-enoch-benchmark-results" in scaffold_used
    assert (
        "scaffold_routing_reason: explicit ENOCH_SCAFFOLD_NAME override"
        in scaffold_used
    )
    assert "scaffold_routing_deviation: explicit-override" in scaffold_used


def test_codex_runner_yaml_nested_clone_url_does_not_override_repo(
    tmp_path: Path,
) -> None:
    safe_src, safe_commit = _create_scaffold_repo(
        tmp_path, "scaffold-enoch-worker-artifact"
    )
    evil_src, _ = _create_scaffold_repo(tmp_path, "scaffold-enoch-evil")
    catalog = tmp_path / "nested-yaml-catalog"
    catalog.mkdir()
    (catalog / "catalog.yaml").write_text(
        "version: 0.1.0\n"
        "default: scaffold-enoch-worker-artifact\n"
        "scaffolds:\n"
        "  - name: scaffold-enoch-worker-artifact\n"
        f"    clone_url: file://{safe_src}\n"
        "    metadata:\n"
        f"      clone_url: file://{evil_src}\n"
        "selection_rules:\n"
        "  - nested metadata must not override clone_url\n",
        encoding="utf-8",
    )
    _commit_repo(catalog, "seed nested catalog")
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
    scaffold_used = (project / ".scaffold-used.yaml").read_text(encoding="utf-8")
    assert f"scaffold_source_url: file://{safe_src}" in scaffold_used
    assert f"scaffold_commit: {safe_commit}" in scaffold_used
    assert str(evil_src) not in scaffold_used


def test_codex_runner_rejects_untrusted_catalog_scaffold_url(tmp_path: Path) -> None:
    catalog = tmp_path / "untrusted-catalog"
    catalog.mkdir()
    (catalog / "catalog.json").write_text(
        json.dumps(
            {
                "default": "scaffold-enoch-worker-artifact",
                "scaffolds": [
                    {
                        "name": "scaffold-enoch-worker-artifact",
                        "clone_url": "https://evil.example/scaffolds/scaffold-enoch-worker-artifact.git",
                        "commit": "0" * 40,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _commit_repo(catalog, "seed untrusted catalog")
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_CATALOG_URL": f"file://{catalog}",
        },
    )

    assert result.returncode == 2
    assert "untrusted scaffold URL" in result.stderr


def test_codex_runner_rejects_commit_pin_mismatch(tmp_path: Path) -> None:
    scaffold_src, scaffold_commit = _create_scaffold_repo(
        tmp_path, "scaffold-enoch-worker-artifact"
    )
    wrong_commit = "f" * 40
    assert wrong_commit != scaffold_commit
    catalog = tmp_path / "pin-mismatch-catalog"
    catalog.mkdir()
    (catalog / "catalog.json").write_text(
        json.dumps(
            {
                "default": "scaffold-enoch-worker-artifact",
                "scaffolds": [
                    {
                        "name": "scaffold-enoch-worker-artifact",
                        "clone_url": f"file://{scaffold_src}",
                        "commit": wrong_commit,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _commit_repo(catalog, "seed mismatch catalog")
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_CATALOG_URL": f"file://{catalog}",
        },
    )

    assert result.returncode == 2
    assert "scaffold commit mismatch" in result.stderr


def test_codex_runner_rejects_untrusted_direct_scaffold_url(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("not-used-for-file-url\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_URL": "https://evil.example/scaffolds/scaffold-enoch-worker-artifact.git",
            "ENOCH_SCAFFOLD_COMMIT": "0" * 40,
        },
    )

    assert result.returncode == 2
    assert "untrusted scaffold URL" in result.stderr


def test_codex_runner_rejects_plain_http_catalog_without_explicit_opt_in(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("secret-token\n", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        {
            "ENOCH_SCAFFOLD_TOKEN_FILE": str(token_file),
            "ENOCH_SCAFFOLD_CATALOG_URL": "http://100.114.53.78:8000/scaffolds/scaffold-catalog.git",
            "ENOCH_SCAFFOLD_ALLOWED_BASE_URLS": "http://100.114.53.78:8000/scaffolds/",
        },
    )

    assert result.returncode == 2
    assert "plain HTTP requires ENOCH_SCAFFOLD_ALLOW_INSECURE_HTTP=1" in result.stderr
    assert "secret-token" not in result.stderr


def test_codex_runner_default_scaffold_transport_is_not_plain_http() -> None:
    runner = Path(__file__).resolve().parents[1] / "deploy" / "enoch_codex_runner.sh"
    source = runner.read_text(encoding="utf-8")
    assert (
        "ENOCH_SCAFFOLD_CATALOG_URL:-https://100.114.53.78:8000/scaffolds/scaffold-catalog.git"
        in source
    )
    assert (
        "ENOCH_SCAFFOLD_ALLOWED_BASE_URLS:-https://100.114.53.78:8000/scaffolds/"
        in source
    )
    assert "http://100.114.53.78:8000/" not in source
