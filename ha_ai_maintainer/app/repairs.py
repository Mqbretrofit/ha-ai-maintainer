"""Allowlisted, approval-gated handoff of known repairs to GitHub Codex jobs."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GITHUB_API_VERSION = "2022-11-28"
MAX_EVIDENCE_CHARS = 500

REPAIR_TARGETS: dict[str, dict[str, str]] = {
    "anthbot_map_attributes_too_large": {
        "title": "Anthbot Map – túlméretes állapotattribútumok",
        "repository": "Mqbretrofit/ha-anthbot-map",
        "workflow": "codex-repair.yml",
        "workflow_url": (
            "https://github.com/Mqbretrofit/ha-anthbot-map/"
            "actions/workflows/codex-repair.yml"
        ),
        "repair_id": "map_attributes_too_large",
        "ref": "main",
    }
}


class RepairDispatchError(RuntimeError):
    """Raised when an approved repair cannot be dispatched safely."""


def _looks_like_anthbot_map_attribute_warning(
    logger: str, message: str
) -> bool:
    normalized_logger = logger.strip().casefold()
    normalized_message = " ".join(message.casefold().split())
    return (
        normalized_logger == "homeassistant.components.recorder.db_schema"
        and "state attributes for " in normalized_message
        and "anthbot" in normalized_message
        and "_map" in normalized_message
        and "exceed maximum size" in normalized_message
    )


def find_repair_candidates(snapshot: dict[str, Any] | None) -> list[dict[str, str]]:
    """Find only known, deterministic repair routes in a local snapshot."""

    if not isinstance(snapshot, dict):
        return []
    log = snapshot.get("log")
    if not isinstance(log, dict):
        return []
    samples = log.get("samples")
    if not isinstance(samples, list):
        return []

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        logger = str(sample.get("logger", ""))
        message = str(sample.get("message", ""))
        if _looks_like_anthbot_map_attribute_warning(logger, message):
            target = REPAIR_TARGETS["anthbot_map_attributes_too_large"]
            return [
                {
                    "id": "anthbot_map_attributes_too_large",
                    "title": target["title"],
                    "repository": target["repository"],
                    "workflow_url": target["workflow_url"],
                    "evidence": message[:MAX_EVIDENCE_CHARS],
                }
            ]
    return []


def dispatch_repair(
    token: str,
    candidate_id: str,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, str]:
    """Dispatch one allowlisted workflow without sending diagnostic content."""

    target = REPAIR_TARGETS.get(candidate_id)
    if target is None:
        raise RepairDispatchError("Ez a javítási cél nincs engedélyezve.")
    if not token.strip():
        raise RepairDispatchError(
            "Nincs beállítva GitHub workflow-token az alkalmazás konfigurációjában."
        )

    repository = target["repository"]
    workflow = target["workflow"]
    url = (
        f"https://api.github.com/repos/{repository}/"
        f"actions/workflows/{workflow}/dispatches"
    )
    payload = {
        "ref": target["ref"],
        "inputs": {"repair_id": target["repair_id"]},
    }
    request = Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "ha-ai-maintainer",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with opener(request, timeout=20) as response:
            status = getattr(response, "status", 204)
    except HTTPError as error:
        if error.code in {401, 403}:
            raise RepairDispatchError(
                "A GitHub-token érvénytelen, lejárt, vagy nincs Actions írási joga."
            ) from error
        if error.code == 404:
            raise RepairDispatchError(
                "A GitHub Codex-workflow nem található a célprojektben."
            ) from error
        raise RepairDispatchError(
            f"A GitHub elutasította a workflow indítását (HTTP {error.code})."
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise RepairDispatchError(
            "A GitHub workflow indítása hálózati hiba miatt sikertelen."
        ) from error

    if status not in {200, 201, 204}:
        raise RepairDispatchError(
            f"Váratlan GitHub-válasz a workflow indításakor (HTTP {status})."
        )
    return {
        "candidate_id": candidate_id,
        "repository": repository,
        "workflow_url": target["workflow_url"],
        "status": "dispatched",
    }
