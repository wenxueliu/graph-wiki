"""Config-directory relocation and unified vault resolution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from obsidian_wiki import config_paths


def run_cli(
    home: Path, *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("OBSIDIAN_WIKI_CONFIG_DIR", None)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _page(vault: Path, name: str, *, title: str, summary: str) -> None:
    (vault / f"{name}.md").write_text(
        "---\n"
        f"title: {title}\n"
        "category: concepts\n"
        "tags: [test]\n"
        "sources: [manual]\n"
        "created: 2026-07-01\n"
        "updated: 2026-07-01\n"
        f"summary: {summary}\n"
        "---\n"
        f"# {title}\n",
        encoding="utf-8",
    )


# ── config_paths ─────────────────────────────────────────────────────────────


def test_config_dir_env_override_absolute(
    monkeypatch, tmp_path: Path
) -> None:
    target = tmp_path / "cfg"
    monkeypatch.setenv("OBSIDIAN_WIKI_CONFIG_DIR", str(target))
    monkeypatch.chdir(tmp_path)

    assert config_paths.resolve_config_dir(default=tmp_path / "default") == target.resolve()


def test_config_dir_env_override_relative_to_cwd(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OBSIDIAN_WIKI_CONFIG_DIR", ".wiki-config")
    monkeypatch.chdir(tmp_path)

    assert (
        config_paths.resolve_config_dir(default=tmp_path / "default")
        == (tmp_path / ".wiki-config").resolve()
    )


def test_config_dir_from_nearest_dotenv_is_dotenv_relative(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    project = home / "project"
    nested = project / "a" / "b"
    nested.mkdir(parents=True)
    (project / ".env").write_text(
        "OBSIDIAN_WIKI_CONFIG_DIR=.wiki-config\n", encoding="utf-8"
    )
    monkeypatch.delenv("OBSIDIAN_WIKI_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(nested)

    assert (
        config_paths.resolve_config_dir(default=home / ".obsidian-wiki")
        == (project / ".wiki-config").resolve()
    )


def test_process_env_beats_dotenv(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "project"
    project.mkdir(parents=True)
    (project / ".env").write_text(
        "OBSIDIAN_WIKI_CONFIG_DIR=from-dotenv\n", encoding="utf-8"
    )
    monkeypatch.setenv("OBSIDIAN_WIKI_CONFIG_DIR", str(tmp_path / "from-env"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)

    assert config_paths.resolve_config_dir(
        default=home / ".obsidian-wiki"
    ) == (tmp_path / "from-env").resolve()


def test_config_dir_defaults_when_unset(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("OBSIDIAN_WIKI_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)

    assert config_paths.resolve_config_dir(
        default=home / ".obsidian-wiki"
    ) == (home / ".obsidian-wiki").resolve()


def test_cli_config_dir_walks_up_from_explicit_start(
    monkeypatch, tmp_path: Path
) -> None:
    from obsidian_wiki import cli

    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    (project / ".env").write_text(
        "OBSIDIAN_WIKI_CONFIG_DIR=.wiki-config\n", encoding="utf-8"
    )
    monkeypatch.delenv("OBSIDIAN_WIKI_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    assert cli.config_dir(start=nested) == (project / ".wiki-config").resolve()


# ── CLI: project-local configuration ─────────────────────────────────────────


def test_query_reads_vault_from_project_dotenv(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "project"
    vault = tmp_path / "vault"
    vault.mkdir()
    project.mkdir(parents=True)
    _page(vault, "transformer", title="Transformer", summary="Self-attention model.")
    (project / ".env").write_text(
        f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8"
    )

    proc = run_cli(home, "query", "transformer", "--json", cwd=project)

    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert any(item["page"] == "transformer.md" for item in data["candidates"])


def test_context_pack_reads_named_profile_from_project_config_dir(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = home / "project"
    vault = tmp_path / "work-vault"
    vault.mkdir()
    local_config = project / ".wiki-config"
    local_config.mkdir(parents=True)
    (vault / "auth.md").write_text(
        "# Authentication\n\nUse short-lived access tokens.\n", encoding="utf-8"
    )
    (project / ".env").write_text(
        "OBSIDIAN_WIKI_CONFIG_DIR=.wiki-config\n"
        "OBSIDIAN_VAULT_PATH=/nonexistent/ignored\n",
        encoding="utf-8",
    )
    (local_config / "config.work").write_text(
        f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8"
    )

    proc = run_cli(home, "context-pack", "authentication", "--vault", "@work", cwd=project)

    assert proc.returncode == 0, proc.stderr
    assert "short-lived access tokens" in proc.stdout


def test_doctor_reports_project_dotenv_without_global_config(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = home / "project"
    vault = tmp_path / "vault"
    vault.mkdir()
    project.mkdir(parents=True)
    (project / ".env").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")

    proc = run_cli(home, "doctor", cwd=project)

    assert "OBSIDIAN_VAULT_PATH is not set" not in proc.stdout
    assert str(vault) in proc.stdout
    assert not (home / ".obsidian-wiki").exists()


def test_setup_writes_config_inside_project_config_dir(
    monkeypatch, tmp_path: Path
) -> None:
    import obsidian_wiki.cli as cli

    monkeypatch.setenv("OBSIDIAN_WIKI_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.chdir(tmp_path)

    target = cli.write_config(str(tmp_path / "vault"), "default")

    assert target == (tmp_path / "cfg" / "config")
    assert f'OBSIDIAN_VAULT_PATH="{tmp_path / "vault"}"' in target.read_text()


def test_project_dotenv_suppresses_never_ran_setup_warning(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = home / "project"
    vault = tmp_path / "vault"
    vault.mkdir()
    project.mkdir(parents=True)
    _page(vault, "transformer", title="Transformer", summary="Self-attention model.")
    (project / ".env").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")

    proc = run_cli(home, "query", "transformer", "--json", cwd=project)

    assert proc.returncode == 0, proc.stderr
    assert "setup has never been run" not in proc.stderr
