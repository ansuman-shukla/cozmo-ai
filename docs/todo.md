# TODO
## Cozmo Voice Platform

This file is the execution checklist for a test-driven build. Every feature starts with tests, then implementation, then refactor.

---

## 1. Repo Scaffolding And Tooling

- [ ] Create `uv` workspace root with `pyproject.toml`, `uv.lock`, and package boundaries for `backend`, `agent`, `knowledge`, and shared `contracts`
- [ ] Add shared `pytest` configuration, markers, and local developer commands
- [ ] Add Dockerfiles and baseline `docker-compose.yml`

Unit tests

- [ ] config loading parses required env vars and rejects invalid values
- [ ] package import smoke tests for `backend`, `agent`, and `knowledge`

Integration tests

- [ ] `uv sync` installs all packages cleanly
- [ ] `docker compose config` validates the stack definition

---

## 2. Domain Models And Configuration

- [ ] Define Mongo models and Pydantic schemas for `call_sessions`, `transcripts`, and `agent_configs`
- [ ] Define agent runtime config model
- [ ] Define metrics schema and event payload schema

Unit tests

- [ ] valid model payloads are accepted
- [ ] invalid DID, room name, and transfer target values are rejected
- [ ] defaults for history, retrieval, and timeout settings are applied correctly

Integration tests

- [ ] Mongo serialization and deserialization round-trip works
- [ ] indexes are created successfully on startup

---

## 3. Telephony Provisioning And Admission Metadata

- [x] Implement provisioning helpers or validation commands for LiveKit inbound trunk and dispatch rules
- [x] Define DID -> `agent_config_id` lookup behavior from SIP participant attributes
- [x] Persist call session creation from LiveKit room/participant events

Unit tests

- [x] SIP participant attributes map to DID and ANI correctly
- [ ] DID lookup chooses the expected `agent_config`
- [x] provisioning payload builders generate valid LiveKit API requests

Integration tests

- [x] LiveKit webhook/event payload creates a `call_sessions` record
- [x] unknown DID triggers fallback session status
- [x] duplicate webhook/event processing is idempotent

Operator notes as of April 5, 2026

- Twilio Elastic SIP trunk exists and has an active inbound number attached.
- Twilio origination now points to the LiveKit SIP endpoint with `transport=tcp`.
- LiveKit inbound SIP trunk `cozmo-inbound` exists for the active number.
- LiveKit dispatch rule `cozmo-inbound-dispatch` exists, routes rooms with the `call-` prefix, and dispatches `inbound-agent`.
- LiveKit outbound trunk cleanup is complete.
- LiveKit webhook can be configured to an HTTPS tunnel such as `https://<ngrok-host>/webhooks/livekit` for local testing.
- The LiveKit webhook signing API key must match the backend LiveKit API key/secret pair used for verification.
- Backend LiveKit webhook verification now uses the official SDK verifier with clock-skew leeway, and rejected requests are logged with the backend-side rejection reason.
- `.env.example` remains a template only; local runtime and Compose should read the real `.env`.
- Provider-side inbound telephony setup is complete; remaining setup is a running worker and eventual replacement of the temporary tunnel URL with a stable public backend URL.
- `COZMO_TWILIO_ACCOUNT_SID` and `COZMO_TWILIO_AUTH_TOKEN` are already present in `.env`.

---

## 4. FastAPI Control Plane

- [x] Build `/webhooks/livekit`, `/calls`, `/calls/{room_name}`, `/calls/{room_name}/transcript`
- [x] Build `/agents` list/get/create/update endpoints
- [x] Add `/health`, `/ready`, and `/metrics`

Unit tests

- [ ] endpoint auth rules are enforced correctly
- [ ] pagination and filter parsing for `/calls` works
- [ ] readiness aggregation reports dependency failures correctly

Integration tests

- [ ] API endpoints persist and return Mongo-backed data correctly
- [ ] metrics endpoint exposes required counters and histograms
- [ ] duplicate webhook delivery does not create duplicate sessions

---

## 5. Knowledge Base Ingestion And Retrieval

- [ ] Build ingestion pipeline for text, FAQ JSON, and file-based content
- [ ] Implement chunking and embedding flow
- [ ] Implement retrieval adapter with thresholded top-k results

Unit tests

- [ ] chunker respects size and overlap settings
- [ ] retrieval filters low-score chunks
- [ ] no-hit retrieval returns the no-answer path

Integration tests

- [ ] ingest endpoint writes expected documents into ChromaDB
- [ ] retrieval returns stable top-k results for fixture queries
- [ ] ingestion job status transitions work end to end

Implementation notes as of April 5, 2026

- the config surface for `CHROMADB_*`, retrieval thresholds, and `EMBEDDING_MODEL` exists in backend and agent settings
- the current `KnowledgeService` and `EmbeddingAdapter` code paths are placeholders only
- no ChromaDB ingestion, vector writes, embedding generation, or live retrieval path is implemented yet

---

## 6. Agent Worker Bootstrap

- [x] Implement worker server entrypoint
- [x] Implement per-call job bootstrap and room join
- [x] Load agent config once per call after SIP participant discovery

Unit tests

- [x] job bootstrap rejects missing or invalid config
- [x] room metadata parsing yields expected runtime context
- [ ] worker admission logic handles unsupported room states safely

Integration tests

- [ ] worker joins a dispatched room and initializes call state
- [x] call greeting can be published after config load
- [ ] call session transitions from created to active

Implementation notes as of April 5, 2026

- the worker now registers a real LiveKit `AgentServer` against the configured project
- inbound jobs are accepted only for rooms matching `CALL_ROOM_PREFIX`
- bootstrap waits for the SIP participant, parses DID and ANI, loads the active `agent_config` from Mongo, and annotates the local participant with resolved context
- after config resolution, the worker now starts a real `AgentSession` against the room using Gemini 3 Flash text plus Deepgram STT/TTS
- the initial greeting now runs through the provider-backed session instead of the earlier placeholder PCM track
- transcript turns are now persisted from live `AgentSession` conversation events as well as the mocked turn-pipeline tests

---

## 7. Core Voice Pipeline

- [x] Implement turn detection wrapper
- [x] Implement STT adapter
- [x] Implement prompt builder, LLM adapter, and TTS adapter
- [x] Implement transcript persistence hooks

Unit tests

- [x] VAD or endpointing transitions emit expected speech start/end events
- [x] prompt builder includes persona, history, and retrieved KB chunks
- [x] TTS chunker emits stable chunks instead of token-by-token audio

Integration tests

- [x] audio input -> transcript -> LLM -> TTS round trip works with mocked providers
- [x] transcript turns are stored in order
- [x] pipeline timing metrics are emitted per turn

Implementation notes as of April 5, 2026

- the worker now has a stateful turn detector with speech-start and speech-end events plus an RMS fallback for raw PCM frames
- the worker now has typed in-memory conversation state, retrieval-hit normalization, and provider wrapper classes for Gemini Flash text plus Deepgram STT/TTS
- the worker now persists transcript turns through a Mongo-backed recorder, and the initial greeting is stored as the first `agent` turn on the real live session path
- the pipeline layer now includes a mocked-provider `TurnPipeline` that runs STT -> prompt build -> Gemini text completion -> stable TTS chunking -> transcript persistence
- per-turn latency metrics are now emitted under stage labels for STT, LLM, TTS, and total pipeline RTT
- the current LLM target is `gemini-3-flash-preview`
- the current speech-provider target is Deepgram for both STT and TTS
- the live room-media loop is now implemented through LiveKit `AgentSession`, while the mocked `TurnPipeline` remains the isolated test harness for policy logic

---

## 8. Barge-In And Interruption Handling

- [x] Implement interruption coordinator inside the job
- [x] Cancel or stop active TTS on caller speech start
- [x] Mark interrupted agent turns in transcripts and metrics

Unit tests

- [x] interruption state machine cancels active response correctly
- [x] queued audio is dropped after interruption
- [x] interrupted turns are flagged in transcript records

Integration tests

- [x] caller speech during TTS stops playback quickly enough
- [x] next user turn is processed correctly after interruption

Implementation notes as of April 5, 2026

- the worker now supports interruption both in the earlier greeting-placeholder path and in the provider-backed `AgentSession` path
- queued greeting audio frames are cleared immediately when caller speech interrupts playback
- interrupted assistant turns from the live `AgentSession` are now persisted with `interrupted=True` and counted in interruption metrics
- integration coverage now exercises the bootstrap path end to end through live session startup, greeting publish, transcript persistence, and interruption accounting
- the mocked conversational turn pipeline now preserves interrupted agent turns in history and successfully processes the caller's next turn with the same pipeline instance
- full provider-specific tuning for barge-in thresholds may still need production tuning, but the real streaming voice path is now wired

---

## 9. Fallbacks, Objection Handling, And Transfer

- [x] Implement no-answer fallback
- [x] Implement at least one objection handler
- [x] Implement supported human transfer flow

Unit tests

- [x] objection classifier routes to scripted, llm, or transfer branch correctly
- [x] no-answer path is selected when retrieval misses
- [x] transfer request payload builder is valid

Integration tests

- [x] objection scenario runs end to end
- [x] transfer path marks call state and disposition correctly
- [x] transfer failure falls back gracefully

Implementation notes as of April 5, 2026

- the worker now has an objection router that can send a turn to scripted trust-handling, Gemini text generation, or human-transfer handling
- retrieval misses now take the configured no-answer path when retrieval was attempted and returned no grounded chunks
- transfer support now includes a validated transfer-request builder, success and failure response handling, and call-session state updates for successful transfers
- current transfer execution is still a mocked/provider-abstracted path in the turn pipeline; a real LiveKit or SIP handoff implementation is the next provider-facing step

---

## 10. Recovery And Reliability

- [x] Implement job crash recovery markers and replacement job flow
- [x] Add dead-letter path for failed transcript writes
- [x] Add idempotency handling for duplicate events

Unit tests

- [x] recovery coordinator marks a room recoverable only once
- [x] failed write events are enqueued for replay
- [x] idempotency keys suppress duplicate side effects

Integration tests

- [x] simulated job crash triggers recovery path
- [x] transcript write retry succeeds after transient Mongo failure
- [x] duplicate event delivery leaves one consistent final record

Implementation notes as of April 5, 2026

- the worker now marks recoverable rooms exactly once, builds a replacement-job recovery prompt from recent transcript history, and increments `recovery_count` on the call session
- transcript writes now retry transient failures and fall back to a Mongo-backed dead-letter queue when they still cannot be persisted
- transcript-side idempotency keys now suppress duplicate side effects inside the worker pipeline, while backend webhook idempotency remains in place for provider callbacks

---

## 11. Observability

- [x] Implement per-turn latency metrics
- [x] Implement call setup timing
- [x] Implement worker saturation and room quality metrics
- [x] Build initial Grafana dashboards

Unit tests

- [x] latency calculators compute perceived and pipeline RTT correctly
- [x] metric label sets stay stable and low-cardinality

Integration tests

- [x] Prometheus scrape returns all required metrics during a live test
- [x] room quality metrics are persisted into session summaries

Implementation notes as of April 5, 2026

- the worker now exposes a local Prometheus scrape endpoint on `COZMO_AGENT_METRICS_PORT` and publishes low-cardinality metrics for active jobs, call setup time, per-turn RTT, STT latency, LLM TTFT, TTS first-audio latency, and recovery count
- the worker now also publishes CPU utilization, memory utilization, queue depth, jitter, packet loss, and MOS gauges; CPU and memory are sampled in-process, and room quality is polled from LiveKit RTC stats
- backend `/metrics` now projects persisted session state into gauges for active calls and failed call setups
- call setup timing is now persisted into `call_sessions.metrics_summary.call_setup_ms` from lifecycle timestamps when the room transitions from created to connected
- room quality snapshots are now persisted into `call_sessions.voice_quality` through the worker call-state update path during active calls
- Prometheus now scrapes backend `:8000/metrics` and agent `:9108/metrics` in the Compose stack, and Grafana is provisioned with a default Prometheus datasource plus the `Cozmo Platform Overview` dashboard
- local-host development mode is supported by scraping `host.docker.internal` from the Prometheus container when backend and agent are not running inside Compose
- live scrape validation tests now cover the worker's real HTTP exporter and backend `/metrics` output

---

## 12. End-To-End And Load Validation

- [x] Build synthetic end-to-end tests with mocked or simulated media/provider edges
- [x] Build staged PSTN smoke test checklist
- [x] Build stepped load tests for 25, 50, and 100 calls

Unit tests

- [x] load test config parser validates concurrency profiles

Integration tests

- [x] local full-stack synthetic call succeeds
- [ ] staged PSTN smoke test succeeds
- [ ] 25-call, 50-call, and 100-call runs record latency and failure-rate outputs

Implementation notes as of April 5, 2026

- `tests/e2e/test_synthetic_call_flow.py` now exercises a synthetic cross-service call using signed LiveKit webhooks, shared in-memory persistence, the agent turn pipeline, and backend transcript/call APIs
- `docs/staged-pstn-smoke-test.md` now records the manual staging checklist, evidence capture points, and pass/fail criteria for real inbound PSTN checks
- `tests/load/profiles.json`, `tests/load/config.py`, and `tests/load/runner.py` now provide stepped 25/50/100 synthetic load profiles plus a JSON-reporting runner wired into `infra/scripts/load_test.sh`
- actual staged PSTN execution and real 25/50/100 benchmark runs are still pending manual execution against a stable environment

---

## 13. Release Readiness

- [ ] README quickstart
- [ ] `.env.example`
- [ ] architecture and PRD kept in sync with implementation
- [ ] demo script and measurement checklist

Unit tests

- [ ] none

Integration tests

- [ ] fresh environment bootstrap works from documented steps
- [ ] final acceptance checklist can be executed without undocumented setup
