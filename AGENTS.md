# Repository guidance

## Purpose

This repository contains a Home Assistant app that observes system health and
prepares sanitized diagnostics for a future AI-assisted maintenance workflow.

## Safety boundaries

- Keep observation and remediation separate.
- Keep observation read-only. Local remediation requires the feature option,
  a proposal approval, a separate apply approval, a file-level backup, and a
  successful Home Assistant configuration check.
- Never let Codex work directly in the live `homeassistant_config` mount. Give
  it only a bounded, filtered copy under the app data directory.
- Do not add entity control, device service calls, automatic restart, Docker
  access, or unattended deployment.
- Do not transmit logs, states, diagnostics, credentials, locations, or entity
  identifiers to an external service by default.
- Never commit API keys, GitHub tokens, Home Assistant tokens, diagnostic dumps,
  coordinates, serial numbers, email addresses, or private URLs.
- Preserve disabled-by-default remediation and read-only automatic scans.

## Development

- Support the `amd64` architecture used by the target Home Assistant OS system.
- Keep `aarch64` support when changes are architecture-neutral.
- Use Python standard-library modules unless a dependency is necessary and
  explicitly justified.
- Validate all option values and treat Home Assistant API responses as
  untrusted input.
- Escape or assign UI data through `textContent`; do not render log text as HTML.
- Add or update tests for redaction, state summaries, and log parsing.

## Verification

Run before proposing a change:

```text
python3 -m unittest discover -s tests -v
python3 -m compileall -q ha_ai_maintainer/app tests
python3 tools/validate_yaml.py
```

## Pull requests

- Use a dedicated branch and open a draft PR.
- Explain any new permission in `ha_ai_maintainer/config.yaml`.
- State what data leaves Home Assistant, where it goes, and which approval gate
  protects it.
