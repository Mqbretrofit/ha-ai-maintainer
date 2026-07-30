# Changelog

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
