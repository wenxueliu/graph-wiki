"""Role-scoped pack and access-gateway tests (stdlib only)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from graph_wiki import access
from graph_wiki import cli
from graph_wiki import pack as pack_mod


def write_page(
    vault: Path,
    relative: str,
    *,
    tags: tuple[str, ...] = ("test",),
    title: str = "Page",
    body: str = "body text",
) -> Path:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "---\n"
        f"title: {title}\n"
        "category: concepts\n"
        f"tags: [{', '.join(tags)}]\n"
        "sources: [manual]\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "summary: summary text\n"
        "lifecycle: verified\n"
        "---\n"
        f"# {title}\n\n{body}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path


def write_policy(vault: Path, roles: dict[str, list[str]], *, force: bool = True) -> Path:
    policy = {
        "version": 1,
        "default_exclude_tags": ["visibility/pii", "visibility/internal"],
        "roles": {name: {"exclude_tags": excludes} for name, excludes in roles.items()},
    }
    return access.write_policy(vault, policy, force=force)


def inventory_paths(pack_dir: Path) -> set[str]:
    rows = [
        json.loads(line)
        for line in (pack_dir / "inventory.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {row["path"] for row in rows}


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GRAPH_WIKI_CONFIG_DIR", str(tmp_path / "config"))
    root = tmp_path / "vault"
    write_page(root, "concepts/shared.md", title="Shared", body="shared content")
    write_page(root, "concepts/pii.md", tags=("test", "visibility/pii"), title="Pii", body="pii content")
    write_page(
        root,
        "concepts/internal.md",
        tags=("test", "visibility/internal"),
        title="Internal",
        body="internal content",
    )
    write_page(
        root,
        "concepts/finance.md",
        tags=("test", "role/finance"),
        title="Finance",
        body="finance secret",
    )
    write_page(root, "concepts/hr.md", tags=("test", "role/hr"), title="Hr", body="hr secret")
    write_policy(
        root,
        {
            "finance": ["visibility/pii"],
            "hr": ["visibility/pii", "visibility/internal"],
        },
    )
    return root


def store_for(tmp_path: Path) -> Path:
    return tmp_path / "store"


def build_all(vault: Path, store: Path) -> dict[str, dict[str, object]]:
    return {
        role: access.build_role_pack(vault, role, store=store)
        for role in access.policy_roles(access.load_policy(vault))
    }


def token_for(vault: Path, role: str, name: str = "alice") -> str:
    token, _record = access.create_token(name, role)
    return token


def test_policy_validation_fails_closed(vault: Path) -> None:
    with pytest.raises(access.AccessError):
        access.validate_policy({"version": 1, "roles": {"Finance": {}}})
    with pytest.raises(access.AccessError):
        access.validate_policy({"version": 1, "roles": {"finance": {"channel": "other"}}})
    with pytest.raises(access.AccessError):
        access.validate_policy({"version": 2, "roles": {}})
    with pytest.raises(access.AccessError):
        access.validate_policy({"version": 1, "roles": {}, "surprise": True})
    with pytest.raises(access.AccessError):
        access.role_config(access.load_policy(vault), "nobody")


def test_role_packs_are_physically_filtered(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    finance = pack_mod.resolve_pack(None, store=store, vault=vault, channel="role-finance")
    hr = pack_mod.resolve_pack(None, store=store, vault=vault, channel="role-hr")

    assert inventory_paths(finance) == {"concepts/shared.md", "concepts/internal.md", "concepts/finance.md"}
    assert inventory_paths(hr) == {"concepts/shared.md", "concepts/hr.md"}
    assert pack_mod.load_manifest(finance)["build"]["access_role"] == "finance"
    assert pack_mod.load_manifest(hr)["build"]["access_role"] == "hr"


def test_identical_visible_sets_do_not_share_role_metadata(vault: Path, tmp_path: Path) -> None:
    write_policy(vault, {"alpha": ["visibility/pii"], "beta": ["visibility/pii"]})
    for relative in ("concepts/finance.md", "concepts/hr.md"):
        (vault / relative).unlink()
    store = store_for(tmp_path)
    first = access.build_role_pack(vault, "alpha", store=store)
    second = access.build_role_pack(vault, "beta", store=store)

    assert first["pack_id"] != second["pack_id"] or first["version"] != second["version"]
    beta_dir = pack_mod.resolve_pack(None, store=store, vault=vault, channel="role-beta")
    assert pack_mod.load_manifest(beta_dir)["build"]["access_role"] == "beta"


def test_gateway_only_returns_role_pages(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    finance_token = token_for(vault, "finance")
    hr_token = token_for(vault, "hr", name="bob")

    finance = access.gateway_search(finance_token, "secret", vault=vault, store=store)
    hr = access.gateway_search(hr_token, "secret", vault=vault, store=store)

    assert {item["path"] for item in finance["results"]} <= {
        "concepts/shared.md",
        "concepts/internal.md",
        "concepts/finance.md",
    }
    assert {item["path"] for item in hr["results"]} <= {"concepts/shared.md", "concepts/hr.md"}
    assert "concepts/finance.md" not in {item["path"] for item in hr["results"]}
    assert finance["coverage"]["excluded_pages"] == 2
    assert finance["roles"] == ["finance"]
    assert finance["content_trust"] == "untrusted_reference_data"


def test_unknown_and_revoked_tokens_are_denied(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)

    with pytest.raises(access.AccessError) as missing:
        access.gateway_search("gw_not-a-real-token", "secret", vault=vault, store=store)
    assert missing.value.reason == "invalid_token"

    token = token_for(vault, "finance")
    access.revoke_token("alice")
    with pytest.raises(access.AccessError) as revoked:
        access.gateway_search(token, "secret", vault=vault, store=store)
    assert revoked.value.reason == "invalid_token"


def test_policy_change_invalidates_the_role_pack(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    token = token_for(vault, "hr")

    write_policy(vault, {"finance": ["visibility/pii"], "hr": ["visibility/pii"]})
    with pytest.raises(access.AccessError) as drift:
        access.gateway_search(token, "secret", vault=vault, store=store)
    assert drift.value.reason == "policy_drift"

    access.build_role_pack(vault, "hr", store=store)
    access.gateway_search(token, "secret", vault=vault, store=store)


def test_content_change_invalidates_the_role_pack(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    token = token_for(vault, "finance")

    write_page(vault, "concepts/new-finance.md", tags=("test", "role/finance"), body="new finance secret")
    with pytest.raises(access.AccessError) as drift:
        access.gateway_search(token, "secret", vault=vault, store=store)
    assert drift.value.reason == "content_drift"

    # The policy-only check still passes, which is the documented escape hatch.
    access.gateway_search(token, "secret", vault=vault, store=store, skip_drift=True)
    access.build_role_pack(vault, "finance", store=store)
    access.gateway_search(token, "secret", vault=vault, store=store)


def test_missing_pack_fails_closed(vault: Path, tmp_path: Path) -> None:
    token = token_for(vault, "finance")
    with pytest.raises(access.AccessError) as missing:
        access.gateway_search(token, "secret", vault=vault, store=store_for(tmp_path))
    assert missing.value.reason == "pack_missing"


def test_sidecar_tampering_is_detected(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    access.build_role_pack(vault, "finance", store=store)
    token = token_for(vault, "finance")
    pack_dir = pack_mod.resolve_pack(None, store=store, vault=vault, channel="role-finance")
    sidecar = json.loads((pack_dir / "access.json").read_text(encoding="utf-8"))
    sidecar["policy_sha256"] = "sha256:" + "0" * 64
    os.chmod(pack_dir / "access.json", 0o644)
    (pack_dir / "access.json").write_text(json.dumps(sidecar), encoding="utf-8")

    with pytest.raises(access.AccessError) as tampered:
        access.gateway_search(token, "secret", vault=vault, store=store)
    assert tampered.value.reason == "policy_drift"


def test_tokens_store_only_hashes_and_are_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPH_WIKI_CONFIG_DIR", str(tmp_path / "config"))
    token, record = access.create_token("alice", "finance")
    path = access.principals_file()
    text = path.read_text(encoding="utf-8")

    assert token.startswith(access.TOKEN_PREFIX)
    assert token not in text
    assert record["token_sha256"] in text
    if os.name == "posix":
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
    assert access.resolve_principal(token)["roles"] == ["finance"]
    assert all("token_sha256" not in row for row in access.list_principals())


def test_audit_records_decisions_without_tokens(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    token = token_for(vault, "finance")

    access.gateway_search(token, "secret", vault=vault, store=store)
    with pytest.raises(access.AccessError):
        access.gateway_search("gw_bad-token-value", "secret", vault=vault, store=store)

    rows = access.read_audit(10)
    assert [row["outcome"] for row in rows] == ["ok", "denied"]
    assert rows[0]["principal"] == "alice"
    assert rows[0]["returned"]
    assert token not in access.audit_file().read_text(encoding="utf-8")


def test_status_reports_current_and_stale_roles(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    report = access.role_status(vault, store=store)
    assert {entry["role"] for entry in report["roles"]} == {"finance", "hr"}
    assert all(entry["policy_current"] and entry["content_current"] for entry in report["roles"])

    write_page(vault, "concepts/new-finance.md", tags=("test", "role/finance"), body="new")
    stale = access.role_status(vault, store=store)
    finance = next(entry for entry in stale["roles"] if entry["role"] == "finance")
    hr = next(entry for entry in stale["roles"] if entry["role"] == "hr")
    assert finance["content_current"] is False
    assert hr["content_current"] is True


def test_cli_access_flow(vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = store_for(tmp_path)
    assert cli.main(["access", "build", "--vault", str(vault), "--all", "--store", str(store), "--json"]) == 0
    capsys.readouterr()

    assert (
        cli.main(
            [
                "access",
                "token",
                "create",
                "--vault",
                str(vault),
                "--name",
                "alice",
                "--role",
                "finance",
                "--json",
            ]
        )
        == 0
    )
    token = json.loads(capsys.readouterr().out)["token"]

    assert (
        cli.main(
            [
                "access",
                "search",
                "secret",
                "--vault",
                str(vault),
                "--store",
                str(store),
                "--token",
                token,
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["roles"] == ["finance"]
    assert {item["path"] for item in payload["results"]} <= {
        "concepts/shared.md",
        "concepts/internal.md",
        "concepts/finance.md",
    }

    assert cli.main(["access", "status", "--vault", str(vault), "--store", str(store), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["roles"][0]["policy_current"] is True

    assert cli.main(["access", "audit", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[-1]["outcome"] == "ok"


def test_status_strict_gates_unbuilt_and_stale_roles(
    vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = store_for(tmp_path)
    assert cli.main(["access", "status", "--vault", str(vault), "--store", str(store), "--strict"]) == 1
    capsys.readouterr()

    assert cli.main(["access", "build", "--vault", str(vault), "--all", "--store", str(store)]) == 0
    capsys.readouterr()
    assert cli.main(["access", "status", "--vault", str(vault), "--store", str(store), "--strict"]) == 0
    capsys.readouterr()

    write_page(vault, "concepts/late.md", tags=("test", "role/finance"), body="late")
    assert cli.main(["access", "status", "--vault", str(vault), "--store", str(store), "--strict"]) == 1


def test_cli_search_denies_an_unknown_token(
    vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = store_for(tmp_path)
    cli.main(["access", "build", "--vault", str(vault), "--all", "--store", str(store)])
    capsys.readouterr()

    code = cli.main(
        [
            "access",
            "search",
            "secret",
            "--vault",
            str(vault),
            "--store",
            str(store),
            "--token",
            "gw_unknown",
        ]
    )
    assert code == 1
    assert "access denied" in capsys.readouterr().err


def test_multi_role_token_searches_all_granted_packs(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    token, record = access.create_token("carol", ["finance", "hr"])

    assert record["roles"] == ["finance", "hr"]
    assert access.resolve_principal(token)["roles"] == ["finance", "hr"]

    payload = access.gateway_search(token, "content", vault=vault, store=store)
    paths = [item["path"] for item in payload["results"]]
    assert paths.count("concepts/shared.md") == 1
    shared = next(item for item in payload["results"] if item["path"] == "concepts/shared.md")
    assert shared["granted_by"] == ["finance", "hr"]
    assert payload["coverage"]["visible_pages"] == 4
    assert payload["coverage"]["excluded_pages"] == 1
    assert {item["role"] for item in payload["packs"]} == {"finance", "hr"}

    narrowed = access.gateway_search(token, "content", vault=vault, store=store, role="hr")
    assert narrowed["roles"] == ["hr"]
    assert {item["path"] for item in narrowed["results"]} <= {"concepts/shared.md", "concepts/hr.md"}


def test_multi_role_inventory_and_page_access(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    token, _record = access.create_token("carol", ["finance", "hr"])

    inventory = access.gateway_inventory(token, vault=vault, store=store)
    by_path = {row["path"]: row for row in inventory["pages"]}
    assert inventory["total"] == 4
    assert by_path["concepts/shared.md"]["granted_by"] == ["finance", "hr"]
    assert by_path["concepts/finance.md"]["granted_by"] == ["finance"]
    assert "concepts/pii.md" not in by_path

    page = access.gateway_page(token, "concepts/finance.md", vault=vault, store=store)
    assert page["title"] == "Finance"
    assert page["granted_by"] == ["finance"]
    assert "finance secret" in page["body"]
    assert page["content_trust"] == "untrusted_reference_data"

    with pytest.raises(access.AccessError) as denied:
        access.gateway_page(token, "concepts/pii.md", vault=vault, store=store)
    assert denied.value.reason == "page_denied"

    with pytest.raises(access.AccessError) as traversal:
        access.gateway_page(token, "../outside.md", vault=vault, store=store)
    assert traversal.value.reason == "invalid_page_path"


def test_multi_role_search_denies_a_stale_pack(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    token, _record = access.create_token("carol", ["finance", "hr"])

    write_page(vault, "concepts/new-finance.md", tags=("test", "role/finance"), body="new finance secret")
    with pytest.raises(access.AccessError) as drift:
        access.gateway_search(token, "content", vault=vault, store=store)
    assert drift.value.reason == "content_drift"


def test_role_cannot_be_requested_without_a_grant(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    token = token_for(vault, "finance")

    with pytest.raises(access.AccessError) as denied:
        access.gateway_search(token, "content", vault=vault, store=store, role="hr")
    assert denied.value.reason == "role_not_granted"


def test_legacy_single_role_principal_records_still_resolve(vault: Path, tmp_path: Path) -> None:
    store = store_for(tmp_path)
    build_all(vault, store)
    token = "gw_legacy-token-value"
    access.principals_file().parent.mkdir(parents=True, exist_ok=True)
    access.principals_file().write_text(
        json.dumps(
            {
                "version": 1,
                "principals": {
                    "legacy": {
                        "role": "finance",
                        "token_sha256": access._sha256_text(token),
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "revoked_at": None,
                        "vault_id": None,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert access.resolve_principal(token)["roles"] == ["finance"]
    payload = access.gateway_search(token, "content", vault=vault, store=store)
    assert payload["roles"] == ["finance"]
