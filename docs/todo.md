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
- after config resolution, the worker now publishes a short deterministic greeting-audio placeholder track and annotates participant state with the greeting text
- full provider-backed TTS and end-to-end dispatched-room integration coverage are still pending

---

## 7. Core Voice Pipeline

- [ ] Implement turn detection wrapper
- [ ] Implement STT adapter
- [ ] Implement prompt builder, LLM adapter, and TTS adapter
- [ ] Implement transcript persistence hooks

Unit tests

- [ ] VAD or endpointing transitions emit expected speech start/end events
- [ ] prompt builder includes persona, history, and retrieved KB chunks
- [ ] TTS chunker emits stable chunks instead of token-by-token audio

Integration tests

- [ ] audio input -> transcript -> LLM -> TTS round trip works with mocked providers
- [ ] transcript turns are stored in order
- [ ] pipeline timing metrics are emitted per turn

---

## 8. Barge-In And Interruption Handling

- [ ] Implement interruption coordinator inside the job
- [ ] Cancel or stop active TTS on caller speech start
- [ ] Mark interrupted agent turns in transcripts and metrics

Unit tests

- [ ] interruption state machine cancels active response correctly
- [ ] queued audio is dropped after interruption
- [ ] interrupted turns are flagged in transcript records

Integration tests

- [ ] caller speech during TTS stops playback quickly enough
- [ ] next user turn is processed correctly after interruption

---

## 9. Fallbacks, Objection Handling, And Transfer

- [ ] Implement no-answer fallback
- [ ] Implement at least one objection handler
- [ ] Implement supported human transfer flow

Unit tests

- [ ] objection classifier routes to scripted, llm, or transfer branch correctly
- [ ] no-answer path is selected when retrieval misses
- [ ] transfer request payload builder is valid

Integration tests

- [ ] objection scenario runs end to end
- [ ] transfer path marks call state and disposition correctly
- [ ] transfer failure falls back gracefully

---

## 10. Recovery And Reliability

- [ ] Implement job crash recovery markers and replacement job flow
- [ ] Add dead-letter path for failed transcript writes
- [ ] Add idempotency handling for duplicate events

Unit tests

- [ ] recovery coordinator marks a room recoverable only once
- [ ] failed write events are enqueued for replay
- [ ] idempotency keys suppress duplicate side effects

Integration tests

- [ ] simulated job crash triggers recovery path
- [ ] transcript write retry succeeds after transient Mongo failure
- [ ] duplicate event delivery leaves one consistent final record

---

## 11. Observability

- [ ] Implement per-turn latency metrics
- [ ] Implement call setup timing
- [ ] Implement worker saturation and room quality metrics
- [ ] Build initial Grafana dashboards

Unit tests

- [ ] latency calculators compute perceived and pipeline RTT correctly
- [ ] metric label sets stay stable and low-cardinality

Integration tests

- [ ] Prometheus scrape returns all required metrics during a live test
- [ ] room quality metrics are persisted into session summaries

---

## 12. End-To-End And Load Validation

- [ ] Build synthetic end-to-end tests with mocked or simulated media/provider edges
- [ ] Build staged PSTN smoke test checklist
- [ ] Build stepped load tests for 25, 50, and 100 calls

Unit tests

- [ ] load test config parser validates concurrency profiles

Integration tests

- [ ] local full-stack synthetic call succeeds
- [ ] staged PSTN smoke test succeeds
- [ ] 25-call, 50-call, and 100-call runs record latency and failure-rate outputs

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
