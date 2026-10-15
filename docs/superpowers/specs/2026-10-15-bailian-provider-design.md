# Bailian Qwen Provider Design

## Goal

Add real cloud-backed model inference to the personal multi-agent fitness platform without changing its LangGraph workflow. The first cloud configuration uses Alibaba Cloud Bailian's OpenAI-compatible API with `qwen-plus`.

The platform continues to support three explicit modes:

- `fake`: deterministic simulation for offline demonstrations.
- `ollama`: local model inference.
- `openai_compatible`: real external model inference, initially configured for Bailian.

There is no automatic fallback from real inference to the fake provider. A failed cloud request must remain visibly failed so simulated output is never presented as model output.

## Architecture

All agent nodes continue to call one provider-neutral function:

```text
LangGraph agent node
  -> generate(agent, context, schema)
  -> provider router
       -> fake
       -> ollama
       -> openai_compatible
            -> Bailian / qwen-plus
```

The quality, recovery, training, fat-loss, review, coach, risk, and learning agents retain separate prompts, contexts, calls, outputs, durations, and database run records. The cloud adapter changes only model transport; it does not collapse the agents into one request.

The existing deterministic pre-safety check, conflict detector, review route, risk review, final safety gate, and controlled learning proposal rules remain authoritative around model output.

## Configuration

The root `.env` accepts:

```env
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-plus
MODEL_API_KEY=
```

`MODEL_API_KEY` is injected only into the API and worker containers. It is never compiled into the web image, written to application tables, or returned by an endpoint.

Existing Ollama variable names remain supported for `MODEL_PROVIDER=ollama`. The runtime model identifier is normalized to `MODEL_NAME` for cloud mode and `OLLAMA_MODEL` for Ollama mode.

## Bailian Request Flow

The adapter calls:

```text
POST {MODEL_BASE_URL}/chat/completions
Authorization: Bearer {MODEL_API_KEY}
```

Each request contains the agent-specific system prompt and a JSON user context. It requests JSON output and then validates the returned content against the Pydantic schema supplied by the calling node.

The adapter may remove a Markdown JSON code fence before validation, but it must not repair arbitrary invalid content locally. On invalid structured output, the second request adds a concise schema-correction instruction.

Calls remain serialized through the existing model semaphore. This reduces rate-limit bursts and keeps the run trace easier to follow. A planning run therefore makes separate, sequential calls for its participating agents.

## Failure Semantics

- Missing base URL, model, or API key fails before network access with a safe configuration message.
- HTTP `401` and `403` fail immediately and are not retried.
- Timeout, transport errors, HTTP `429`, HTTP `5xx`, and invalid model JSON receive one retry.
- Other HTTP `4xx` responses fail immediately.
- After the retry is exhausted, the current `AgentRun` and parent planning run are marked failed.
- No failure path switches to `fake` automatically.
- Error messages are sanitized so the API key cannot appear in logs, API responses, or database error fields.

The readiness endpoint verifies PostgreSQL and application configuration without making a paid model request. The first planning run is the first real credential and provider test.

## Runtime API And UI

`GET /api/v1/system/runtime` returns non-secret runtime metadata:

```json
{
  "provider": "openai_compatible",
  "provider_label": "Alibaba Cloud Bailian",
  "model": "qwen-plus",
  "mode": "live-cloud",
  "api_key_configured": true,
  "api_key_hint": "****8A2F"
}
```

Only the final four characters may be exposed. If the key is absent or too short, `api_key_hint` is `null`.

The web header shows a read-only status such as:

```text
Cloud inference
Alibaba Cloud Bailian / qwen-plus
API KEY configured / ****8A2F
```

When the key is missing, the header shows a clear configuration warning. Fake and Ollama modes retain distinct simulated and local labels. Agent trace records continue to show the actual provider and model used for the planning run.

## Privacy And Cost Boundary

Cloud mode sends the profile, check-in data, and bounded recent history needed by each agent to Bailian. It does not send the API key anywhere except the Bailian authorization header. The UI must identify cloud mode so the user can distinguish it from local inference.

History limits already applied by each node remain in place to control token use. The first version does not add token billing estimates because Bailian usage fields and prices can vary by model; raw secrets and complete prompts are also not persisted.

## Tests

Automated tests use mocked HTTP responses and never consume Bailian quota. Coverage includes:

- successful structured output;
- JSON content wrapped in a Markdown code fence;
- invalid model output followed by a successful retry;
- timeout and HTTP `429`/`5xx` retry behavior;
- immediate HTTP `401`/`403` failure;
- missing cloud configuration;
- API key masking and absence from runtime responses and exceptions;
- runtime mode labels for fake, Ollama, and cloud providers;
- regression coverage for existing Fake Provider behavior and LangGraph safety gates.

The frontend production build and backend test suite must pass before the Compose services are rebuilt. A real end-to-end Bailian call is performed only after the user adds a key to `.env`.
