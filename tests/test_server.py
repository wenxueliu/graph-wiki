"""HTTP tests for the read-only graph viewer server."""

from __future__ import annotations

import http.client
import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from graph_wiki.server import make_server

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault / "concepts/ml.md",
        """---
title: Machine Learning
category: concepts
tags: [ml, ai]
summary: The study of algorithms that improve through experience.
---
# ML
[[entities/nn|Neural Networks @implements]]
[[concepts/dl]]
""",
    )
    _write(
        vault / "concepts/dl.md",
        """---
title: Deep Learning
category: concepts
tags: [ml, deep-learning]
---
# DL
[[concepts/ml]] is the broader field.
""",
    )
    _write(
        vault / "entities/nn.md",
        """---
title: Neural Networks
category: entities
tags: [ml, architecture]
---
# NN
[[concepts/ml]] implemented via NNs.
""",
    )
    return vault


@pytest.fixture()
def server(tmp_path: Path):
    vault = _make_vault(tmp_path)
    instance, _service = make_server(
        vault, host="127.0.0.1", port=0, refresh_interval=0.0
    )
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{instance.server_address[1]}"
    try:
        yield base, vault, instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=5)


def _get(url: str, **headers: str):
    request = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(request, timeout=5)


def _json(response) -> dict:
    return json.loads(response.read().decode("utf-8"))


def _error_status(url: str, **headers: str) -> tuple[int, dict]:
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=5
        )
    response = caught.value
    raw = response.read()
    body = json.loads(raw.decode("utf-8")) if raw else {}
    return response.code, body


def test_serves_the_html_shell(server) -> None:
    base, _vault, _instance = server
    response = _get(base + "/")
    body = response.read().decode("utf-8")

    assert response.status == 200
    assert response.headers.get_content_type() == "text/html"
    assert 'id="graph"' in body
    assert 'src="/static/vis-network.min.js"' in body
    assert "Content-Security-Policy" in response.headers
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers.get("Access-Control-Allow-Origin") is None


def test_serves_static_assets(server) -> None:
    base, _vault, _instance = server
    for path, content_type in (
        ("/static/app.js", "text/javascript"),
        ("/static/style.css", "text/css"),
        ("/static/vis-network.min.js", "text/javascript"),
        ("/favicon.svg", "image/svg+xml"),
    ):
        response = _get(base + path)
        assert response.status == 200
        assert response.headers.get_content_type() == content_type
        assert response.read()


def test_vendored_network_library_is_offline_and_complete() -> None:
    vendor = ROOT / "graph_wiki" / "web" / "vendor" / "vis-network.min.js"
    assert vendor.is_file()
    assert vendor.stat().st_size > 200_000


def test_ui_assets_do_not_reference_external_urls() -> None:
    for name in ("index.html", "app.js", "style.css"):
        text = (ROOT / "graph_wiki" / "web" / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://", text), name


def test_api_graph_returns_payload(server) -> None:
    base, _vault, _instance = server
    response = _get(base + "/api/graph")
    payload = _json(response)

    assert response.status == 200
    assert response.headers.get_content_type() == "application/json"
    assert payload["schema_version"] == 1
    assert payload["stats"]["pages"] == 3
    assert [node["id"] for node in payload["nodes"]] == [
        "concepts/dl",
        "concepts/ml",
        "entities/nn",
    ]
    assert any(edge["relation"] == "implements" for edge in payload["edges"])
    assert response.headers["ETag"]


def test_api_graph_supports_conditional_get(server) -> None:
    base, _vault, _instance = server
    first = _get(base + "/api/graph")
    etag = first.headers["ETag"]
    first.read()

    status, payload = _error_status(base + "/api/graph", **{"If-None-Match": etag})
    assert status == 304
    assert payload == {}


def test_api_graph_head_has_no_body(server) -> None:
    base, _vault, _instance = server
    request = urllib.request.Request(base + "/api/graph", method="HEAD")
    response = urllib.request.urlopen(request, timeout=5)

    assert response.status == 200
    assert int(response.headers["Content-Length"]) > 0
    assert response.read() == b""


def test_api_page_returns_body(server) -> None:
    base, _vault, _instance = server
    response = _get(base + "/api/page?id=concepts/ml")
    payload = _json(response)

    assert response.status == 200
    assert payload["id"] == "concepts/ml"
    assert "title: Machine Learning" in payload["frontmatter"]
    assert "# ML" in payload["body"]
    assert payload["content_trust"] == "untrusted_reference_data"
    assert payload["obsidian_uri"].startswith("obsidian://open?path=")


def test_api_page_accepts_md_suffix(server) -> None:
    base, _vault, _instance = server
    response = _get(base + "/api/page?id=concepts/ml.md")
    assert _json(response)["id"] == "concepts/ml"


def test_api_page_supports_conditional_get(server) -> None:
    base, _vault, _instance = server
    first = _get(base + "/api/page?id=concepts/ml")
    etag = first.headers["ETag"]
    first.read()

    status, payload = _error_status(
        base + "/api/page?id=concepts/ml", **{"If-None-Match": etag}
    )
    assert status == 304
    assert payload == {}


def test_api_page_requires_an_id(server) -> None:
    base, _vault, _instance = server
    status, payload = _error_status(base + "/api/page")
    assert status == 400
    assert payload["error"]["code"] == "invalid_request"


def test_api_page_unknown_id_is_404(server) -> None:
    base, _vault, _instance = server
    status, payload = _error_status(base + "/api/page?id=missing/page")
    assert status == 404
    assert payload["error"]["code"] == "not_found"


def test_api_page_rejects_traversal(server) -> None:
    base, _vault, _instance = server
    status, _payload = _error_status(base + "/api/page?id=../../etc/passwd")
    assert status == 404


def test_unknown_static_and_api_routes_are_404(server) -> None:
    base, _vault, _instance = server
    with pytest.raises(urllib.error.HTTPError) as caught:
        _get(base + "/static/../server.py")
    assert caught.value.code == 404

    status, payload = _error_status(base + "/api/nope")
    assert status == 404
    assert payload["error"]["code"] == "not_found"


def test_post_is_rejected(server) -> None:
    base, _vault, _instance = server
    request = urllib.request.Request(base + "/api/graph", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=5)
    response = caught.value
    assert response.code == 405
    assert "GET" in response.headers["Allow"]
    assert json.loads(response.read().decode("utf-8"))["error"]["code"] == "method_not_allowed"


def test_host_header_check_blocks_dns_rebinding(server) -> None:
    _base, _vault, instance = server
    connection = http.client.HTTPConnection(
        "127.0.0.1", instance.server_address[1], timeout=5
    )
    try:
        connection.putrequest("GET", "/api/graph", skip_host=True)
        connection.putheader("Host", "evil.example")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 403
        body = json.loads(response.read().decode("utf-8"))
        assert body["error"]["code"] == "forbidden"
    finally:
        connection.close()


def test_viewer_does_not_write_to_the_vault(server) -> None:
    base, vault, _instance = server
    _get(base + "/api/graph").read()
    _get(base + "/api/page?id=concepts/ml").read()

    assert not (vault / ".obsidian").exists()


def test_cli_parser_exposes_serve() -> None:
    from graph_wiki.cli import build_parser

    args = build_parser().parse_args(
        ["serve", "--vault", "/tmp/vault", "--port", "0", "--verbose"]
    )
    assert args.func.__name__ == "cmd_serve"
    assert args.port == 0
    assert args.verbose is True
