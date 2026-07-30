# Changelog

## 0.5.2

- Use Codex's legacy Landlock sandbox inside the Home Assistant application
  container instead of the unsupported nested bubblewrap backend.
- Add a preflight check and container CI smoke test while preserving
  workspace-only writes and disabled command network access.

## 0.5.1

- Treat the diagnostic AI's fixability labels as non-binding advice and require
  Codex to perform its own evidence-based review of the selected files.
- Preserve and display a bounded Codex explanation when no safe file
  modification can be proposed.

## 0.5.0

- Connect the latest approved AI diagnosis and its bounded, redacted evidence
  to an explicitly approved local Codex proposal.
- Tighten the AI prompt so network, offline-device, re-pairing, restart, cloud,
  and device-originated data faults are not presented as file-fixable.
- Allow each local proposal to narrow the configured file paths, with large
  `www` and `dashboards` directories unselected by default in the dashboard.
- Add a disabled-by-default, separately approved entity-registry cleanup for
  orphaned entries and entries continuously unavailable beyond a configurable
  threshold.
- Revalidate every selected entity immediately before deletion; never
  auto-select or auto-delete entries.

## 0.4.0

- Add disabled-by-default local Codex repair proposals for explicitly
  allowlisted Home Assistant configuration paths.
- Run Codex only against a filtered copy with a deny-by-default filesystem
  permission profile and no Supervisor, GitHub, or API-key environment variables.
- Show the complete proposed diff before a separate apply approval.
- Back up every affected file, detect concurrent changes, validate the live
  configuration, and automatically restore files when validation fails.
- Add a separately approved rollback without automatic Home Assistant restart.
- Mark `0.4.0` as a breaking update because it adds a writable
  `homeassistant_config` mount; local repair itself remains disabled by default.

## 0.3.0

- Detect the allowlisted oversized Anthbot map-attribute Recorder warning.
- Add a separate user confirmation before dispatching a Codex repair.
- Send only a fixed repair identifier to the target GitHub workflow; no logs,
  entity data, or Home Assistant configuration leave the app.
- Keep GitHub dispatch disabled until an optional fine-grained workflow token
  is configured.

## 0.2.2

- Treat a never-used AI Task with `unknown` state as selectable.
- Keep only `unavailable` AI Task entities out of active selection.

## 0.2.1

- Prefer the canonical and available OpenAI AI Task entity when duplicates exist.
- Include matching entity IDs in the ambiguity error for easier troubleshooting.

## 0.2.0

- Add explicit, confirmation-gated diagnosis through Home Assistant AI Task.
- Reuse the configured OpenAI AI Task entity without reading or storing its API key.
- Send only bounded, redacted diagnostics and exclude problem entity identifiers.
- Treat log content as untrusted prompt data and render AI output as plain text.
- Keep all AI output advisory-only with no device or configuration changes.

## 0.1.2

- Separate unique system-log issues from their total occurrence count.
- Rank log samples by occurrence count and show their logger separately.
- Group unavailable and unknown entities by domain.
- Show the total number of problem entities when the table is truncated.

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
