"""Read-only local HTTP server for the graph viewer.

The server is intentionally small and stdlib-only: it serves one HTML page,
its static assets, and the two JSON endpoints that page needs.  It never
accepts writes, never lists directories, and binds to loopback by default.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import traceback
import webbrowser
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from graph_wiki import __version__
from graph_wiki.viewer import (
    DEFAULT_PAGE_MAX_BYTES,
    GraphService,
    PageNotFound,
    ViewerError,
)

WEB_ROOT = Path(__file__).with_name("web")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}
# vis-network injects a small <style> element for its tooltip and controls.
# Inline styles are allowed; scripts stay locked to same-origin assets.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

# route -> (file under WEB_ROOT, content type, cache control)
STATIC_ROUTES: dict[str, tuple[str, str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8", "no-cache"),
    "/index.html": ("index.html", "text/html; charset=utf-8", "no-cache"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml", "public, max-age=86400"),
    "/static/app.js": (
        "app.js",
        "text/javascript; charset=utf-8",
        "public, max-age=3600",
    ),
    "/static/style.css": (
        "style.css",
        "text/css; charset=utf-8",
        "public, max-age=3600",
    ),
    "/static/vis-network.min.js": (
        "vendor/vis-network.min.js",
        "text/javascript; charset=utf-8",
        "public, max-age=86400",
    ),
}


@lru_cache(maxsize=16)
def _static_bytes(relative: str) -> bytes:
    return (WEB_ROOT / relative).read_bytes()


class ViewerHTTPServer(ThreadingHTTPServer):
    """Threaded server carrying the vault service and bind context."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        service: GraphService,
        verbose: bool = False,
        bound_host: str = "127.0.0.1",
    ) -> None:
        self.service = service
        self.verbose = verbose
        self.bound_host = bound_host
        super().__init__(server_address, handler_class)


class ViewerHandler(BaseHTTPRequestHandler):
    """Serve the viewer shell and its read-only JSON endpoints."""

    server_version = f"graph-wiki-viewer/{__version__}"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def version_string(self) -> str:
        return self.server_version

    # -- HTTP verbs -------------------------------------------------------

    def do_GET(self) -> None:
        self._handle(head=False)

    def do_HEAD(self) -> None:
        self._handle(head=True)

    def do_POST(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    # -- request plumbing -------------------------------------------------

    def log_message(self, format: str, *args: object) -> None:
        if getattr(self.server, "verbose", False):
            super().log_message(format, *args)

    def _handle(self, *, head: bool) -> None:
        try:
            status, headers, body = self._dispatch()
        except PageNotFound as exc:
            status = HTTPStatus.NOT_FOUND
            headers = {"Cache-Control": "no-cache"}
            body = _error_body("not_found", str(exc))
        except ViewerError as exc:
            status = HTTPStatus.BAD_REQUEST
            headers = {"Cache-Control": "no-cache"}
            body = _error_body("invalid_request", str(exc))
        except (ValueError, UnicodeError) as exc:
            status = HTTPStatus.BAD_REQUEST
            headers = {"Cache-Control": "no-cache"}
            body = _error_body("invalid_request", str(exc))
        except Exception as exc:  # pragma: no cover - defensive boundary
            if getattr(self.server, "verbose", False):
                traceback.print_exc()
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            headers = {"Cache-Control": "no-store"}
            body = _error_body("internal_error", "the viewer could not read the vault")
            if not getattr(self.server, "verbose", False):
                print(f"graph-wiki viewer: {exc}", file=sys.stderr)

        self._respond(status, headers, body, head=head)

    def _dispatch(self) -> tuple[int, dict[str, str], bytes]:
        if not self._host_allowed():
            return (
                HTTPStatus.FORBIDDEN,
                {"Cache-Control": "no-store"},
                _error_body("forbidden", "unexpected Host header"),
            )

        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=True)

        if path == "/api/graph":
            return self._graph_response()
        if path == "/api/page":
            return self._page_response(query)
        if path in STATIC_ROUTES:
            return self._static_response(path)
        if path == "/favicon.ico":
            return HTTPStatus.NO_CONTENT, {}, b""
        if path.startswith("/api/"):
            return (
                HTTPStatus.NOT_FOUND,
                {"Cache-Control": "no-cache"},
                _error_body("not_found", f"unknown API route: {path}"),
            )
        return (
            HTTPStatus.NOT_FOUND,
            {"Cache-Control": "no-store"},
            b"not found",
        )

    def _host_allowed(self) -> bool:
        bound = getattr(self.server, "bound_host", "")
        if bound not in LOOPBACK_HOSTS:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return True
        if host.startswith("["):
            hostname = host.split("]", 1)[0] + "]"
        elif host.count(":") == 1:
            hostname = host.split(":", 1)[0]
        else:
            hostname = host
        return hostname in LOOPBACK_HOSTS

    def _respond(
        self,
        status: int,
        headers: dict[str, str],
        body: bytes,
        *,
        head: bool,
    ) -> None:
        self.send_response(int(status))
        for key, value in {**SECURITY_HEADERS, **headers}.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head and body:
            self.wfile.write(body)

    def _method_not_allowed(self) -> None:
        body = _error_body(
            "method_not_allowed", "the viewer is read-only; use GET or HEAD"
        )
        # A rejected request may still carry a body.  Close the connection
        # instead of trying to parse it as the next keep-alive request.
        self.close_connection = True
        self._respond(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"Allow": "GET, HEAD", "Cache-Control": "no-store"},
            body,
            head=False,
        )

    # -- responses --------------------------------------------------------

    def _static_response(self, path: str) -> tuple[int, dict[str, str], bytes]:
        relative, content_type, cache_control = STATIC_ROUTES[path]
        try:
            body = _static_bytes(relative)
        except OSError as exc:
            raise RuntimeError(f"viewer asset is missing: {relative}") from exc
        headers = {
            "Content-Type": content_type,
            "Cache-Control": cache_control,
        }
        if content_type.startswith("text/html"):
            headers["Content-Security-Policy"] = CSP
        return HTTPStatus.OK, headers, body

    def _graph_response(self) -> tuple[int, dict[str, str], bytes]:
        payload = self.server.service.graph()
        body = _json_bytes(payload)
        etag = _quote_etag(payload["vault"]["fingerprint"])
        if self._matches_etag(etag):
            return HTTPStatus.NOT_MODIFIED, {"ETag": etag}, b""
        return (
            HTTPStatus.OK,
            {
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-cache",
                "ETag": etag,
            },
            body,
        )

    def _page_response(
        self, query: dict[str, list[str]]
    ) -> tuple[int, dict[str, str], bytes]:
        page_id = (query.get("id") or [""])[0].strip()
        if page_id.endswith(".md"):
            page_id = page_id[:-3]
        if not page_id:
            return (
                HTTPStatus.BAD_REQUEST,
                {"Cache-Control": "no-cache"},
                _error_body(
                    "invalid_request",
                    "pass ?id=<page id>, for example ?id=concepts/transformers",
                ),
            )

        max_bytes = DEFAULT_PAGE_MAX_BYTES
        raw_limit = (query.get("max_bytes") or [""])[0].strip()
        if raw_limit:
            max_bytes = int(raw_limit)

        payload = self.server.service.page(page_id, max_bytes=max_bytes)
        body = _json_bytes(payload)
        digest = hashlib.sha256(
            f"{payload['path']}\0{payload['frontmatter']}\0{payload['body']}".encode("utf-8")
        ).hexdigest()[:32]
        etag = _quote_etag(digest)
        if self._matches_etag(etag):
            return HTTPStatus.NOT_MODIFIED, {"ETag": etag}, b""
        return (
            HTTPStatus.OK,
            {
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-cache",
                "ETag": etag,
            },
            body,
        )

    def _matches_etag(self, etag: str) -> bool:
        header = self.headers.get("If-None-Match") or ""
        return etag in header


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _error_body(code: str, message: str) -> bytes:
    return _json_bytes({"error": {"code": code, "message": message}})


def _quote_etag(value: str) -> str:
    return f'"{value}"'


def make_server(
    vault: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    verbose: bool = False,
    refresh_interval: float = 1.0,
) -> tuple[ViewerHTTPServer, GraphService]:
    """Create (but do not start) a viewer server bound to *host*:*port*."""
    service = GraphService(vault, refresh_interval=refresh_interval)
    server = ViewerHTTPServer(
        (host, port),
        ViewerHandler,
        service=service,
        verbose=verbose,
        bound_host=host,
    )
    return server, service


def _display_url(server: ViewerHTTPServer) -> str:
    address = server.server_address
    host = str(address[0])
    port = int(address[1])
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/"


def run_server(
    vault: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    open_browser: bool = False,
    verbose: bool = False,
    refresh_interval: float = 1.0,
) -> int:
    """Run the viewer until interrupted."""
    try:
        server, _service = make_server(
            vault,
            host=host,
            port=port,
            verbose=verbose,
            refresh_interval=refresh_interval,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot bind {host}:{port}: {exc}") from exc

    url = _display_url(server)
    print(f"graph-wiki viewer: {url}", flush=True)
    print(f"vault: {Path(vault).expanduser().resolve()}", flush=True)
    print("Ctrl-C to stop", flush=True)

    if open_browser:
        timer = threading.Timer(0.4, lambda: _open_browser(url))
        timer.daemon = True
        timer.start()

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    finally:
        server.server_close()
    return 0


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass
