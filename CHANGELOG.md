# Changelog

## 0.1.1

- Read current warning and error records through the Home Assistant WebSocket
  `system_log/list` API.
- Keep entity-health results visible when log collection is unavailable.
- Retain the legacy REST error-log endpoint only as a compatibility fallback.

## 0.1.0

- Initial local-only Home Assistant health observer.
- Read-only entity-state and error-log collection through the Home Assistant API.
- Sensitive-data redaction and local Ingress dashboard.
- No AI calls, GitHub writes, configuration access, or device control.
