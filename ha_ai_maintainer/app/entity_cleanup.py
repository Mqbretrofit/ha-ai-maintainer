"""Approval-gated cleanup of demonstrably orphaned entity-registry entries."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

MAX_ENTITY_CANDIDATES = 500
MAX_ENTITY_DELETIONS = 50
MIN_UNAVAILABLE_DAYS = 7
MAX_UNAVAILABLE_DAYS = 3650
ENTITY_ID_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


class EntityCleanupError(RuntimeError):
    """Raised when an entity cleanup cannot proceed safely."""


class EntityRegistryClient(Protocol):
    """Home Assistant reads and mutation required by the cleanup flow."""

    def get_states(self) -> list[dict[str, Any]]:
        """Return current states."""

    def get_entity_registry(self) -> list[dict[str, Any]]:
        """Return current entity-registry entries."""

    def get_config_entries(self) -> list[dict[str, Any]]:
        """Return current config entries."""

    def remove_entity_registry_entry(self, entity_id: str) -> None:
        """Remove one entity-registry entry."""


def _valid_entity_id(value: Any) -> str | None:
    entity_id = value.strip() if isinstance(value, str) else ""
    if not entity_id or len(entity_id) > 255:
        return None
    return entity_id if ENTITY_ID_PATTERN.fullmatch(entity_id) else None


def _last_changed(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def find_entity_cleanup_candidates(
    client: EntityRegistryClient,
    minimum_unavailable_days: int = 30,
    maximum: int = MAX_ENTITY_CANDIDATES,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Find unavailable registry entries and classify their deletion risk."""

    if maximum < 1 or maximum > MAX_ENTITY_CANDIDATES:
        raise EntityCleanupError("Érvénytelen entitásjelölt-korlát.")
    if not MIN_UNAVAILABLE_DAYS <= minimum_unavailable_days <= MAX_UNAVAILABLE_DAYS:
        raise EntityCleanupError("Érvénytelen unavailable-időtartam.")
    reference_time = now or datetime.now(UTC)
    if reference_time.tzinfo is None:
        raise EntityCleanupError("Az időbélyegnek időzónát kell tartalmaznia.")
    stale_before = reference_time.astimezone(UTC) - timedelta(
        days=minimum_unavailable_days
    )

    unavailable: dict[str, dict[str, Any]] = {}
    for item in client.get_states():
        if not isinstance(item, dict) or item.get("state") != "unavailable":
            continue
        entity_id = _valid_entity_id(item.get("entity_id"))
        if entity_id is not None:
            unavailable[entity_id] = item

    active_config_entries = {
        entry_id
        for item in client.get_config_entries()
        if isinstance(item, dict)
        and isinstance(entry_id := item.get("entry_id"), str)
        and entry_id
    }

    candidates: list[dict[str, str]] = []
    for entry in client.get_entity_registry():
        if not isinstance(entry, dict):
            continue
        entity_id = _valid_entity_id(entry.get("entity_id"))
        config_entry_id = entry.get("config_entry_id")
        if entity_id is None or entity_id not in unavailable:
            continue
        is_orphaned = isinstance(config_entry_id, str) and bool(config_entry_id) and (
            config_entry_id not in active_config_entries
        )
        changed_at = _last_changed(unavailable[entity_id].get("last_changed"))
        is_stale = changed_at is not None and changed_at <= stale_before

        state = unavailable[entity_id]
        attributes = state.get("attributes")
        friendly_name = ""
        if isinstance(attributes, dict):
            friendly_name = str(attributes.get("friendly_name", "")).strip()
        registry_name = str(
            entry.get("name") or entry.get("original_name") or ""
        ).strip()
        if is_orphaned:
            kind = "orphaned"
            review_level = "confirmed"
            reason = (
                "Igazolt árva: az entitás unavailable, és a hozzá tartozó "
                "konfigurációs bejegyzés már nem létezik."
            )
        elif is_stale:
            kind = "long_unavailable"
            review_level = "confirmed"
            reason = (
                "A Home Assistant jelenlegi állapotadata szerint legalább "
                f"{minimum_unavailable_days} napja folyamatosan unavailable. "
                "Aktív integráció vagy YAML később újra létrehozhatja."
            )
        elif isinstance(config_entry_id, str) and config_entry_id:
            kind = "manual_review"
            review_level = "manual"
            reason = (
                "Kézi ellenőrzés szükséges: az entitás unavailable, de egy "
                "jelenleg is létező integrációhoz tartozik, és a "
                f"{minimum_unavailable_days} napos kor "
                "nem bizonyítható. Csak akkor töröld, ha az eszköz vagy entitás "
                "szándékosan végleg megszűnt; az integráció újra létrehozhatja."
            )
        else:
            kind = "manual_review"
            review_level = "manual"
            reason = (
                "Kézi ellenőrzés szükséges: nincs konfigurációs bejegyzéshez "
                "kötve, ezért YAML-ból vagy Segédből is származhat. A forrás "
                "eltávolítása nélkül újra megjelenhet."
            )
        candidates.append(
            {
                "entity_id": entity_id,
                "name": friendly_name or registry_name,
                "platform": str(entry.get("platform", ""))[:100],
                "kind": kind,
                "review_level": review_level,
                "reason": reason,
            }
        )

    candidates.sort(
        key=lambda item: (
            item["review_level"] == "manual",
            item["entity_id"],
        )
    )
    return candidates[:maximum]


def delete_entity_cleanup_candidates(
    client: EntityRegistryClient,
    requested_entity_ids: list[str],
    minimum_unavailable_days: int = 30,
) -> dict[str, Any]:
    """Revalidate and remove an explicitly selected set of cleanup candidates."""

    if not isinstance(requested_entity_ids, list):
        raise EntityCleanupError("Az entitáslista érvénytelen.")
    normalized: list[str] = []
    for value in requested_entity_ids:
        entity_id = _valid_entity_id(value)
        if entity_id is None:
            raise EntityCleanupError("Az entitáslista érvénytelen azonosítót tartalmaz.")
        if entity_id not in normalized:
            normalized.append(entity_id)
    if not normalized:
        raise EntityCleanupError("Nincs törlésre kiválasztott entitás.")
    if len(normalized) > MAX_ENTITY_DELETIONS:
        raise EntityCleanupError(
            f"Egyszerre legfeljebb {MAX_ENTITY_DELETIONS} entitás törölhető."
        )

    current_candidates = {
        item["entity_id"]: item
        for item in find_entity_cleanup_candidates(
            client, minimum_unavailable_days
        )
    }
    no_longer_safe = [
        entity_id for entity_id in normalized if entity_id not in current_candidates
    ]
    if no_longer_safe:
        raise EntityCleanupError(
            "A kiválasztott entitások közül legalább egy már nem unavailable, "
            "vagy már nincs a regiszterben. Indíts új jelöltvizsgálatot."
        )

    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for index, entity_id in enumerate(normalized):
        try:
            client.remove_entity_registry_entry(entity_id)
        except Exception as error:
            failed.append(
                {
                    "entity_id": entity_id,
                    "error": str(error)[:300] or type(error).__name__,
                }
            )
            failed.extend(
                {
                    "entity_id": skipped,
                    "error": "Az előző hiba miatt nem került sor a törlésre.",
                }
                for skipped in normalized[index + 1 :]
            )
            break
        deleted.append(entity_id)
    message = f"{len(deleted)} entitásregiszter-bejegyzés törölve."
    if failed:
        message += f" {len(failed)} bejegyzés törlése sikertelen vagy kimaradt."
    else:
        message += (
            " Ha az integráció később újra létrehozza őket, ismét megjelenhetnek."
        )
    return {
        "deleted": deleted,
        "failed": failed,
        "count": len(deleted),
        "message": message,
    }
