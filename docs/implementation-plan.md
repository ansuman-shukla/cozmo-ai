# Implementation Plan
## Cozmo Voice Platform

This plan defines the build order, integration order, and test gates for a full TDD workflow.

Core rule for every phase:

1. write failing unit tests first
2. write failing integration tests for the feature boundary
3. implement the minimum code to pass
4. refactor only after the test gate is green

Development guardrails for every phase:

1. use OOP where services, adapters, jobs, and domain state benefit from explicit objects
2. follow SOLID so components remain modular and replaceable
3. keep configuration in dedicated config files or modules and reference it from code instead of hardcoding values
4. add brief docstrings where function intent or behavior needs extra context
5. if a requirement is ambiguous, check official sources first; if ambiguity remains, ask the human before locking in the implementation

---

## Phase 0. Foundation

### Build

- create the `uv` workspace
- create package boundaries for `backend`, `agent`, `knowledge`, and shared `contracts`
- create centralized config modules and settings loading strategy for each package
- add `pytest`, markers, fixtures, and common developer commands
- add Dockerfiles and the initial Compose stack

### Integrate

- verify all packages install together
- verify the container topology renders correctly

### Test After Phase

- unit: config parsing, package import smoke tests
- integration: `uv sync`, `docker compose config`, baseline service startup

Exit gate

- developer can bootstrap the repo from a clean environment

---

## Phase 1. Data Contracts And Config

### Build

- define Pydantic and Mongo models
- define runtime settings and validation
- define transcript, latency, and agent config schemas

### Integrate

- connect models to Mongo collections
- create indexes on startup

### Test After Phase

- unit: schema validation, defaults, invalid field rejection
- integration: Mongo round-trip and index creation

Exit gate

- persistent contracts are stable enough for the rest of the system

---

## Phase 2. Telephony Metadata And Control Plane Events

### Build

- implement LiveKit event ingestion in FastAPI
- implement DID extraction from SIP participant attributes
- implement call session creation and status updates
- add idempotency handling for duplicate events

### Integrate

- connect LiveKit event payloads to Mongo persistence
- connect DID lookup to `agent_configs`

### Test After Phase

- unit: SIP attribute parsing, DID mapping, idempotency behavior
- integration: webhook/event payloads create and update `call_sessions`

Exit gate

- a room event can create a valid call record without manual fixes

---

## Phase 3. Agent Config APIs And Knowledge APIs

### Build

- add `/agents` CRUD endpoints
- add `/knowledge/ingest`, `/knowledge/jobs/{job_id}`, and `/knowledge/query`
- add chunking and embedding pipeline

### Integrate

- write agent configs into Mongo
- write KB artifacts into ChromaDB

### Test After Phase

- unit: chunking, retrieval thresholding, payload validation
- integration: config CRUD, ingestion jobs, retrieval on fixture data

Exit gate

- DID mappings and KB content can be managed from the control plane

---

## Phase 4. Worker Server And Job Bootstrap

### Build

- implement worker server entrypoint
- implement per-call job bootstrap
- join LiveKit room and resolve runtime context
- load the selected `agent_config`

### Integrate

- connect worker job start to session state updates
- publish an initial greeting path

### Test After Phase

- unit: runtime context parsing, job startup guards
- integration: dispatched room -> joined job -> greeting publish

Exit gate

- an inbound room can be claimed by a worker and brought to an active state

---

## Phase 5. Core Turn Pipeline

### Build

- implement turn detection wrapper
- implement streaming STT adapter
- implement prompt builder and LLM adapter
- implement streaming TTS adapter
- implement transcript persistence hooks

### Integrate

- connect VAD -> STT -> RAG -> LLM -> TTS in one job flow
- persist turns to Mongo asynchronously

### Test After Phase

- unit: prompt composition, chunk boundaries, latency timestamp calculations
- integration: mocked provider round trip from audio input to agent audio output

Exit gate

- one full conversational turn works and is measurable

---

## Phase 6. Interruption And Barge-In

### Build

- implement interruption state machine
- stop queued agent audio on caller speech start
- mark interrupted turns in transcript and metrics

### Integrate

- wire interruption logic into the active TTS path
- ensure next caller turn starts cleanly

### Test After Phase

- unit: interruption state transitions
- integration: caller speech during TTS cancels playback and starts the next turn correctly

Exit gate

- barge-in works reliably in the job loop

---

## Phase 7. Fallback, Objection, And Transfer

### Build

- implement retrieval miss fallback
- implement one objection flow
- implement supported transfer request flow

### Integrate

- connect objection handling to prompt or scripted response path
- connect transfer outcome to call disposition updates

### Test After Phase

- unit: branch selection for objection, fallback, and transfer
- integration: objection and transfer scenarios execute end to end

Exit gate

- required assignment behaviors are present beyond the happy path

---

## Phase 8. Recovery And Reliability

### Build

- detect disappeared agent participant
- mark room recoverable
- dispatch replacement job
- add dead-letter queue for failed writes

### Integrate

- recover conversation context from persisted turns
- replay failed persistence operations when dependencies return

### Test After Phase

- unit: recovery coordination and retry logic
- integration: simulated job crash and transient Mongo failure

Exit gate

- at least one real failure mode is recoverable and demonstrable

---

## Phase 9. Observability

### Build

- expose `/metrics`
- compute `perceived_rtt` and `pipeline_rtt`
- emit setup latency, worker saturation, and room quality metrics
- add Grafana dashboards

### Integrate

- connect job metrics, FastAPI metrics, and LiveKit stats into Prometheus

### Test After Phase

- unit: latency math and metric labeling
- integration: Prometheus scrape returns the required metric set during live runs

Exit gate

- latency bottlenecks are visible without reading raw logs

---

## Phase 10. Full-Stack Validation

### Build

- add synthetic end-to-end test flow
- add staged PSTN smoke-test checklist
- add stepped load profiles

### Integrate

- run 25-call and 50-call validation first
- tune worker limits, endpointing, and provider timeouts
- run 100-call validation only after intermediate steps pass

### Test After Phase

- integration: full local synthetic call flow
- integration: public staging PSTN smoke test
- load: 25-call, 50-call, 100-call measurement runs

Exit gate

- required assignment metrics are demonstrated, recorded, and explainable

---

## Test Strategy

### Unit Test Focus

Unit tests cover pure logic and adapters:

- settings and schema validation
- SIP metadata parsing
- retrieval filtering
- prompt building
- interruption state machine
- latency calculations
- fallback and transfer branch selection

### Integration Test Focus

Integration tests cover service boundaries:

- FastAPI <-> MongoDB
- FastAPI <-> ChromaDB
- worker job <-> LiveKit room lifecycle
- worker pipeline <-> mocked provider clients
- webhook/event idempotency
- recovery behavior

### End-To-End Test Focus

End-to-end coverage is split:

- local synthetic full-stack tests for repeatable CI-style coverage
- public staging PSTN smoke tests for real telephony verification

### Load Test Focus

Load tests are not a one-shot 100-call gamble.

Run order:

1. 25 calls
2. 50 calls
3. 100 calls

At each step, capture:

- setup success rate
- perceived RTT
- pipeline RTT
- worker CPU and memory
- dispatch delay

---

## Definition Of Done

A feature is done only when:

- unit tests for the feature are green
- integration tests for the feature are green
- metrics or logs needed to debug the feature exist
- docs are updated if the feature changes the architecture or workflow

The project is done only when:

- all major phases have passed their exit gates
- the 100-call validation run is recorded
- the final demo path is reproducible from the written docs
