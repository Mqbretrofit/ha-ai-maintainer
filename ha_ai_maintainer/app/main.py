"""Ingress dashboard for diagnostics and explicitly approved maintenance."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any

from analysis import AIAnalysisError, analyze_snapshot, build_repair_context
from collector import (
    CollectorOptions,
    HomeAssistantAPIError,
    HomeAssistantClient,
    collect_snapshot,
)
from local_repair import (
    DEFAULT_ALLOWED_PATHS,
    LocalRepairError,
    LocalRepairOptions,
    apply_local_repair,
    load_latest_local_job,
    load_local_job,
    prepare_local_repair,
    rollback_local_repair,
)
from entity_cleanup import (
    EntityCleanupError,
    delete_entity_cleanup_candidates,
    find_entity_cleanup_candidates,
)
from repairs import (
    RepairDispatchError,
    dispatch_repair,
    find_repair_candidates,
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


def load_github_token(path: Path = OPTIONS_PATH) -> str:
    """Read the optional GitHub token without retaining or exposing it."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(raw, dict):
        return ""
    token = raw.get("github_token")
    return token.strip() if isinstance(token, str) else ""


def load_entity_cleanup_options(path: Path = OPTIONS_PATH) -> tuple[bool, int]:
    """Read disabled-by-default entity cleanup settings."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return (
        bool(raw.get("entity_cleanup_enabled", False)),
        _bounded_int(raw.get("entity_cleanup_min_unavailable_days"), 30, 7, 3650),
    )


def load_local_repair_options(path: Path = OPTIONS_PATH) -> LocalRepairOptions:
    """Read the disabled-by-default local repair settings."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    raw_paths = raw.get("local_repair_paths", list(DEFAULT_ALLOWED_PATHS))
    if not isinstance(raw_paths, list):
        raw_paths = list(DEFAULT_ALLOWED_PATHS)
    paths = tuple(
        item.strip()
        for item in raw_paths
        if isinstance(item, str) and item.strip()
    )
    api_key = raw.get("openai_api_key")
    return LocalRepairOptions(
        enabled=bool(raw.get("local_repair_enabled", False)),
        api_key=api_key.strip() if isinstance(api_key, str) else "",
        allowed_paths=paths or DEFAULT_ALLOWED_PATHS,
    )


def select_local_repair_paths(
    options: LocalRepairOptions, requested_paths: Any
) -> LocalRepairOptions:
    """Restrict one repair run to a non-empty subset of configured paths."""

    if requested_paths is None:
        return options
    if not isinstance(requested_paths, list):
        raise LocalRepairError("A kiválasztott javítási útvonalak érvénytelenek.")
    selected: list[str] = []
    allowed = set(options.allowed_paths)
    for value in requested_paths:
        if not isinstance(value, str) or value not in allowed:
            raise LocalRepairError(
                "A kérés az alkalmazásban nem engedélyezett útvonalat tartalmaz."
            )
        if value not in selected:
            selected.append(value)
    if not selected:
        raise LocalRepairError("Válassz legalább egy javítandó útvonalat.")
    return replace(options, allowed_paths=tuple(selected))


class ObserverState:
    """Thread-safe storage for the most recent snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._error: str | None = None
        self._scanning = False
        self._analysis: dict[str, Any] | None = None
        self._analysis_error: str | None = None
        self._analyzing = False
        self._dispatching_repair = False
        self._repair_result: dict[str, str] | None = None
        self._repair_error: str | None = None
        self._local_repair_busy = False
        self._local_repair_operation: str | None = None
        self._local_repair_job: dict[str, Any] | None = load_latest_local_job()
        self._local_repair_error: str | None = None
        self._entity_cleanup_busy = False
        self._entity_cleanup_operation: str | None = None
        self._entity_cleanup_candidates: list[dict[str, str]] = []
        self._entity_cleanup_scanned = False
        self._entity_cleanup_result: dict[str, Any] | None = None
        self._entity_cleanup_error: str | None = None

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

    def begin_analysis(self) -> dict[str, Any] | None:
        with self._lock:
            if self._analyzing or self._snapshot is None:
                return None
            self._analyzing = True
            self._analysis_error = None
            return deepcopy(self._snapshot)

    def finish_analysis(
        self, analysis: dict[str, Any] | None, error: str | None
    ) -> None:
        with self._lock:
            if analysis is not None:
                self._analysis = analysis
            self._analysis_error = error
            self._analyzing = False

    def begin_repair(self, candidate_id: str) -> dict[str, str] | None:
        """Lock and return one currently detected allowlisted repair."""

        with self._lock:
            if self._dispatching_repair:
                return None
            candidates = find_repair_candidates(self._snapshot)
            candidate = next(
                (
                    item
                    for item in candidates
                    if item.get("id") == candidate_id
                ),
                None,
            )
            if candidate is None:
                return None
            self._dispatching_repair = True
            self._repair_error = None
            return deepcopy(candidate)

    def finish_repair(
        self, result: dict[str, str] | None, error: str | None
    ) -> None:
        with self._lock:
            if result is not None:
                self._repair_result = result
            self._repair_error = error
            self._dispatching_repair = False

    def begin_local_repair(self, operation: str) -> bool:
        """Lock one local proposal, apply, or rollback operation."""

        with self._lock:
            if self._local_repair_busy:
                return False
            self._local_repair_busy = True
            self._local_repair_operation = operation
            self._local_repair_error = None
            return True

    def finish_local_repair(
        self, job: dict[str, Any] | None, error: str | None
    ) -> None:
        with self._lock:
            if job is not None:
                self._local_repair_job = job
            self._local_repair_error = error
            self._local_repair_busy = False
            self._local_repair_operation = None

    def latest_repair_context(self) -> str:
        """Return the latest AI diagnosis as bounded local-repair evidence."""

        with self._lock:
            analysis = deepcopy(self._analysis)
        if analysis is None:
            raise AIAnalysisError(
                "Nincs átadható AI-diagnózis. Előbb indíts AI-elemzést."
            )
        return build_repair_context(analysis)

    def begin_entity_cleanup(self, operation: str) -> bool:
        """Lock one entity-registry discovery or deletion operation."""

        with self._lock:
            if self._entity_cleanup_busy:
                return False
            self._entity_cleanup_busy = True
            self._entity_cleanup_operation = operation
            self._entity_cleanup_error = None
            return True

    def finish_entity_cleanup(
        self,
        *,
        candidates: list[dict[str, str]] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            if candidates is not None:
                self._entity_cleanup_candidates = candidates
                self._entity_cleanup_scanned = True
            if result is not None:
                self._entity_cleanup_result = result
            self._entity_cleanup_error = error
            self._entity_cleanup_busy = False
            self._entity_cleanup_operation = None

    def response(self) -> dict[str, Any]:
        with self._lock:
            public_analysis = deepcopy(self._analysis)
            if public_analysis is not None:
                public_analysis.pop("evidence", None)
            response = {
                "scanning": self._scanning,
                "error": self._error,
                "snapshot": self._snapshot,
                "analyzing": self._analyzing,
                "analysis_error": self._analysis_error,
                "analysis": public_analysis,
                "repair_candidates": find_repair_candidates(self._snapshot),
                "dispatching_repair": self._dispatching_repair,
                "repair_result": self._repair_result,
                "repair_error": self._repair_error,
                "local_repair": {
                    "busy": self._local_repair_busy,
                    "operation": self._local_repair_operation,
                    "job": deepcopy(self._local_repair_job),
                    "error": self._local_repair_error,
                },
                "entity_cleanup": {
                    "enabled": False,
                    "busy": self._entity_cleanup_busy,
                    "operation": self._entity_cleanup_operation,
                    "scanned": self._entity_cleanup_scanned,
                    "candidates": deepcopy(self._entity_cleanup_candidates),
                    "result": deepcopy(self._entity_cleanup_result),
                    "error": self._entity_cleanup_error,
                },
            }
        response["local_repair"]["config"] = load_local_repair_options().public()
        cleanup_enabled, cleanup_days = load_entity_cleanup_options()
        response["entity_cleanup"]["enabled"] = cleanup_enabled
        response["entity_cleanup"]["minimum_unavailable_days"] = cleanup_days
        return response


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


def run_analysis() -> None:
    """Run one explicitly requested advisory AI analysis."""

    snapshot = STATE.begin_analysis()
    if snapshot is None:
        return
    try:
        result = analyze_snapshot(HomeAssistantClient(), snapshot)
    except (AIAnalysisError, HomeAssistantAPIError, ValueError, OSError) as error:
        STATE.finish_analysis(None, str(error))
    except Exception as error:
        STATE.finish_analysis(
            None, f"Unexpected AI analysis error: {type(error).__name__}"
        )
    else:
        STATE.finish_analysis(result, None)


def run_repair(candidate_id: str) -> None:
    """Dispatch one explicitly approved, allowlisted Codex repair."""

    candidate = STATE.begin_repair(candidate_id)
    if candidate is None:
        return
    try:
        result = dispatch_repair(load_github_token(), candidate_id)
    except (RepairDispatchError, ValueError, OSError) as error:
        STATE.finish_repair(None, str(error))
    except Exception as error:
        STATE.finish_repair(
            None, f"Unexpected repair dispatch error: {type(error).__name__}"
        )
    else:
        STATE.finish_repair(result, None)


def run_local_prepare(
    options: LocalRepairOptions,
    task: str,
    diagnostic_context: str = "",
) -> None:
    """Generate a local Codex proposal in an isolated configuration copy."""

    try:
        result = prepare_local_repair(
            options,
            task,
            diagnostic_context=diagnostic_context,
        )
    except (LocalRepairError, ValueError, OSError) as error:
        STATE.finish_local_repair(None, str(error))
    except Exception as error:
        STATE.finish_local_repair(
            None, f"Váratlan helyi Codex-hiba: {type(error).__name__}"
        )
    else:
        STATE.finish_local_repair(result, None)


def run_entity_cleanup_discovery() -> None:
    """Find only currently unavailable, demonstrably orphaned registry entries."""

    try:
        _enabled, minimum_days = load_entity_cleanup_options()
        candidates = find_entity_cleanup_candidates(
            HomeAssistantClient(), minimum_days
        )
    except (EntityCleanupError, HomeAssistantAPIError, ValueError, OSError) as error:
        STATE.finish_entity_cleanup(error=str(error))
        return
    except Exception as error:
        STATE.finish_entity_cleanup(
            error=f"Váratlan entitásvizsgálati hiba: {type(error).__name__}"
        )
    else:
        STATE.finish_entity_cleanup(candidates=candidates)


def run_entity_cleanup_delete(entity_ids: list[str]) -> None:
    """Revalidate and remove explicitly approved orphaned registry entries."""

    try:
        client = HomeAssistantClient()
        _enabled, minimum_days = load_entity_cleanup_options()
        result = delete_entity_cleanup_candidates(client, entity_ids, minimum_days)
    except (EntityCleanupError, HomeAssistantAPIError, ValueError, OSError) as error:
        STATE.finish_entity_cleanup(error=str(error))
        return
    except Exception as error:
        STATE.finish_entity_cleanup(
            error=f"Váratlan entitástörlési hiba: {type(error).__name__}"
        )
        return
    try:
        candidates = find_entity_cleanup_candidates(client, minimum_days)
    except (EntityCleanupError, HomeAssistantAPIError, ValueError, OSError) as error:
        STATE.finish_entity_cleanup(result=result, error=str(error))
    except Exception as error:
        STATE.finish_entity_cleanup(
            result=result,
            error=f"Váratlan utóellenőrzési hiba: {type(error).__name__}",
        )
    else:
        STATE.finish_entity_cleanup(candidates=candidates, result=result)


def run_local_apply(job_id: str) -> None:
    """Apply one explicitly approved proposal and validate Home Assistant."""

    try:
        result = apply_local_repair(job_id, HomeAssistantClient())
    except (LocalRepairError, HomeAssistantAPIError, ValueError, OSError) as error:
        try:
            persisted = load_local_job(job_id)
        except LocalRepairError:
            persisted = None
        STATE.finish_local_repair(persisted, str(error))
    except Exception as error:
        STATE.finish_local_repair(
            None, f"Váratlan helyi alkalmazási hiba: {type(error).__name__}"
        )
    else:
        STATE.finish_local_repair(result, None)


def run_local_rollback(job_id: str) -> None:
    """Restore one explicitly approved local file-level backup."""

    try:
        result = rollback_local_repair(job_id, HomeAssistantClient())
    except (LocalRepairError, HomeAssistantAPIError, ValueError, OSError) as error:
        try:
            persisted = load_local_job(job_id)
        except LocalRepairError:
            persisted = None
        STATE.finish_local_repair(persisted, str(error))
    except Exception as error:
        STATE.finish_local_repair(
            None, f"Váratlan helyi visszaállítási hiba: {type(error).__name__}"
        )
    else:
        STATE.finish_local_repair(result, None)


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
    .actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
    h1 { margin: 0; font-size: clamp(1.5rem, 4vw, 2.4rem); }
    .sub { color: #9fc2d5; margin: 6px 0 22px; }
    button { border: 0; border-radius: 12px; padding: 11px 16px; background: #16a9e0;
      color: #031018; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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
    #error, #log-warning, #analysis-error, #repair-error, #local-repair-error,
    #entity-cleanup-error {
      white-space: pre-wrap; }
    #analysis { white-space: pre-wrap; line-height: 1.5; margin-top: 12px; }
    .repair-item { display: grid; gap: 8px; padding: 12px 0;
      border-bottom: 1px solid #1c3d4e; }
    .repair-item:last-child { border-bottom: 0; }
    .repair-meta { color: #9fc2d5; overflow-wrap: anywhere; }
    .repair-evidence { white-space: pre-wrap; overflow-wrap: anywhere; }
    textarea { width: 100%; min-height: 110px; resize: vertical; box-sizing: border-box;
      margin: 12px 0; padding: 12px; border-radius: 10px; border: 1px solid #31576a;
      background: #071923; color: #e7f5ff; font: inherit; }
    pre { max-height: 460px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere;
      background: #071923; border: 1px solid #1c3d4e; border-radius: 10px; padding: 12px; }
    .local-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
    .path-list { display: flex; gap: 10px 18px; flex-wrap: wrap; margin: 12px 0; }
    .path-list label, .entity-choice { display: flex; gap: 8px; align-items: center; }
    .entity-choice { align-items: flex-start; padding: 8px 0;
      border-bottom: 1px solid #1c3d4e; }
    input[type="checkbox"] { width: 18px; height: 18px; flex: 0 0 auto; }
    a { color: #71d4ff; }
  </style>
</head>
<body>
<main>
  <header><div><h1>HA AI Maintainer</h1>
    <div class="sub">Helyi diagnosztika, jóváhagyásos AI-elemzéssel</div></div>
    <div class="actions"><button id="scan">Vizsgálat indítása</button>
      <button id="analyze">AI-elemzés indítása</button></div></header>
  <div class="notice">Az automatikus vizsgálat nem vezérel eszközt és nem módosít
    konfigurációt. AI-elemzés és helyi Codex-javítás csak külön jóváhagyással indul.
    A Codex először kizárólag egy szűrt, elkülönített másolatban készít javaslatot;
    az élő fájlokra külön második jóváhagyás után, mentéssel és ellenőrzéssel kerülhet.
    Árva entitásregiszter-bejegyzés csak kézi kijelölés és újraellenőrzés után
    törölhető.</div>
  <div id="error" class="card bad" hidden></div>
  <div id="log-warning" class="card warn" hidden></div>
  <div id="analysis-error" class="card bad" hidden></div>
  <div id="repair-error" class="card bad" hidden></div>
  <div id="local-repair-error" class="card bad" hidden></div>
  <div id="entity-cleanup-error" class="card bad" hidden></div>
  <section id="analysis-card" class="card section" hidden>
    <h2>AI diagnózis</h2>
    <div id="analysis-meta" class="label"></div>
    <div id="analysis"></div>
    <div class="local-actions">
      <button id="analysis-local-repair">
        Javítási javaslat készítése ebből a diagnózisból
      </button>
    </div>
  </section>
  <section id="repair-card" class="card section" hidden>
    <h2>Codexszel javítható problémák</h2>
    <div class="label">Csak előre engedélyezett GitHub-workflow indítható.
      A diagnosztikai napló és az entitásadatok nem kerülnek a GitHubra.</div>
    <div id="repairs"></div>
    <div id="repair-result" class="ok" hidden></div>
  </section>
  <section id="local-repair-card" class="card section">
    <h2>Helyi Codex-javítás</h2>
    <div id="local-repair-config" class="label"></div>
    <div id="local-repair-paths" class="path-list"></div>
    <textarea id="local-repair-task"
      placeholder="Írd le pontosan, mit javítson a Codex az engedélyezett Home Assistant-fájlokban."></textarea>
    <button id="local-repair-prepare">Javítási javaslat készítése</button>
    <div id="local-repair-progress" class="label" hidden></div>
    <div id="local-repair-result" hidden>
      <h3>Codex-javaslat</h3>
      <div id="local-repair-meta" class="label"></div>
      <pre id="local-repair-summary"></pre>
      <h3>Fájlmódosítások</h3>
      <pre id="local-repair-diff"></pre>
      <div class="local-actions">
        <button id="local-repair-apply">Javaslat alkalmazása</button>
        <button id="local-repair-rollback" hidden>Legutóbbi javítás visszaállítása</button>
      </div>
    </div>
  </section>
  <div class="grid">
    <div class="card"><div id="total" class="value">–</div><div class="label">Összes entitás</div></div>
    <div class="card"><div id="unavailable" class="value">–</div><div class="label">Unavailable</div></div>
    <div class="card"><div id="unknown" class="value">–</div><div class="label">Unknown</div></div>
    <div class="card"><div id="unique-errors" class="value">–</div><div class="label">Egyedi naplóhibák</div></div>
    <div class="card"><div id="occurrences" class="value">–</div><div class="label">Összes előfordulás</div></div>
  </div>
  <section class="grid section">
    <div class="card"><h2>Problémás entitások domain szerint</h2>
      <table><thead><tr><th>Domain</th><th>Darab</th></tr></thead>
        <tbody id="problem-domains"></tbody></table></div>
    <div class="card"><h2>Leggyakoribb naplóforrások</h2>
      <table><thead><tr><th>Forrás</th><th>Egyedi</th><th>Előfordulás</th></tr></thead>
        <tbody id="loggers"></tbody></table></div>
  </section>
  <section class="card section"><h2>Problémás entitások</h2>
    <div id="entity-summary" class="label"></div>
    <table><thead><tr><th>Név</th><th>Entitás</th><th>Állapot</th></tr></thead>
      <tbody id="entities"></tbody></table></section>
  <section id="entity-cleanup-card" class="card section">
    <h2>Régi és árva entitások törlése</h2>
    <div id="entity-cleanup-config" class="label"></div>
    <div class="label">Csak igazoltan árva, vagy a beállított ideje folyamatosan
      unavailable entitás kerülhet ide. A törlés nem vonható vissza, ezért
      nincs automatikus kijelölés.</div>
    <div class="local-actions">
      <button id="entity-cleanup-discover">Törlési jelöltek keresése</button>
      <button id="entity-cleanup-delete" disabled>Kijelöltek törlése</button>
    </div>
    <div id="entity-cleanup-progress" class="label" hidden></div>
    <div id="entity-cleanup-result" class="ok" hidden></div>
    <div id="entity-cleanup-empty" class="label" hidden>
      Nem található biztonságosan törölhető árva entitás.
    </div>
    <div id="entity-cleanup-candidates"></div>
  </section>
  <section class="card section"><h2>Legutóbbi hibanapló-bejegyzések</h2>
    <table><thead><tr><th>Szint</th><th>Forrás</th><th>Előfordulás</th><th>Üzenet</th></tr></thead>
      <tbody id="logs"></tbody></table></section>
</main>
<script>
const byId = (id) => document.getElementById(id);
let currentLocalJob = null;
let currentPathSignature = '';
let selectedRepairPaths = new Set();
let selectedCleanupEntities = new Set();
function cell(row, value) { const td = document.createElement('td'); td.textContent = value || '–'; row.append(td); }
function selectedPaths() {
  return [...selectedRepairPaths];
}
function renderRepairPaths(paths) {
  const signature = paths.join('\\n');
  if (signature === currentPathSignature) return;
  currentPathSignature = signature;
  selectedRepairPaths = new Set(
    paths.filter((path) => !['www', 'dashboards'].includes(path))
  );
  if (selectedRepairPaths.size === 0) selectedRepairPaths = new Set(paths);
  const container = byId('local-repair-paths'); container.replaceChildren();
  for (const path of paths) {
    const label = document.createElement('label');
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
    checkbox.checked = selectedRepairPaths.has(path);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) selectedRepairPaths.add(path);
      else selectedRepairPaths.delete(path);
    });
    const text = document.createElement('span'); text.textContent = path;
    label.append(checkbox, text); container.append(label);
  }
}
function render(data) {
  byId('scan').disabled = Boolean(data.scanning);
  byId('analyze').disabled = Boolean(data.analyzing) || !data.snapshot;
  byId('analyze').textContent = data.analyzing
    ? 'AI elemzi…' : 'AI-elemzés indítása';
  const error = byId('error');
  error.hidden = !data.error; error.textContent = data.error || '';
  const analysisError = byId('analysis-error');
  analysisError.hidden = !data.analysis_error;
  analysisError.textContent = data.analysis_error || '';
  const repairError = byId('repair-error');
  repairError.hidden = !data.repair_error;
  repairError.textContent = data.repair_error || '';
  const localRepair = data.local_repair || {};
  const localConfig = localRepair.config || {};
  const localError = byId('local-repair-error');
  localError.hidden = !localRepair.error;
  localError.textContent = localRepair.error || '';
  const entityCleanup = data.entity_cleanup || {};
  const entityCleanupError = byId('entity-cleanup-error');
  entityCleanupError.hidden = !entityCleanup.error;
  entityCleanupError.textContent = entityCleanup.error || '';
  const analysisCard = byId('analysis-card');
  analysisCard.hidden = !data.analysis;
  if (data.analysis) {
    byId('analysis-meta').textContent =
      `Forrás: ${data.analysis.entity_id} · pillanatkép: ${data.analysis.source_generated_at} · csak javaslat`;
    byId('analysis').textContent = data.analysis.text;
  }
  const analysisRepair = byId('analysis-local-repair');
  analysisRepair.disabled = !data.analysis || Boolean(localRepair.busy) ||
    !localConfig.enabled || !localConfig.api_key_configured;
  const repairCard = byId('repair-card');
  const repairCandidates = Array.isArray(data.repair_candidates)
    ? data.repair_candidates : [];
  repairCard.hidden = repairCandidates.length === 0 && !data.repair_result;
  const repairs = byId('repairs'); repairs.replaceChildren();
  for (const candidate of repairCandidates) {
    const item = document.createElement('div'); item.className = 'repair-item';
    const title = document.createElement('strong'); title.textContent = candidate.title;
    const meta = document.createElement('div'); meta.className = 'repair-meta';
    meta.textContent = `Célprojekt: ${candidate.repository}`;
    const evidence = document.createElement('div'); evidence.className = 'repair-evidence';
    evidence.textContent = candidate.evidence;
    const button = document.createElement('button');
    button.textContent = data.dispatching_repair
      ? 'Codex indítása…' : 'Javítás készítése Codexszel';
    button.disabled = Boolean(data.dispatching_repair);
    button.addEventListener('click', () => requestRepair(candidate));
    item.append(title, meta, evidence, button); repairs.append(item);
  }
  const repairResult = byId('repair-result');
  repairResult.hidden = !data.repair_result;
  repairResult.replaceChildren();
  if (data.repair_result) {
    const message = document.createElement('span');
    message.textContent = 'A Codex javítási workflow elindult. ';
    const link = document.createElement('a');
    link.href = data.repair_result.workflow_url;
    link.target = '_blank'; link.rel = 'noopener noreferrer';
    link.textContent = 'GitHub Actions megnyitása';
    repairResult.append(message, link);
  }
  const allowedPaths = Array.isArray(localConfig.allowed_paths)
    ? localConfig.allowed_paths : [];
  renderRepairPaths(allowedPaths);
  byId('local-repair-config').textContent = localConfig.enabled
    ? `Engedélyezve · OpenAI-kulcs: ${localConfig.api_key_configured ? 'beállítva' : 'hiányzik'} · ` +
      `engedélyezett útvonalak: ${allowedPaths.join(', ') || 'nincs'}`
    : 'Kikapcsolva az alkalmazás konfigurációjában.';
  const localPrepare = byId('local-repair-prepare');
  localPrepare.disabled = Boolean(localRepair.busy) || !localConfig.enabled ||
    !localConfig.api_key_configured;
  localPrepare.textContent = localRepair.busy && localRepair.operation === 'prepare'
    ? 'Codex dolgozik…' : 'Javítási javaslat készítése';
  const localProgress = byId('local-repair-progress');
  localProgress.hidden = !localRepair.busy;
  localProgress.textContent = localRepair.busy
    ? `Folyamatban: ${localRepair.operation || 'helyi javítás'}…` : '';
  currentLocalJob = localRepair.job || null;
  const localResult = byId('local-repair-result');
  localResult.hidden = !currentLocalJob;
  if (currentLocalJob) {
    const changedFiles = Array.isArray(currentLocalJob.changed_files)
      ? currentLocalJob.changed_files : [];
    byId('local-repair-meta').textContent =
      `Állapot: ${currentLocalJob.status} · fájlok: ${changedFiles.join(', ') || '–'}`;
    byId('local-repair-summary').textContent = currentLocalJob.summary || 'Nincs összefoglaló.';
    byId('local-repair-diff').textContent = currentLocalJob.diff || 'Nincs diff.';
    const applyButton = byId('local-repair-apply');
    applyButton.hidden = currentLocalJob.status !== 'proposed';
    applyButton.disabled = Boolean(localRepair.busy);
    const rollbackButton = byId('local-repair-rollback');
    rollbackButton.hidden = currentLocalJob.status !== 'applied';
    rollbackButton.disabled = Boolean(localRepair.busy);
  }
  const cleanupCandidates = Array.isArray(entityCleanup.candidates)
    ? entityCleanup.candidates : [];
  byId('entity-cleanup-config').textContent = entityCleanup.enabled
    ? `Engedélyezve · tartós unavailable határ: ${entityCleanup.minimum_unavailable_days || 30} nap.`
    : 'Kikapcsolva az alkalmazás konfigurációjában.';
  const currentCleanupIds = new Set(
    cleanupCandidates.map((item) => item.entity_id)
  );
  selectedCleanupEntities = new Set(
    [...selectedCleanupEntities].filter((entityId) => currentCleanupIds.has(entityId))
  );
  const cleanupDiscover = byId('entity-cleanup-discover');
  cleanupDiscover.disabled = Boolean(entityCleanup.busy) || !entityCleanup.enabled;
  cleanupDiscover.textContent = entityCleanup.busy &&
    entityCleanup.operation === 'discover'
    ? 'Vizsgálat folyamatban…' : 'Törlési jelöltek keresése';
  const cleanupDelete = byId('entity-cleanup-delete');
  cleanupDelete.disabled = Boolean(entityCleanup.busy) || !entityCleanup.enabled ||
    selectedCleanupEntities.size === 0;
  cleanupDelete.textContent = entityCleanup.busy &&
    entityCleanup.operation === 'delete'
    ? 'Törlés folyamatban…' : 'Kijelöltek törlése';
  const cleanupProgress = byId('entity-cleanup-progress');
  cleanupProgress.hidden = !entityCleanup.busy;
  cleanupProgress.textContent = entityCleanup.busy
    ? `Folyamatban: ${entityCleanup.operation || 'entitásvizsgálat'}…` : '';
  const cleanupResult = byId('entity-cleanup-result');
  cleanupResult.hidden = !entityCleanup.result;
  cleanupResult.textContent = entityCleanup.result
    ? entityCleanup.result.message || '' : '';
  byId('entity-cleanup-empty').hidden =
    !entityCleanup.scanned || cleanupCandidates.length !== 0 ||
    Boolean(entityCleanup.busy);
  const cleanupList = byId('entity-cleanup-candidates');
  cleanupList.replaceChildren();
  for (const candidate of cleanupCandidates) {
    const label = document.createElement('label'); label.className = 'entity-choice';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
    checkbox.checked = selectedCleanupEntities.has(candidate.entity_id);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) selectedCleanupEntities.add(candidate.entity_id);
      else selectedCleanupEntities.delete(candidate.entity_id);
      cleanupDelete.disabled = !entityCleanup.enabled ||
        Boolean(entityCleanup.busy) || selectedCleanupEntities.size === 0;
    });
    const text = document.createElement('span');
    const title = candidate.name
      ? `${candidate.name} (${candidate.entity_id})` : candidate.entity_id;
    text.textContent = `${title} · ${candidate.platform || 'ismeretlen integráció'} · ${candidate.reason}`;
    label.append(checkbox, text); cleanupList.append(label);
  }
  const snap = data.snapshot;
  if (!snap) return;
  const states = snap.states; const log = snap.log;
  const logWarning = byId('log-warning');
  logWarning.hidden = Boolean(log.available);
  logWarning.textContent = log.error || '';
  byId('total').textContent = states.total;
  byId('unavailable').textContent = states.unavailable;
  byId('unknown').textContent = states.unknown;
  byId('unique-errors').textContent = log.available ? log.unique_entries : '–';
  byId('occurrences').textContent = log.available ? log.total_occurrences : '–';
  const problemDomains = byId('problem-domains'); problemDomains.replaceChildren();
  for (const item of states.problem_domains) {
    const row = document.createElement('tr'); cell(row, item.domain); cell(row, item.count);
    problemDomains.append(row);
  }
  const loggers = byId('loggers'); loggers.replaceChildren();
  for (const item of log.top_loggers) {
    const row = document.createElement('tr'); cell(row, item.logger);
    cell(row, item.unique_entries); cell(row, item.occurrences); loggers.append(row);
  }
  byId('entity-summary').textContent = states.problem_entities_truncated
    ? `${states.problem_entities_total} problémás entitásból az első ${states.problem_entities.length} látható.`
    : `${states.problem_entities_total} problémás entitás.`;
  const entities = byId('entities'); entities.replaceChildren();
  for (const item of states.problem_entities) {
    const row = document.createElement('tr'); cell(row, item.name); cell(row, item.entity_id);
    cell(row, item.state); entities.append(row);
  }
  const logs = byId('logs'); logs.replaceChildren();
  for (const item of log.samples) {
    const row = document.createElement('tr'); cell(row, item.severity);
    cell(row, item.logger); cell(row, item.occurrences); cell(row, item.message);
    logs.append(row);
  }
}
async function refresh() {
  try { render(await (await fetch('./api/status', {cache: 'no-store'})).json()); }
  catch (error) { byId('error').hidden = false; byId('error').textContent = String(error); }
}
async function requestRepair(candidate) {
  const approved = window.confirm(
    `Elindítsuk a Codex javítást ebben a projektben: ${candidate.repository}?\n\n` +
    'A GitHub csak az előre engedélyezett javítás azonosítóját kapja meg. ' +
    'Napló, entitásadat és Home Assistant-konfiguráció nem kerül továbbításra.'
  );
  if (!approved) return;
  const response = await fetch('./api/repair', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-HA-AI-Approval': 'dispatch-repair'
    },
    body: JSON.stringify({candidate_id: candidate.id})
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    byId('repair-error').hidden = false;
    byId('repair-error').textContent =
      result.error || `A javítás indítása sikertelen (HTTP ${response.status}).`;
  }
  setTimeout(refresh, 500);
}
function showLocalError(message) {
  byId('local-repair-error').hidden = false;
  byId('local-repair-error').textContent = message;
}
async function localRepairRequest(path, approval, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-HA-AI-Approval': approval
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    showLocalError(result.error || `A helyi javítás sikertelen (HTTP ${response.status}).`);
  }
  setTimeout(refresh, 500);
}
async function prepareLocalRepair(task, useAnalysis) {
  if (!task) { showLocalError('Írd le a javítási feladatot.'); return; }
  const paths = selectedPaths();
  if (paths.length === 0) {
    showLocalError('Válassz legalább egy javítandó útvonalat.');
    return;
  }
  const analysisNotice = useAnalysis
    ? ' A legutóbbi AI-diagnózis és a korlátozott, kitakart naplóbizonyíték is a Codexhez kerül.'
    : '';
  const approved = window.confirm(
    'A Codex megkapja a feladat szövegét és az alkalmazásban engedélyezett fájlok ' +
    `elkülönített másolatát.${analysisNotice} Az élő konfigurációt még nem módosítja. Folytatod?`
  );
  if (!approved) return;
  byId('local-repair-prepare').disabled = true;
  byId('analysis-local-repair').disabled = true;
  await localRepairRequest(
    './api/local-repair/prepare', 'prepare-local-repair',
    {task, use_analysis: useAnalysis, paths}
  );
}
byId('local-repair-prepare').addEventListener('click', async () => {
  await prepareLocalRepair(byId('local-repair-task').value.trim(), false);
});
byId('analysis-local-repair').addEventListener('click', async () => {
  const task =
    'Vizsgáld meg a mellékelt AI-diagnózis bizonyítékait, és javítsd kizárólag ' +
    'az engedélyezett fájlokban ténylegesen igazolható konfigurációs vagy ' +
    'forráskód-hibákat. A hálózati, kikapcsolt eszköz-, újrapárosítási, ' +
    'újraindítási és felhőszolgáltatási hibákat ne próbáld fájlmódosítással javítani.';
  await prepareLocalRepair(task, true);
});
byId('local-repair-apply').addEventListener('click', async () => {
  if (!currentLocalJob) return;
  const files = Array.isArray(currentLocalJob.changed_files)
    ? currentLocalJob.changed_files.join(', ') : '';
  const approved = window.confirm(
    `Alkalmazzuk ezt a Codex-javaslatot?\\n\\nFájlok: ${files}\\n\\n` +
    'Az eredeti fájlokról mentés készül. A Home Assistant konfiguráció-ellenőrzése ' +
    'hibánál automatikusan visszaállítja őket. A rendszer nem indul újra magától.'
  );
  if (!approved) return;
  await localRepairRequest(
    './api/local-repair/apply', 'apply-local-repair',
    {job_id: currentLocalJob.job_id}
  );
});
byId('local-repair-rollback').addEventListener('click', async () => {
  if (!currentLocalJob) return;
  const approved = window.confirm(
    'Visszaállítsuk a javítás előtt elmentett fájlokat? A művelet után újabb ' +
    'Home Assistant konfiguráció-ellenőrzés fut.'
  );
  if (!approved) return;
  await localRepairRequest(
    './api/local-repair/rollback', 'rollback-local-repair',
    {job_id: currentLocalJob.job_id}
  );
});
byId('scan').addEventListener('click', async () => {
  byId('scan').disabled = true;
  await fetch('./api/scan', {method: 'POST'});
  setTimeout(refresh, 500);
});
byId('analyze').addEventListener('click', async () => {
  const approved = window.confirm(
    'Elküldjük a kitakart diagnosztikai összefoglalót a beállított OpenAI AI Task szolgáltatásnak?'
  );
  if (!approved) return;
  byId('analyze').disabled = true;
  await fetch('./api/analyze', {
    method: 'POST',
    headers: {'X-HA-AI-Approval': 'analyze'}
  });
  setTimeout(refresh, 500);
});
byId('entity-cleanup-discover').addEventListener('click', async () => {
  const approved = window.confirm(
    'Lekérjük a Home Assistant aktuális állapotait, entitásregiszterét és ' +
    'konfigurációs bejegyzéseit az árva vagy régóta unavailable entitások ' +
    'megkereséséhez? ' +
    'Ez még nem töröl semmit.'
  );
  if (!approved) return;
  await localRepairRequest(
    './api/entity-cleanup/discover', 'discover-orphaned-entities', {}
  );
});
byId('entity-cleanup-delete').addEventListener('click', async () => {
  const entityIds = [...selectedCleanupEntities].sort();
  if (entityIds.length === 0) return;
  const approved = window.confirm(
    `Végleg töröljük ezt a ${entityIds.length} entitásregiszter-bejegyzést?\\n\\n` +
    `${entityIds.join('\\n')}\\n\\n` +
    'A művelet nem vonható vissza. A szerver a törlés előtt mindegyiket újra ellenőrzi.'
  );
  if (!approved) return;
  await localRepairRequest(
    './api/entity-cleanup/delete', 'delete-orphaned-entities',
    {entity_ids: entityIds}
  );
});
refresh(); setInterval(refresh, 5000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    """Serve the local dashboard and observer status."""

    server_version = "HAAIMaintainer/0.5.0"

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

    def _read_json(self, maximum_bytes: int = 4096) -> dict[str, Any]:
        """Read one bounded JSON request body."""

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Érvénytelen kérésméret.") from error
        if length <= 0 or length > maximum_bytes:
            raise ValueError("A kérés üres vagy túl nagy.")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            raise ValueError("A kérés nem érvényes JSON.") from error
        if not isinstance(payload, dict):
            raise ValueError("A kérésnek JSON objektumnak kell lennie.")
        return payload

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _approved_json(
        self, approval: str, maximum_bytes: int = 4096
    ) -> dict[str, Any] | None:
        if self.headers.get("X-HA-AI-Approval") != approval:
            self._send_json(
                HTTPStatus.FORBIDDEN,
                {"accepted": False, "error": "Hiányzó helyi javítási jóváhagyás."},
            )
            return None
        try:
            return self._read_json(maximum_bytes)
        except ValueError as error:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "error": str(error)},
            )
            return None

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
        if path == "/api/scan":
            threading.Thread(target=run_scan, daemon=True).start()
            body = json.dumps({"accepted": True}).encode("utf-8")
            self._send(
                HTTPStatus.ACCEPTED, "application/json; charset=utf-8", body
            )
            return
        if path == "/api/analyze":
            if self.headers.get("X-HA-AI-Approval") != "analyze":
                body = json.dumps(
                    {"accepted": False, "error": "Hiányzó AI-jóváhagyás."},
                    ensure_ascii=False,
                ).encode("utf-8")
                self._send(
                    HTTPStatus.FORBIDDEN,
                    "application/json; charset=utf-8",
                    body,
                )
                return
            if STATE.response()["snapshot"] is None:
                body = json.dumps(
                    {"accepted": False, "error": "Nincs diagnosztikai eredmény."},
                    ensure_ascii=False,
                ).encode("utf-8")
                self._send(
                    HTTPStatus.CONFLICT,
                    "application/json; charset=utf-8",
                    body,
                )
                return
            threading.Thread(target=run_analysis, daemon=True).start()
            body = json.dumps({"accepted": True}).encode("utf-8")
            self._send(
                HTTPStatus.ACCEPTED, "application/json; charset=utf-8", body
            )
            return
        if path == "/api/repair":
            if self.headers.get("X-HA-AI-Approval") != "dispatch-repair":
                body = json.dumps(
                    {"accepted": False, "error": "Hiányzó Codex-jóváhagyás."},
                    ensure_ascii=False,
                ).encode("utf-8")
                self._send(
                    HTTPStatus.FORBIDDEN,
                    "application/json; charset=utf-8",
                    body,
                )
                return
            try:
                request = self._read_json()
            except ValueError as error:
                body = json.dumps(
                    {"accepted": False, "error": str(error)},
                    ensure_ascii=False,
                ).encode("utf-8")
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    "application/json; charset=utf-8",
                    body,
                )
                return
            candidate_id = request.get("candidate_id")
            if not isinstance(candidate_id, str) or not any(
                candidate.get("id") == candidate_id
                for candidate in STATE.response()["repair_candidates"]
            ):
                body = json.dumps(
                    {
                        "accepted": False,
                        "error": "A javítás nem található az aktuális vizsgálatban.",
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                self._send(
                    HTTPStatus.CONFLICT,
                    "application/json; charset=utf-8",
                    body,
                )
                return
            threading.Thread(
                target=run_repair, args=(candidate_id,), daemon=True
            ).start()
            body = json.dumps({"accepted": True}).encode("utf-8")
            self._send(
                HTTPStatus.ACCEPTED, "application/json; charset=utf-8", body
            )
            return
        if path == "/api/local-repair/prepare":
            request = self._approved_json("prepare-local-repair", 16384)
            if request is None:
                return
            task = request.get("task")
            if not isinstance(task, str) or not task.strip():
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"accepted": False, "error": "Hiányzik a javítási feladat."},
                )
                return
            use_analysis = request.get("use_analysis", False)
            if not isinstance(use_analysis, bool):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"accepted": False, "error": "Érvénytelen AI-kontextus beállítás."},
                )
                return
            try:
                options = select_local_repair_paths(
                    load_local_repair_options(), request.get("paths")
                )
                diagnostic_context = (
                    STATE.latest_repair_context() if use_analysis else ""
                )
            except (LocalRepairError, AIAnalysisError) as error:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"accepted": False, "error": str(error)},
                )
                return
            if not options.enabled or not options.api_key.strip():
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {
                        "accepted": False,
                        "error": (
                            "A helyi javítás nincs engedélyezve, vagy hiányzik "
                            "az OpenAI API-kulcs."
                        ),
                    },
                )
                return
            if not STATE.begin_local_repair("prepare"):
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {"accepted": False, "error": "Már fut helyi javítási művelet."},
                )
                return
            threading.Thread(
                target=run_local_prepare,
                args=(options, task, diagnostic_context),
                daemon=True,
            ).start()
            self._send_json(HTTPStatus.ACCEPTED, {"accepted": True})
            return
        if path == "/api/local-repair/apply":
            request = self._approved_json("apply-local-repair")
            if request is None:
                return
            job_id = request.get("job_id")
            if not isinstance(job_id, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"accepted": False, "error": "Hiányzik a javításazonosító."},
                )
                return
            if not load_local_repair_options().enabled:
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {"accepted": False, "error": "A helyi javítás nincs engedélyezve."},
                )
                return
            if not STATE.begin_local_repair("apply"):
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {"accepted": False, "error": "Már fut helyi javítási művelet."},
                )
                return
            threading.Thread(
                target=run_local_apply, args=(job_id,), daemon=True
            ).start()
            self._send_json(HTTPStatus.ACCEPTED, {"accepted": True})
            return
        if path == "/api/local-repair/rollback":
            request = self._approved_json("rollback-local-repair")
            if request is None:
                return
            job_id = request.get("job_id")
            if not isinstance(job_id, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"accepted": False, "error": "Hiányzik a javításazonosító."},
                )
                return
            if not load_local_repair_options().enabled:
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {"accepted": False, "error": "A helyi javítás nincs engedélyezve."},
                )
                return
            if not STATE.begin_local_repair("rollback"):
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {"accepted": False, "error": "Már fut helyi javítási művelet."},
                )
                return
            threading.Thread(
                target=run_local_rollback, args=(job_id,), daemon=True
            ).start()
            self._send_json(HTTPStatus.ACCEPTED, {"accepted": True})
            return
        if path == "/api/entity-cleanup/discover":
            request = self._approved_json("discover-orphaned-entities")
            if request is None:
                return
            cleanup_enabled, _minimum_days = load_entity_cleanup_options()
            if not cleanup_enabled:
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {
                        "accepted": False,
                        "error": "Az árvaentitás-tisztítás nincs engedélyezve.",
                    },
                )
                return
            if not STATE.begin_entity_cleanup("discover"):
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {
                        "accepted": False,
                        "error": "Már fut entitásregiszter-művelet.",
                    },
                )
                return
            threading.Thread(
                target=run_entity_cleanup_discovery, daemon=True
            ).start()
            self._send_json(HTTPStatus.ACCEPTED, {"accepted": True})
            return
        if path == "/api/entity-cleanup/delete":
            request = self._approved_json("delete-orphaned-entities", 16384)
            if request is None:
                return
            cleanup_enabled, _minimum_days = load_entity_cleanup_options()
            if not cleanup_enabled:
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {
                        "accepted": False,
                        "error": "Az árvaentitás-tisztítás nincs engedélyezve.",
                    },
                )
                return
            entity_ids = request.get("entity_ids")
            if not isinstance(entity_ids, list) or not all(
                isinstance(entity_id, str) for entity_id in entity_ids
            ):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"accepted": False, "error": "Az entitáslista érvénytelen."},
                )
                return
            if not STATE.begin_entity_cleanup("delete"):
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {
                        "accepted": False,
                        "error": "Már fut entitásregiszter-művelet.",
                    },
                )
                return
            threading.Thread(
                target=run_entity_cleanup_delete,
                args=(entity_ids,),
                daemon=True,
            ).start()
            self._send_json(HTTPStatus.ACCEPTED, {"accepted": True})
            return
        self._send(
            HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found"
        )


def main() -> None:
    """Start the background observer and Ingress HTTP server."""

    threading.Thread(target=scan_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
