# Changelog

## 0.6.2

- Classify Home Assistant `restored: true` registry states as confirmed
  “integration no longer provides this entity” cleanup candidates.
- Add an explicit bulk-selection button for up to 50 Home Assistant-confirmed
  removable entries while preserving the separate delete confirmation.

## 0.6.1

- Require actionable manual repair instructions when AI cannot justify a file
  change, and persist them as a successful manual-action result.
- Add a clearly marked manual-review group for all other unavailable
  entity-registry entries, including active-integration and YAML/helper cases.
- Never preselect cleanup entries and revalidate them before deletion.

## 0.6.0

- Replace the kernel-dependent local Codex CLI sandbox with a direct, tool-free
  OpenAI Responses API request and strict Structured Outputs.
- Require existing allowlisted paths and matching original SHA-256 hashes for
  every proposed replacement before computing and displaying the diff.
- Preserve all approval, backup, concurrent-change, configuration-check,
  automatic-restore, and rollback gates.
- Remove Node.js, npm, and Codex CLI runtime dependencies from the app image.

## 0.5.2

- Replace the nested bubblewrap sandbox with Codex's legacy Landlock backend
  for compatibility with restricted Home Assistant application containers.
- Keep workspace-only writes and network denial; do not fall back to
  unrestricted Codex execution.
- Verify Landlock before API authentication and in the container CI build.

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
