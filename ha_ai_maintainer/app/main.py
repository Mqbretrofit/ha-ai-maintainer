"""Local Ingress dashboard for the HA AI Maintainer observer."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any

from collector import (
    CollectorOptions,
    HomeAssistantAPIError,
    HomeAssistantClient,
    collect_snapshot,
)

OPTIONS_PATH = Path("/data/options.json")
PORT = 8099


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def load_options(path: Path = OPTIONS_PATH) -> tuple[int, CollectorOptions]:
    """Read and validate Supervisor-provided options."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    interval = _bounded_int(raw.get("scan_interval_minutes"), 15, 1, 1440)
    collector_options = CollectorOptions(
        max_problem_entities=_bounded_int(
            raw.get("max_problem_entities"), 50, 1, 500
        ),
        max_log_lines=_bounded_int(raw.get("max_log_lines"), 1000, 100, 10000),
        redact_sensitive_data=bool(raw.get("redact_sensitive_data", True)),
    )
    return interval, collector_options


class ObserverState:
    """Thread-safe storage for the most recent snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._error: str | None = None
        self._scanning = False

    def begin_scan(self) -> bool:
        with self._lock:
            if self._scanning:
                return False
            self._scanning = True
            return True

    def finish(
        self, snapshot: dict[str, Any] | None, error: str | None
    ) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._error = error
            self._scanning = False

    def response(self) -> dict[str, Any]:
        with self._lock:
            return {
                "scanning": self._scanning,
                "error": self._error,
                "snapshot": self._snapshot,
            }


STATE = ObserverState()


def run_scan() -> None:
    """Run a scan unless another scan is already active."""

    if not STATE.begin_scan():
        return
    try:
        _, options = load_options()
        snapshot = collect_snapshot(HomeAssistantClient(), options)
    except (HomeAssistantAPIError, ValueError, OSError) as error:
        STATE.finish(None, str(error))
    except Exception as error:  # Keep the observer alive on malformed API input.
        STATE.finish(None, f"Unexpected observer error: {type(error).__name__}")
    else:
        STATE.finish(snapshot, None)


def scan_loop() -> None:
    """Run the first scan immediately, then repeat at the configured interval."""

    while True:
        run_scan()
        interval_minutes, _ = load_options()
        time.sleep(interval_minutes * 60)


DASHBOARD = """<!doctype html>
<html lang="hu">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HA AI Maintainer</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { margin: 0; background: #07131c; color: #e7f5ff; }
    main { max-width: 1080px; margin: auto; padding: 24px; }
    header { display: flex; gap: 16px; align-items: center; justify-content: space-between; }
    h1 { margin: 0; font-size: clamp(1.5rem, 4vw, 2.4rem); }
    .sub { color: #9fc2d5; margin: 6px 0 22px; }
    button { border: 0; border-radius: 12px; padding: 11px 16px; background: #16a9e0;
      color: #031018; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 14px; }
    .card { background: #0d2330; border: 1px solid #1c3d4e; border-radius: 16px; padding: 16px; }
    .value { font-size: 2rem; font-weight: 750; }
    .label { color: #9fc2d5; }
    .ok { color: #62d394; } .warn { color: #ffd166; } .bad { color: #ff6b6b; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; border-bottom: 1px solid #1c3d4e; padding: 9px 7px;
      overflow-wrap: anywhere; }
    th { color: #9fc2d5; }
    .section { margin-top: 18px; }
    .notice { border-left: 4px solid #62d394; padding: 10px 14px; background: #0d2330;
      border-radius: 8px; margin: 18px 0; }
    #error { white-space: pre-wrap; }
  </style>
</head>
<body>
<main>
  <header><div><h1>HA AI Maintainer</h1><div class="sub">Helyi, csak olvasási mód</div></div>
    <button id="scan">Vizsgálat indítása</button></header>
  <div class="notice">Ez a verzió nem vezérel eszközt, nem módosít konfigurációt és
    nem küld adatot külső szolgáltatásnak.</div>
  <div id="error" class="card bad" hidden></div>
  <div class="grid">
    <div class="card"><div id="total" class="value">–</div><div class="label">Összes entitás</div></div>
    <div class="card"><div id="unavailable" class="value">–</div><div class="label">Unavailable</div></div>
    <div class="card"><div id="unknown" class="value">–</div><div class="label">Unknown</div></div>
    <div class="card"><div id="errors" class="value">–</div><div class="label">Hibanapló találatok</div></div>
  </div>
  <section class="card section"><h2>Problémás entitások</h2>
    <table><thead><tr><th>Név</th><th>Entitás</th><th>Állapot</th></tr></thead>
      <tbody id="entities"></tbody></table></section>
  <section class="card section"><h2>Legutóbbi hibanapló-bejegyzések</h2>
    <table><thead><tr><th>Szint</th><th>Üzenet</th></tr></thead>
      <tbody id="logs"></tbody></table></section>
</main>
<script>
const byId = (id) => document.getElementById(id);
function cell(row, value) { const td = document.createElement('td'); td.textContent = value || '–'; row.append(td); }
function render(data) {
  byId('scan').disabled = Boolean(data.scanning);
  const error = byId('error');
  error.hidden = !data.error; error.textContent = data.error || '';
  const snap = data.snapshot;
  if (!snap) return;
  const states = snap.states; const log = snap.log;
  byId('total').textContent = states.total;
  byId('unavailable').textContent = states.unavailable;
  byId('unknown').textContent = states.unknown;
  byId('errors').textContent = log.critical + log.errors + log.warnings;
  const entities = byId('entities'); entities.replaceChildren();
  for (const item of states.problem_entities) {
    const row = document.createElement('tr'); cell(row, item.name); cell(row, item.entity_id);
    cell(row, item.state); entities.append(row);
  }
  const logs = byId('logs'); logs.replaceChildren();
  for (const item of log.samples) {
    const row = document.createElement('tr'); cell(row, item.severity); cell(row, item.message);
    logs.append(row);
  }
}
async function refresh() {
  try { render(await (await fetch('./api/status', {cache: 'no-store'})).json()); }
  catch (error) { byId('error').hidden = false; byId('error').textContent = String(error); }
}
byId('scan').addEventListener('click', async () => {
  byId('scan').disabled = true;
  await fetch('./api/scan', {method: 'POST'});
  setTimeout(refresh, 500);
});
refresh(); setInterval(refresh, 5000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    """Serve the local dashboard and observer status."""

    server_version = "HAAIMaintainer/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            self._send(HTTPStatus.OK, "text/plain; charset=utf-8", b"ok")
            return
        if path == "/api/status":
            body = json.dumps(STATE.response(), ensure_ascii=False).encode("utf-8")
            self._send(HTTPStatus.OK, "application/json; charset=utf-8", body)
            return
        if path == "/":
            self._send(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                DASHBOARD.encode("utf-8"),
            )
            return
        self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path != "/api/scan":
            self._send(
                HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found"
            )
            return
        threading.Thread(target=run_scan, daemon=True).start()
        body = json.dumps({"accepted": True}).encode("utf-8")
        self._send(HTTPStatus.ACCEPTED, "application/json; charset=utf-8", body)


def main() -> None:
    """Start the background observer and Ingress HTTP server."""

    threading.Thread(target=scan_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
