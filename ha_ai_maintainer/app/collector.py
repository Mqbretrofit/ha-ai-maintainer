"""Collection, summarization, and approved AI-task calls for Home Assistant."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from redaction import redact_text

DEFAULT_API_BASE = "http://supervisor/core/api"
DEFAULT_WEBSOCKET_URL = "ws://supervisor/core/websocket"


class HomeAssistantAPIError(RuntimeError):
    """Raised when the internal Home Assistant API cannot be read."""


@dataclass(frozen=True)
class CollectorOptions:
    """Validated runtime options."""

    max_problem_entities: int = 50
    max_log_lines: int = 1000
    redact_sensitive_data: bool = True


class HomeAssistantClient:
    """Small client for the internal Home Assistant API proxy."""

    def __init__(
        self,
        token: str | None = None,
        api_base: str = DEFAULT_API_BASE,
        websocket_url: str = DEFAULT_WEBSOCKET_URL,
        timeout: int = 20,
        ai_timeout: int = 120,
        websocket_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._token = token or os.environ.get("SUPERVISOR_TOKEN", "")
        self._api_base = api_base.rstrip("/")
        self._websocket_url = websocket_url
        self._timeout = timeout
        self._ai_timeout = ai_timeout
        self._websocket_factory = websocket_factory
        if not self._token:
            raise HomeAssistantAPIError("SUPERVISOR_TOKEN is not available")

    def _get(self, path: str, accept: str) -> bytes:
        request = Request(
            f"{self._api_base}/{path.lstrip('/')}",
            method="GET",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": accept,
            },
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            raise HomeAssistantAPIError(
                f"Home Assistant API read failed for {path}: {error}"
            ) from error

    def _post_json(
        self, path: str, payload: dict[str, Any], timeout: int | None = None
    ) -> dict[str, Any]:
        request = Request(
            f"{self._api_base}/{path.lstrip('/')}",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(
                request, timeout=timeout if timeout is not None else self._timeout
            ) as response:
                result = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise HomeAssistantAPIError(
                f"Home Assistant API action failed for {path}: {error}"
            ) from error
        if not isinstance(result, dict):
            raise HomeAssistantAPIError("Unexpected Home Assistant action response")
        return result

    def get_states(self) -> list[dict[str, Any]]:
        """Read all Home Assistant states."""

        payload = json.loads(self._get("states", "application/json"))
        if not isinstance(payload, list):
            raise HomeAssistantAPIError("Unexpected states response")
        return payload

    def get_error_log(self) -> str:
        """Read the legacy file-backed Home Assistant error log."""

        return self._get("error_log", "text/plain").decode(
            "utf-8", errors="replace"
        )

    @staticmethod
    def _receive_websocket_json(connection: Any) -> dict[str, Any]:
        message = connection.recv()
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        try:
            payload = json.loads(message)
        except (TypeError, json.JSONDecodeError) as error:
            raise HomeAssistantAPIError(
                "Invalid Home Assistant WebSocket response"
            ) from error
        if not isinstance(payload, dict):
            raise HomeAssistantAPIError(
                "Unexpected Home Assistant WebSocket response"
            )
        return payload

    def get_system_log(self) -> list[dict[str, Any]]:
        """Read warning and error records through the Home Assistant WebSocket API."""

        factory = self._websocket_factory
        if factory is None:
            try:
                from websocket import create_connection
            except ImportError as error:
                raise HomeAssistantAPIError(
                    "WebSocket client dependency is unavailable"
                ) from error
            factory = create_connection

        connection = None
        try:
            connection = factory(self._websocket_url, timeout=self._timeout)
            auth_required = self._receive_websocket_json(connection)
            if auth_required.get("type") != "auth_required":
                raise HomeAssistantAPIError(
                    "Home Assistant WebSocket did not request authentication"
                )

            connection.send(
                json.dumps({"type": "auth", "access_token": self._token})
            )
            auth_result = self._receive_websocket_json(connection)
            if auth_result.get("type") != "auth_ok":
                raise HomeAssistantAPIError(
                    "Home Assistant WebSocket authentication failed"
                )

            connection.send(json.dumps({"id": 1, "type": "system_log/list"}))
            response = self._receive_websocket_json(connection)
            if (
                response.get("id") != 1
                or response.get("type") != "result"
                or response.get("success") is not True
                or not isinstance(response.get("result"), list)
            ):
                raise HomeAssistantAPIError(
                    "Home Assistant system log response was unsuccessful"
                )
            return [
                item for item in response["result"] if isinstance(item, dict)
            ]
        except HomeAssistantAPIError:
            raise
        except Exception as error:
            raise HomeAssistantAPIError(
                f"Home Assistant WebSocket read failed: {type(error).__name__}"
            ) from error
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def generate_ai_task(
        self, entity_id: str, task_name: str, instructions: str
    ) -> dict[str, Any]:
        """Run an explicitly approved AI Task and return its service response."""

        return self._post_json(
            "services/ai_task/generate_data?return_response",
            {
                "entity_id": entity_id,
                "task_name": task_name,
                "instructions": instructions,
            },
            timeout=self._ai_timeout,
        )

    def check_config(self) -> dict[str, Any]:
        """Validate the current Home Assistant configuration without restarting."""

        return self._post_json("config/core/check_config", {})


def summarize_states(
    states: list[dict[str, Any]], max_problem_entities: int
) -> dict[str, Any]:
    """Create a compact state-health summary without changing any entity."""

    state_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    problem_domain_counts: Counter[str] = Counter()
    problems: list[dict[str, str]] = []

    for item in states:
        entity_id = str(item.get("entity_id", ""))
        state = str(item.get("state", ""))
        state_counts[state] += 1
        domain = entity_id.partition(".")[0] or "unknown"
        domain_counts[domain] += 1
        if state in {"unavailable", "unknown"}:
            problem_domain_counts[domain] += 1
            attributes = item.get("attributes")
            friendly_name = ""
            if isinstance(attributes, dict):
                friendly_name = str(attributes.get("friendly_name", ""))
            problems.append(
                {
                    "entity_id": entity_id,
                    "name": friendly_name,
                    "state": state,
                }
            )

    problems.sort(key=lambda item: (item["state"], item["entity_id"]))
    return {
        "total": len(states),
        "unavailable": state_counts["unavailable"],
        "unknown": state_counts["unknown"],
        "problem_entities_total": len(problems),
        "problem_entities": problems[:max_problem_entities],
        "problem_entities_truncated": max(0, len(problems) - max_problem_entities),
        "problem_domains": [
            {"domain": domain, "count": count}
            for domain, count in problem_domain_counts.most_common(10)
        ],
        "top_domains": dict(domain_counts.most_common(10)),
    }


def _severity(line: str) -> str | None:
    upper = line.upper()
    if "CRITICAL" in upper:
        return "critical"
    if "ERROR" in upper or "EXCEPTION" in upper or "TRACEBACK" in upper:
        return "error"
    if "WARNING" in upper:
        return "warning"
    return None


def summarize_error_log(
    error_log: str,
    max_log_lines: int,
    redact_sensitive_data: bool,
    max_samples: int = 30,
) -> dict[str, Any]:
    """Summarize recent error-log lines and redact their sample text."""

    lines = error_log.splitlines()[-max_log_lines:]
    counts: Counter[str] = Counter()
    unique_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    redaction_count = 0

    for line in lines:
        severity = _severity(line)
        if severity is None:
            continue
        counts[severity] += 1
        unique_counts[severity] += 1
        if len(samples) >= max_samples:
            continue
        sample = line.strip()
        if redact_sensitive_data:
            sample, count = redact_text(sample)
            redaction_count += count
        samples.append(
            {
                "severity": severity,
                "logger": "legacy_error_log",
                "occurrences": 1,
                "message": sample[:2000],
            }
        )

    return {
        "available": True,
        "source": "legacy_error_log",
        "error": None,
        "lines_scanned": len(lines),
        "unique_entries": sum(unique_counts.values()),
        "total_occurrences": sum(counts.values()),
        "critical": counts["critical"],
        "errors": counts["error"],
        "warnings": counts["warning"],
        "unique_critical": unique_counts["critical"],
        "unique_errors": unique_counts["error"],
        "unique_warnings": unique_counts["warning"],
        "top_loggers": [],
        "samples": samples,
        "redactions": redaction_count,
    }


def summarize_system_log(
    entries: list[dict[str, Any]],
    max_entries: int,
    redact_sensitive_data: bool,
    max_samples: int = 30,
) -> dict[str, Any]:
    """Summarize structured system-log records returned by Home Assistant."""

    occurrence_counts: Counter[str] = Counter()
    unique_counts: Counter[str] = Counter()
    logger_occurrences: Counter[str] = Counter()
    logger_unique: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    redaction_count = 0
    selected_entries = entries[:max_entries]

    for item in selected_entries:
        severity = str(item.get("level", "")).lower()
        if severity not in {"critical", "error", "warning"}:
            continue

        try:
            occurrence_count = max(1, int(item.get("count", 1)))
        except (TypeError, ValueError):
            occurrence_count = 1
        occurrence_counts[severity] += occurrence_count
        unique_counts[severity] += 1
        messages = item.get("message")
        if isinstance(messages, list) and messages:
            message = str(messages[-1])
        else:
            message = str(messages or "")
        logger_name = str(item.get("name", "")).strip() or "unknown"
        sample = message
        exception = str(item.get("exception", "")).strip()
        if exception:
            sample = f"{sample}\n{exception}"
        if redact_sensitive_data:
            sample, count = redact_text(sample)
            redaction_count += count
            logger_name, count = redact_text(logger_name)
            redaction_count += count
        logger_occurrences[logger_name] += occurrence_count
        logger_unique[logger_name] += 1
        records.append(
            {
                "severity": severity,
                "logger": logger_name[:240],
                "occurrences": occurrence_count,
                "message": sample[:2000],
            }
        )

    severity_order = {"critical": 0, "error": 1, "warning": 2}
    records.sort(
        key=lambda record: (
            -record["occurrences"],
            severity_order[record["severity"]],
            record["logger"],
        )
    )

    return {
        "available": True,
        "source": "system_log_websocket",
        "error": None,
        "lines_scanned": len(selected_entries),
        "unique_entries": sum(unique_counts.values()),
        "total_occurrences": sum(occurrence_counts.values()),
        "critical": occurrence_counts["critical"],
        "errors": occurrence_counts["error"],
        "warnings": occurrence_counts["warning"],
        "unique_critical": unique_counts["critical"],
        "unique_errors": unique_counts["error"],
        "unique_warnings": unique_counts["warning"],
        "top_loggers": [
            {
                "logger": logger,
                "occurrences": occurrences,
                "unique_entries": logger_unique[logger],
            }
            for logger, occurrences in logger_occurrences.most_common(10)
        ],
        "samples": records[:max_samples],
        "redactions": redaction_count,
    }


def unavailable_log_summary(error: str) -> dict[str, Any]:
    """Return an empty log summary without discarding a valid state scan."""

    return {
        "available": False,
        "source": None,
        "error": error,
        "lines_scanned": 0,
        "unique_entries": 0,
        "total_occurrences": 0,
        "critical": 0,
        "errors": 0,
        "warnings": 0,
        "unique_critical": 0,
        "unique_errors": 0,
        "unique_warnings": 0,
        "top_loggers": [],
        "samples": [],
        "redactions": 0,
    }


def collect_snapshot(
    client: HomeAssistantClient, options: CollectorOptions
) -> dict[str, Any]:
    """Collect one local-only, read-only health snapshot."""

    states = client.get_states()
    try:
        system_log = client.get_system_log()
        log_summary = summarize_system_log(
            system_log,
            options.max_log_lines,
            options.redact_sensitive_data,
        )
    except HomeAssistantAPIError as websocket_error:
        try:
            error_log = client.get_error_log()
            log_summary = summarize_error_log(
                error_log,
                options.max_log_lines,
                options.redact_sensitive_data,
            )
        except HomeAssistantAPIError as legacy_error:
            log_summary = unavailable_log_summary(
                "A Home Assistant hibanaplója nem érhető el: "
                f"{websocket_error}; tartalék lekérés: {legacy_error}"
            )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "local_read_only",
        "states": summarize_states(states, options.max_problem_entities),
        "log": log_summary,
    }
