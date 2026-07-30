"""Read-only collection and summarization of Home Assistant health data."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from redaction import redact_text

DEFAULT_API_BASE = "http://supervisor/core/api"


class HomeAssistantAPIError(RuntimeError):
    """Raised when the internal Home Assistant API cannot be read."""


@dataclass(frozen=True)
class CollectorOptions:
    """Validated runtime options."""

    max_problem_entities: int = 50
    max_log_lines: int = 1000
    redact_sensitive_data: bool = True


class HomeAssistantClient:
    """Small read-only client for the Home Assistant API proxy."""

    def __init__(
        self,
        token: str | None = None,
        api_base: str = DEFAULT_API_BASE,
        timeout: int = 20,
    ) -> None:
        self._token = token or os.environ.get("SUPERVISOR_TOKEN", "")
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout
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

    def get_states(self) -> list[dict[str, Any]]:
        """Read all Home Assistant states."""

        payload = json.loads(self._get("states", "application/json"))
        if not isinstance(payload, list):
            raise HomeAssistantAPIError("Unexpected states response")
        return payload

    def get_error_log(self) -> str:
        """Read the current Home Assistant error log."""

        return self._get("error_log", "text/plain").decode(
            "utf-8", errors="replace"
        )


def summarize_states(
    states: list[dict[str, Any]], max_problem_entities: int
) -> dict[str, Any]:
    """Create a compact state-health summary without changing any entity."""

    state_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    problems: list[dict[str, str]] = []

    for item in states:
        entity_id = str(item.get("entity_id", ""))
        state = str(item.get("state", ""))
        state_counts[state] += 1
        domain = entity_id.partition(".")[0] or "unknown"
        domain_counts[domain] += 1
        if state in {"unavailable", "unknown"}:
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
        "problem_entities": problems[:max_problem_entities],
        "problem_entities_truncated": max(0, len(problems) - max_problem_entities),
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
    samples: list[dict[str, str]] = []
    redaction_count = 0

    for line in lines:
        severity = _severity(line)
        if severity is None:
            continue
        counts[severity] += 1
        if len(samples) >= max_samples:
            continue
        sample = line.strip()
        if redact_sensitive_data:
            sample, count = redact_text(sample)
            redaction_count += count
        samples.append({"severity": severity, "message": sample[:2000]})

    return {
        "lines_scanned": len(lines),
        "critical": counts["critical"],
        "errors": counts["error"],
        "warnings": counts["warning"],
        "samples": samples,
        "redactions": redaction_count,
    }


def collect_snapshot(
    client: HomeAssistantClient, options: CollectorOptions
) -> dict[str, Any]:
    """Collect one local-only, read-only health snapshot."""

    states = client.get_states()
    error_log = client.get_error_log()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "local_read_only",
        "states": summarize_states(states, options.max_problem_entities),
        "log": summarize_error_log(
            error_log,
            options.max_log_lines,
            options.redact_sensitive_data,
        ),
    }
