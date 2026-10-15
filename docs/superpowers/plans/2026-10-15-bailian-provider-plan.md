# Bailian Provider Implementation Plan

1. Refactor the provider router into explicit `fake`, `ollama`, and `openai_compatible` paths.
2. Add Bailian-compatible chat completions, JSON extraction, Pydantic validation, retry classification, and secret-safe errors.
3. Expose non-secret runtime metadata with provider label, cloud/local mode, and a masked key hint.
4. Pass cloud configuration only to the API and worker containers through Compose.
5. Update the web runtime indicator and privacy copy for cloud inference.
6. Add provider tests for success, fenced JSON, validation retry, HTTP retry, authentication failure, missing configuration, and key masking.
7. Update project documentation, run backend and frontend tests, rebuild Docker services, and verify runtime endpoints.
