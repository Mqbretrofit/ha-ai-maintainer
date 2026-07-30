# Changelog

## 0.5.1

- Make Codex independently inspect selected files even when the advisory AI
  labels every reported problem as not file-fixable.
- Show Codex's bounded, concrete explanation when no safe file change is found.

## 0.5.0

- Add one-click, approval-gated Codex proposals from the latest AI diagnosis.
- Pass only bounded, redacted evidence and treat it as untrusted data.
- Add per-run repair-path selection to avoid unnecessarily large copies.
- Add disabled-by-default, separately approved, revalidated cleanup of
  orphaned or persistently unavailable entity-registry entries.

## 0.4.0

- Add isolated local Codex proposals for selected Home Assistant files.
- Require separate approvals for proposal generation, applying, and rollback.
- Add file-level backups, concurrent-change detection, Home Assistant
  configuration validation, and automatic restore on validation failure.
- Keep local repair disabled by default and never restart Home Assistant
  automatically.

## 0.3.0

- Add approval-gated Codex repair dispatch for known, allowlisted issues.
- Add an optional masked GitHub workflow-token setting.
- Keep remediation isolated from Home Assistant and open changes as draft PRs.

## 0.2.2

- Allow first-use OpenAI AI Task entities whose initial state is `unknown`.

## 0.2.1

- Improve automatic OpenAI AI Task selection when multiple AI Task entities exist.

## 0.2.0

- Add user-approved OpenAI AI Task diagnosis.
- Add prompt-injection boundaries and bounded diagnostic payloads.
- Display the advisory AI report in the Ingress dashboard.

## 0.1.2

- Add unique issue and total occurrence counters.
- Add problem-domain and log-source summaries.
- Sort repeated log issues by frequency.

## 0.1.1

- Use Home Assistant's structured system log over the WebSocket API.
- Preserve entity results when the log API is unavailable.

## 0.1.0

- Initial read-only entity and error-log observer.
- Local Ingress dashboard with sensitive-data redaction.
