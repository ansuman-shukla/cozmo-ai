# Platform Architecture Document
## Cozmo AI — Enterprise Voice AI Agent Platform (PSTN)

**Document version:** 2.0  
**Status:** Draft — Hardened for Implementation  
**Author:** Cozmo AI Platform Engineering  
**Last updated:** 2026-04-04  
**Companion document:** `prd-cozmo.md`

---

## 1. Architecture Summary

### 1.1 Locked Decisions

This document hardens the architecture around four decisions:

1. **Telephony correctness first.**  
   Inbound PSTN calls enter through **Twilio Elastic SIP Trunking** and terminate into **LiveKit SIP** through a pre-provisioned inbound trunk and dispatch rule.

2. **FastAPI is not on the first-hop call path.**  
   FastAPI handles control-plane and operations concerns, but call admission does not wait on a webhook response from the app.

3. **Per-call state stays inside the call job.**  
   The agent job owns conversation history and active dialog state in memory. Redis is optional and not used for per-turn reads.

4. **Scalability is benchmark-driven.**  
   The worker fleet scales by verified active jobs per worker server, not by guessed “one process equals one call” RAM estimates.

### 1.2 High-Level Component Map

```text
                          PUBLIC NETWORK

 [PSTN Caller]
       |
       v
 [Twilio Elastic SIP Trunking]
       |
       | SIP INVITE / RTP-SRTP
       v
 [LiveKit SIP + SFU]
       |
       | dispatches room/job
       v
 [livekit-agents Worker Servers]
       |
       | per-call job subprocess
       v
 [VAD -> STT -> RAG -> LLM -> TTS]


                         CONTROL / DATA PLANE

 [FastAPI Backend] <----> [MongoDB]
        |                     ^
        |                     |
        v                     |
    [ChromaDB]                |
        ^                     |
        |                     |
     [Ingestion]         [Transcript / Session Writes]

 [Redis - optional]
   - event idempotency
   - recovery leases
   - dead-letter replay

 [Prometheus / Grafana]
   - call setup
   - perceived RTT
   - pipeline RTT
   - worker saturation
   - room quality
```

### 1.3 Why This Architecture Is Correct

The previous version mixed two different telephony patterns:

- Twilio Programmable Voice webhook + TwiML `<Dial><Sip>`
- Twilio SIP trunking + LiveKit SIP dispatch

Those are not the same architecture. For a system whose requirements explicitly say **Twilio SIP trunk (inbound PSTN)** plus **LiveKit**, the hardened design is:

- Twilio SIP trunk forwards the call to LiveKit SIP
- LiveKit authenticates the trunk and creates the SIP participant automatically
- LiveKit dispatches the room to a registered agent worker
- FastAPI only handles the surrounding control plane

This keeps the SIP path valid, reduces setup latency variance, and preserves a viable path for SIP-based transfer.

---

## 2. System Boundaries

### 2.1 Runtime Components

| Component | Role | On call-critical path |
|-----------|------|-----------------------|
| Twilio Elastic SIP Trunking | PSTN ingress | Yes |
| LiveKit SIP + SFU | SIP admission, room creation, media routing | Yes |
| `livekit-agents` worker servers | Agent job dispatch and execution | Yes |
| Deepgram STT / TTS | Speech processing | Yes |
| LLM provider | Response generation | Yes |
| FastAPI | config, sessions, ingestion, webhooks, metrics | No for admission; yes for some side effects |
| MongoDB | sessions, transcripts, configs | No on first-hop path |
| ChromaDB | KB retrieval | Yes on response path |
| Redis (optional) | recovery / idempotency | No |
| Prometheus / Grafana | observability | No |

### 2.2 Network Topology

| Boundary | Protocol | Notes |
|----------|----------|-------|
| PSTN -> Twilio | PSTN/SS7 | Managed by Twilio |
| Twilio -> LiveKit SIP | SIP over TLS/UDP + RTP/SRTP | Inbound carrier handoff |
| Worker -> LiveKit | WSS / RTP handled by SDK | Job joins room and publishes audio |
| Worker -> Deepgram | WSS / HTTPS | Streaming STT and TTS |
| Worker -> LLM provider | HTTPS streaming | TTFT-sensitive path |
| Worker -> ChromaDB | HTTP internal | Small top-k retrieval |
| FastAPI -> MongoDB | TCP internal | control-plane state |
| Worker -> MongoDB | TCP internal | async transcript/session writes |
| FastAPI / Worker -> Redis | TCP internal | optional |
| Prometheus -> all services | HTTP scrape | metrics collection |

### 2.3 Port Reference

| Service | Port(s) | Exposure |
|---------|---------|----------|
| FastAPI | 8000 | internal or reverse-proxied |
| LiveKit API / WS | 7880 | public or VPC-routed |
| LiveKit SIP | 5060 / 5061 | public |
| LiveKit RTP/WebRTC UDP range | configured range | public |
| MongoDB | 27017 | internal only |
| ChromaDB | 8000 | internal only |
| Redis | 6379 | internal only |
| Prometheus | 9090 | internal only |
| Grafana | 3000 | internal only |

---

## 3. Repository And Code Structure

### 3.1 `uv` Workspace Layout

```text
cozmo-voice-platform/
|
|- pyproject.toml                  # uv workspace root
|- uv.lock                         # locked dependency graph
|- README.md
|- .env.example
|- Makefile
|- pytest.ini                      # global pytest markers and defaults
|- todo.md                         # feature checklist with unit/integration coverage
|- implementation-plan.md          # phase-by-phase build and integration flow
|
|- backend/
|  |- pyproject.toml               # FastAPI package
|  |- app/
|  |  |- main.py
|  |  |- config.py
|  |  |- routers/
|  |  |  |- webhooks.py            # LiveKit/Twilio event handlers
|  |  |  |- calls.py               # session/transcript read APIs
|  |  |  |- knowledge.py
|  |  |  |- agents.py
|  |  |  |- health.py
|  |  |  |- metrics.py
|  |  |- services/
|  |  |  |- livekit_service.py     # provisioning + room metadata helpers
|  |  |  |- session_service.py
|  |  |  |- knowledge_service.py
|  |  |  |- ingest_jobs.py
|  |  |- models/
|  |  |  |- call_session.py
|  |  |  |- transcript.py
|  |  |  |- agent_config.py
|  |  |- middleware/
|  |  |  |- auth.py
|  |  |  |- logging.py
|  |  |- observability/
|  |     |- metrics.py
|  |- tests/
|  |  |- unit/
|  |  |- integration/
|  |  |- conftest.py
|  |- Dockerfile
|
|- agent/
|  |- pyproject.toml               # livekit-agents package
|  |- agent.py                     # worker server entrypoint
|  |- app/
|  |  |- job.py                    # per-call job orchestration
|  |  |- config.py
|  |  |- telephony.py              # SIP participant attribute parsing
|  |  |- pipeline/
|  |  |  |- vad.py
|  |  |  |- stt.py
|  |  |  |- rag.py
|  |  |  |- llm.py
|  |  |  |- tts.py
|  |  |  |- interruption.py
|  |  |- dialog/
|  |  |  |- conversation.py
|  |  |  |- objection_handler.py
|  |  |- recovery/
|  |  |  |- rejoin.py
|  |  |- observability/
|  |     |- metrics.py
|  |- tests/
|  |  |- unit/
|  |  |- integration/
|  |  |- conftest.py
|  |- Dockerfile
|
|- knowledge/
|  |- pyproject.toml
|  |- ingest.py
|  |- chunker.py
|  |- embeddings.py
|  |- tests/
|  |  |- unit/
|  |  |- integration/
|  |- fixtures/
|
|- contracts/
|  |- pyproject.toml
|  |- cozmo_contracts/
|  |  |- models.py
|  |  |- runtime.py
|  |  |- events.py
|  |  |- validators.py
|  |- tests/
|     |- unit/
|
|- infra/
|  |- docker-compose.yml
|  |- livekit/
|  |  |- livekit.yaml
|  |- prometheus/
|  |  |- prometheus.yml
|  |  |- alerts.yml
|  |- grafana/
|  |- scripts/
|     |- provision_trunks.sh
|     |- seed_knowledge.sh
|     |- load_test.sh
|
|- tests/
|  |- e2e/
|  |- load/
|  |- fixtures/
|  |- stubs/
|
|- docs/
   |- PRD.md
   |- PLATFORM_ARCHITECTURE.md
```

### 3.2 `uv` Conventions

- install everything locally with `uv sync --all-packages --dev`
- run the backend with `uv run --package backend uvicorn app.main:app --host 0.0.0.0 --port 8000`
- run the worker server with `uv run --package agent python agent.py start`
- lock dependency updates with `uv lock`
- run unit tests with `uv run pytest -m unit`
- run integration tests with `uv run pytest -m integration`
- run end-to-end tests with `uv run pytest tests/e2e`

### 3.3 Boundary Rules

- `backend/` and `agent/` are independently deployable
- `agent/` does not import `backend/`
- ChromaDB is the shared KB interface
- MongoDB is the shared persistence interface
- Redis is optional and never used for turn-by-turn dialog state reads

### 3.4 Test Layout And TDD Workflow

The repository follows a test pyramid that matches the implementation plan:

- `backend/tests/unit` and `agent/tests/unit` hold pure logic and adapter tests
- `backend/tests/integration`, `agent/tests/integration`, and `knowledge/tests/integration` cover real service boundaries
- `tests/e2e` covers full-stack synthetic call flows
- `tests/load` holds stepped concurrency and capacity tests
- `tests/fixtures` and `tests/stubs` hold reusable test data and provider fakes

Feature workflow:

1. write failing unit tests for the feature
2. write failing integration tests for the boundary the feature crosses
3. implement the minimum code needed to pass
4. refactor only with the full feature test set green

This is a deliberate architecture choice, not just a development preference. The telephony path, streaming pipeline, and recovery logic are too stateful to trust without layered automated tests.

### 3.5 Engineering Principles And Development Guardrails

The implementation should follow these coding standards throughout the repository:

- use an **object-oriented design** for application services, adapters, orchestration objects, and domain models where state and behavior naturally belong together
- follow **SOLID principles** so responsibilities stay narrow, dependencies stay replaceable, and new providers or behaviors can be added without broad rewrites
- keep every service **modular** and boundary-driven so telephony, persistence, retrieval, model providers, and observability can evolve independently
- store configuration in **dedicated config modules/files** and inject or reference configuration from there instead of hardcoding values throughout the codebase
- prefer changing configuration in one place over scattering constants across handlers, services, and jobs
- add **brief docstrings** to functions and methods when they provide useful context that is not obvious from the signature alone

Practical implications for this codebase:

- provider integrations should sit behind small interfaces or adapters
- orchestration code should depend on abstractions and config objects, not provider-specific constants
- feature changes should usually require editing a focused module, not touching unrelated services
- runtime settings for telephony, model selection, retrieval, and timeouts should be loaded once and passed into the relevant objects

### 3.6 Ambiguity Handling Rule

When implementation details are ambiguous, the development workflow is:

1. inspect the local code and docs first
2. if ambiguity remains, look up the relevant official documentation or primary source on the internet
3. if the ambiguity is still unresolved or a product decision is required, ask the human directly before proceeding

This rule is mandatory for error-resistant development. The system should prefer clarification over silently baking uncertain assumptions into telephony, provider, scaling, or data-model code.

---

## 4. Service Breakdown

### 4.1 FastAPI Backend

**Role**

- expose control-plane APIs
- persist call sessions and transcripts
- ingest and manage KB documents
- receive LiveKit and optional Twilio webhooks
- expose health and metrics
- provision or validate SIP resources during setup

**What it does not do**

- it does not return TwiML for inbound call routing
- it does not create a room synchronously for every inbound call
- it does not sit in the first-hop latency budget

**Scaling**

- stateless
- safe to run behind a load balancer
- 2 replicas recommended for operational resilience

### 4.2 LiveKit SIP + SFU

**Role**

- authenticate inbound SIP trunks
- create SIP participants for inbound callers automatically
- place callers into rooms according to dispatch rules
- dispatch rooms to registered `livekit-agents` workers
- route audio between SIP participant and agent participant
- expose room and participant stats

**Why it is central**

LiveKit is both:

- the telephony admission layer for SIP
- the media layer for the room

That is why it should be the first component after Twilio.

### 4.3 Agent Worker Servers

**Role**

Worker servers are long-lived processes that register with LiveKit. When a room is dispatched, the worker server starts a **job subprocess** for that call.

**Important correction**

The scaling unit is not “one always-running worker process per call.” The actual model is:

1. worker server starts
2. worker server registers with LiveKit
3. LiveKit dispatches a job
4. worker server spawns a job subprocess
5. the job joins the room and runs the call

**Implication**

Capacity planning is based on:

- concurrent jobs per worker server
- CPU and memory saturation under load
- p95 latency under load

### 4.4 MongoDB

**Role**

- call session records
- transcripts
- agent configuration documents
- KB ingestion job records

**v1 posture**

- single node with journaling is acceptable for the take-home
- this is durable enough for a demo
- it is not HA and the docs do not claim otherwise

### 4.5 ChromaDB

**Role**

- store a compact per-deployment KB
- serve small top-k retrieval during calls

**Why acceptable in v1**

- the take-home KB is small
- retrieval latency target is modest
- swap-out to Qdrant or another store is a future concern, not a call-flow concern

### 4.6 Redis

**Role**

Redis is optional. If used, it supports:

- webhook idempotency
- orphaned-room recovery leases
- dead-letter queue for failed transcript/session writes

**What it explicitly does not do**

- no per-turn conversation state
- no “check Redis before every reply” hot-path reads

---

## 5. Provisioning Model

### 5.1 Pre-Provisioned Telephony

Before any call can succeed, the environment must already have:

1. a Twilio Elastic SIP trunk for inbound PSTN calls
2. a LiveKit inbound SIP trunk configured to accept that traffic
3. at least one dispatch rule in LiveKit
4. at least one registered worker server

The application is allowed to help provision these, but the runtime call path must not depend on creating them on the fly.

### 5.1.1 Current Staging Notes

Current operator snapshot as of April 5, 2026:

- a Twilio Elastic SIP trunk has already been created
- at least one active Twilio phone number is attached to that trunk
- the LiveKit project exists and exposes a SIP URI
- Twilio origination is configured to the LiveKit SIP endpoint using `sip:<livekit-sip-endpoint>;transport=tcp`
- a LiveKit inbound SIP trunk named `cozmo-inbound` now exists for the active DID
- a LiveKit dispatch rule named `cozmo-inbound-dispatch` now exists, routes to `call-<caller-number>`, and dispatches the `inbound-agent`
- the stale LiveKit outbound trunk has been removed

Operational guidance:

- the provider-side telephony path is now provisioned for inbound PSTN admission
- the worker process must register with the same agent name used in the dispatch rule: `inbound-agent`
- a LiveKit webhook endpoint can be pointed at a temporary HTTPS tunnel such as `https://<ngrok-host>/webhooks/livekit` for local testing
- the selected LiveKit webhook signing API key must match `COZMO_BACKEND_LIVEKIT_API_KEY` and its paired secret in backend env
- backend webhook verification now uses the official `livekit.api.TokenVerifier` flow with clock-skew leeway instead of a hand-rolled JWT check
- rejected LiveKit webhooks are logged with the backend-side reason so operator triage does not depend on the plain `401` access log line
- `.env.example` is a documentation template only; runtime services and Compose must load the real `.env`
- free tunnel URLs are ephemeral and must be updated in the LiveKit dashboard when they change
- Twilio termination settings are not required for the current inbound PSTN flow; they matter later for outbound PSTN or transfer paths
- Twilio status callbacks to FastAPI are optional correlation hooks and are not required for the primary inbound PSTN path

Minimum configuration to unblock an inbound PSTN smoke test:

```json
{
  "name": "cozmo-inbound",
  "numbers": ["<twilio-did>"]
}
```

```json
{
  "name": "cozmo-inbound-dispatch",
  "rule": {
    "dispatchRuleIndividual": {
      "roomPrefix": "call-"
    }
  }
}
```

### 5.2 DID To Agent Config Mapping

The mapping from dialed number to agent configuration is resolved outside the first-hop SIP path.

Recommended v1 approach:

1. store DID -> `agent_config_id` in MongoDB
2. when the job joins the room, inspect SIP participant attributes
3. read the dialed number and provider metadata
4. fetch the matching `agent_config`
5. cache that config in the job for the rest of the call

This is acceptable because:

- it does not block SIP admission
- it happens once per call, not every turn
- it preserves flexibility for multiple DIDs

### 5.3 Transfer Support

Human transfer requires a compatible SIP path.

The hardened v1 design assumes:

- LiveKit remains the call owner during escalation
- transfer occurs through a supported SIP transfer or outbound trunk path

The architecture explicitly does **not** assume that a TwiML-only Voice webhook path can do this for us.

---

## 6. Call Flow — Control Plane

### 6.1 Inbound Admission Sequence

```text
Step 1: Caller dials enterprise DID
Step 2: PSTN routes to Twilio
Step 3: Twilio forwards INVITE over Elastic SIP Trunking to LiveKit SIP
Step 4: LiveKit authenticates the inbound trunk
Step 5: LiveKit matches a dispatch rule
Step 6: LiveKit creates or assigns a room for this call
Step 7: LiveKit creates the inbound SIP participant automatically
Step 8: LiveKit dispatches the room to an available agent worker server
Step 9: Worker server accepts the dispatch and starts a job subprocess
Step 10: Job joins the room as the agent participant
Step 11: Job inspects SIP participant attributes and loads agent config by DID
Step 12: FastAPI/Mongo persist the call session asynchronously
Step 13: Agent publishes greeting audio
```

Current implementation note:

- Steps 9 through 13 are now implemented in the worker bootstrap path
- the current Step 13 behavior publishes a deterministic short greeting-audio placeholder track after config resolution
- the worker now persists that initial greeting as the first ordered `agent` transcript turn in Mongo
- the worker now has a stateful turn detector with explicit speech-start and speech-end events
- the worker now stops queued greeting playback when a remote participant becomes an active speaker and marks that greeting turn as interrupted
- interruption metrics now track response interruptions and interrupted agent turns
- the interruption path now has integration coverage at the bootstrap level, including caller-speech interruption during greeting playback
- the mocked conversational pipeline now also carries interrupted agent turns forward correctly so the next caller turn can be processed without corrupting prompt history
- the conversational policy layer now supports a grounded no-answer fallback, a scripted trust objection branch, and a transfer branch with validated transfer targets and call-state updates
- transfer execution is still modeled behind a provider abstraction; the current implementation validates payloads and state transitions before a real SIP/LK handoff is wired
- the worker now claims room recovery exactly once after a recoverable crash, builds a short resume prompt from transcript history, and increments `recovery_count` on the persisted call session
- transcript writes now retry transient failures and dead-letter unrecoverable payloads into Mongo for later replay, and transcript-side idempotency keys suppress duplicate side effects
- Gemini Flash text and Deepgram speech adapter scaffolding now exist in the worker pipeline layer
- the worker pipeline now has a mocked-provider turn orchestrator for STT -> LLM -> TTS integration coverage, stable TTS text chunking, and per-turn latency metrics
- provider-backed TTS is still pending and will replace that placeholder path later in the voice pipeline work

### 6.2 Critical Observations

- FastAPI is absent from Steps 1 to 10
- room creation is owned by LiveKit dispatch, not the app
- `CreateSIPParticipant` is not used for inbound calls
- the DID lookup happens once after the job starts

### 6.3 Control Plane Latency Budget

| Segment | Target |
|---------|--------|
| Twilio trunk to LiveKit SIP acceptance | carrier/network dependent |
| LiveKit dispatch to worker acceptance | < 500 ms |
| Job startup and room join | < 400 ms |
| Config fetch by DID | < 150 ms |
| Greeting start after room join | < 300 ms |

The user-facing “how long until the agent speaks” metric includes more than just application time. That is why call setup latency is tracked separately from turn latency.

### 6.4 Control Plane Failure Cases

| Failure | Handling |
|---------|----------|
| trunk auth failure | reject call at SIP layer, alert |
| no dispatch rule | call does not land in agent room, alert |
| no available worker capacity | record failed setup or long queue delay, alert on saturation |
| DID has no config | agent plays fallback and ends or transfers |
| FastAPI unavailable | new calls can still land; secondary persistence side effects may degrade |

---

## 7. Call Flow — Media And Agent Pipeline

### 7.1 Turn Processing Sequence

```text
1. Caller audio reaches LiveKit room as SIP participant media
2. Agent job subscribes to caller audio track
3. VAD / endpointing detects speech start
4. Audio is buffered into the active user turn
5. If TTS is active, interruption logic cancels current response
6. VAD / endpointing detects end of utterance
7. Audio is streamed to STT provider
8. Finalized or stable transcript is produced
9. ChromaDB retrieves top-k KB chunks
10. Prompt is assembled with system instructions, short history, KB context
11. LLM streaming request begins
12. First useful token or clause arrives
13. TTS streaming begins on stable chunk boundary
14. Audio is published to the LiveKit room
15. Transcript and metrics are persisted asynchronously
```

### 7.2 Pipeline Components

| Stage | Baseline choice | Notes |
|-------|-----------------|-------|
| Turn detection | Silero VAD via `livekit-agents` | explicit, measurable |
| STT | Deepgram Nova-3 streaming | configurable provider |
| KB retrieval | ChromaDB | top-k small context |
| LLM | configurable low-latency streaming model | provider is not hardcoded in architecture |
| TTS | Deepgram Aura-2 streaming | configurable voice/model |

### 7.3 Interruption / Barge-In

When the caller speaks during active TTS:

1. mark the current agent turn as interrupted
2. cancel any remaining TTS request if possible
3. stop publishing queued agent audio
4. switch back to caller input buffering

This logic lives entirely inside the job. It does not require Redis coordination.

### 7.4 Conversation State

Per-call state held in memory:

- short rolling history
- current objection/escalation flags
- active response stream state
- per-turn timestamps
- active agent config snapshot

Persisted asynchronously:

- final user turns
- final agent turns
- interruption markers
- per-turn latency summary

### 7.5 Latency Definitions

Two latency numbers are required.

**Perceived RTT**

```text
first_agent_audio_time - last_user_speech_frame_time
```

This is the assignment-facing latency number.

**Pipeline RTT**

```text
first_agent_audio_time - endpoint_detected_time
```

This is the tuning and debugging number.

### 7.6 Latency Budget

| Stage | Target |
|-------|--------|
| Endpointing / end-of-turn detection | 180-250 ms |
| STT | 80-150 ms |
| KB retrieval | 20-50 ms |
| LLM TTFT | 120-250 ms |
| TTS first audio | 80-150 ms |
| Publish overhead | 10-20 ms |
| Total perceived RTT | 490-870 ms worst case, target average < 600 ms |

Practical implication:

- a sub-600 average is possible only if endpointing is tuned aggressively and LLM TTFT is tightly controlled
- the doc therefore separates tuning metrics from externally reported perceived latency

---

## 8. Data Model

### 8.1 `call_sessions`

```json
{
  "_id": "ObjectId",
  "provider": "twilio",
  "provider_call_id": "string|null",
  "room_name": "string",
  "did": "string|null",
  "ani": "string|null",
  "agent_config_id": "string",
  "status": "created|active|completed|failed|recovered|transferred",
  "created_at": "ISODate",
  "connected_at": "ISODate|null",
  "ended_at": "ISODate|null",
  "duration_seconds": "number|null",
  "disposition": "completed|caller_hangup|agent_error|transferred|setup_failed|null",
  "transfer_target": "string|null",
  "recovery_count": "int",
  "metrics_summary": {
    "avg_perceived_rtt_ms": "number|null",
    "p95_perceived_rtt_ms": "number|null",
    "avg_pipeline_rtt_ms": "number|null",
    "avg_stt_ms": "number|null",
    "avg_llm_ttft_ms": "number|null",
    "avg_tts_first_audio_ms": "number|null",
    "call_setup_ms": "number|null"
  },
  "voice_quality": {
    "avg_jitter_ms": "number|null",
    "packet_loss_pct": "number|null",
    "mos_estimate": "number|null"
  }
}
```

Indexes:

- unique `provider_call_id` when present
- unique `room_name`
- `did`
- `status`
- `created_at`

### 8.2 `transcripts`

```json
{
  "_id": "ObjectId",
  "room_name": "string",
  "turn_index": "int",
  "speaker": "user|agent",
  "text": "string",
  "timestamp": "ISODate",
  "interrupted": "bool",
  "objection_type": "string|null",
  "latency": {
    "endpoint_ms": "number|null",
    "stt_ms": "number|null",
    "llm_ttft_ms": "number|null",
    "tts_first_audio_ms": "number|null",
    "pipeline_rtt_ms": "number|null",
    "perceived_rtt_ms": "number|null"
  },
  "kb_chunks_used": [
    {
      "chunk_id": "string",
      "score": "number"
    }
  ]
}
```

Indexes:

- compound `room_name + turn_index`
- `timestamp`

### 8.3 `agent_configs`

```json
{
  "_id": "ObjectId",
  "config_id": "string",
  "did": "string",
  "agent_name": "string",
  "persona_prompt": "string",
  "kb_collection": "string",
  "llm_provider": "string",
  "llm_model": "string",
  "tts_provider": "string",
  "tts_model": "string",
  "tts_voice": "string",
  "escalation_triggers": ["string"],
  "transfer_target": "string|null",
  "active": "bool",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

### 8.4 Redis Keys (Optional)

| Key | Purpose |
|-----|---------|
| `idempotency:webhook:{event_id}` | suppress duplicate webhook side effects |
| `recovery:room:{room_name}` | lease or marker for orphaned-room recovery |
| `dlq:transcripts` | replay failed transcript writes |

---

## 9. Observability

### 9.1 Metrics

Required metrics:

- `cozmo_active_calls`
- `cozmo_agent_jobs_active`
- `cozmo_call_setup_seconds`
- `cozmo_pipeline_rtt_seconds`
- `cozmo_perceived_rtt_seconds`
- `cozmo_stt_latency_seconds`
- `cozmo_llm_ttft_seconds`
- `cozmo_tts_first_audio_seconds`
- `cozmo_kb_retrieval_seconds`
- `cozmo_failed_call_setups_total`
- `cozmo_agent_recoveries_total`
- `cozmo_worker_job_queue_depth`
- `cozmo_worker_cpu_utilization`
- `cozmo_worker_memory_utilization`

### 9.2 Metrics Flow

```text
Agent job
  -> turn timestamps
  -> perceived/pipeline RTT
  -> interruption counters
  -> per-call quality snapshots

Worker server
  -> active jobs
  -> queue depth
  -> cpu/memory process stats

FastAPI
  -> ingestion metrics
  -> webhook processing stats
  -> persistence error counts

LiveKit
  -> room count
  -> participant count
  -> jitter / packet loss / room quality
```

Current implementation status as of April 5, 2026:

- the agent worker exposes Prometheus metrics locally on `COZMO_AGENT_METRICS_PORT` with call setup timing, active-job gauge, recovery count, and per-turn latency histograms
- the agent worker now also exposes CPU utilization, memory utilization, queue depth, and per-call room-quality gauges for jitter, packet loss, and MOS
- backend `/metrics` now includes persisted active-call and failed-setup gauges sourced from Mongo-backed session state
- `call_sessions.metrics_summary.call_setup_ms` is populated from call lifecycle timestamps once a session reaches the connected state
- room-quality snapshots are now sampled from `Room.get_rtc_stats()` and persisted into `call_sessions.voice_quality` during active calls
- the Compose stack now provisions Prometheus and Grafana for local observability, with Grafana loading the `Cozmo Platform Overview` dashboard automatically from `infra/grafana/dashboards`
- for local development with backend and agent running on the host instead of inside Compose, Prometheus scrapes `host.docker.internal:8000` and `host.docker.internal:9108` through Docker's host gateway
- integration coverage now validates both the worker HTTP exporter and backend `/metrics` scrape output against the required metric set

### 9.3 Alerts

| Alert | Condition |
|-------|-----------|
| HighPerceivedRTT | avg perceived RTT > 800 ms for 5 min |
| CriticalPerceivedRTT | p95 perceived RTT > 900 ms for 5 min |
| WorkerSaturation | active jobs / verified capacity > 0.85 |
| DispatchDelay | dispatch delay p95 > 1 s |
| FailedCallSetup | failed setup rate > 1% |
| RecoverySpike | recovery count above baseline |
| MongoWriteFailures | transcript/session write failures above threshold |

### 9.4 Logging

Every service emits structured JSON logs with:

- `room_name`
- `provider_call_id`
- `did`
- `agent_config_id`
- `event`
- `latency_ms`
- `worker_id`

---

## 10. Scaling Architecture

### 10.1 Independent Scaling Axes

| Layer | Scale mechanism |
|-------|-----------------|
| LiveKit SIP/SFU | larger node or clustered nodes |
| Agent workers | more worker servers / replicas |
| FastAPI | more stateless replicas |
| ChromaDB | larger node now, alternate vector DB later |
| MongoDB | replica set later if needed |

### 10.2 Capacity Planning Model

The correct capacity formula is:

```text
verified_jobs_per_worker_server = measured under representative load
required_worker_servers = ceil(target_calls / verified_jobs_per_worker_server * 1.3)
```

Why the 1.3 factor exists:

- keeps approximately 30% spare headroom
- leaves room for noisy neighbors and traffic bursts
- protects p95 latency before hard saturation

### 10.3 How To Derive `verified_jobs_per_worker_server`

For each worker server shape:

1. run incremental load steps
2. observe p95 perceived RTT, CPU, memory, and job start delay
3. stop when any SLO guardrail is violated
4. take the last stable concurrency as `verified_jobs_per_worker_server`

Guardrails:

- p95 perceived RTT < 900 ms
- CPU < 70% steady-state
- memory < 75% steady-state
- failed setup rate < 1%
- dispatch delay p95 < 1 s

### 10.4 100-Call Target

For the assignment, the architecture is sufficient because:

- LiveKit can handle 100 audio-only rooms on a single appropriately sized node
- worker servers scale horizontally and are not constrained to “one OS process per call”
- FastAPI is off the first-hop path
- Redis is not adding hot-path overhead

### 10.5 Path To 1000 Calls

| Component | Change |
|-----------|--------|
| LiveKit | move to clustered SIP/SFU deployment |
| Agent workers | orchestrate with Kubernetes or Nomad, autoscale on verified capacity signals |
| MongoDB | replica set |
| Vector store | migrate if ChromaDB stops meeting latency or operational needs |
| Observability | centralize logs and long-term metrics |

---

## 11. Failure Recovery Patterns

### 11.1 Agent Job Crash

Scenario:

- agent job subprocess crashes
- SIP caller remains in the room

Recovery:

1. detect that the agent participant disappeared
2. mark the room as recoverable
3. dispatch a replacement job if capacity exists
4. reload short conversation history from MongoDB
5. resume with a brief recovery prompt

Guarantee:

- best effort only
- target < 5 seconds
- must be demonstrated in testing

### 11.2 External Provider Timeout

| Provider | Failure mode | Fallback |
|----------|--------------|----------|
| STT | timeout / no final transcript | ask caller to repeat |
| LLM | timeout / slow TTFT | retry once or switch configured fallback model |
| TTS | timeout / stream failure | retry once, else short apology and end turn |
| ChromaDB | timeout | continue without KB context or use no-answer fallback |

### 11.3 Duplicate Events

If LiveKit or Twilio emits duplicate callbacks:

- FastAPI uses idempotency keys
- side effects become safe to retry
- no duplicate call session or transcript mutation occurs

### 11.4 MongoDB Write Failure

If MongoDB is temporarily unavailable:

- the live call continues
- writes are retried or pushed to a dead-letter queue
- readiness may fail for the backend, but active media sessions are not blocked

---

## 12. API Surface

### 12.1 Webhooks

#### `POST /webhooks/livekit`

Purpose:

- consume LiveKit room and participant events
- update call session lifecycle
- record setup, connect, teardown, and quality markers
- verify the signed LiveKit Authorization token and request body hash before processing

#### `POST /webhooks/twilio/status`

Purpose:

- optional correlation hook for Twilio-side status events
- not part of primary inbound routing

Note:

- rooms created from LiveKit individual dispatch may include caller-number-derived segments such as `call-+16625550123-abc123`
- backend room-name validation must accept that format without rewriting the canonical LiveKit room id

### 12.2 Calls API

#### `GET /calls`

- list sessions
- filter by status, DID, date window

#### `GET /calls/{room_name}`

- return full session summary

#### `GET /calls/{room_name}/transcript`

- ordered transcript

### 12.3 Knowledge API

#### `POST /knowledge/ingest`

- ingest structured documents into a target KB collection

#### `POST /knowledge/ingest/file`

- file upload path

#### `GET /knowledge/jobs/{job_id}`

- ingestion status

#### `POST /knowledge/query`

- debugging endpoint for retrieval quality

### 12.4 Agent Config API

#### `GET /agents`
#### `GET /agents/{config_id}`
#### `POST /agents`
#### `PUT /agents/{config_id}`

These endpoints manage persona, model selection, escalation target, and KB bindings.

### 12.5 Ops API

#### `GET /metrics`
#### `GET /health`
#### `GET /ready`

Optional provisioning helpers:

- create or validate LiveKit SIP trunk config
- validate dispatch rules
- validate DID -> config mappings

---

## 13. Infrastructure And Deployment

### 13.1 Environment Variables

```bash
# Twilio SIP
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_TRUNK_NAME=cozmo-inbound

# LiveKit
LIVEKIT_URL=wss://livekit.internal:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret
LIVEKIT_SIP_TRUNK_ID=inbound-trunk-id
LIVEKIT_SIP_DISPATCH_RULE_NAME=cozmo-inbound-dispatch
LIVEKIT_DISPATCH_AGENT_NAME=inbound-agent
CALL_ROOM_PREFIX=call-

# Models
DEEPGRAM_API_KEY=xxxxxxxxxxxxxxxx
STT_PROVIDER=deepgram
STT_MODEL=nova-3
TTS_PROVIDER=deepgram
TTS_MODEL=aura-2-thalia-en
LLM_PROVIDER=gemini
LLM_MODEL=your-low-latency-streaming-model

# Data
MONGODB_URI=mongodb://cozmo:secret@mongodb:27017/cozmo_voice?authSource=admin
MONGODB_DB=cozmo_voice
CHROMADB_HOST=chromadb
CHROMADB_PORT=8000
REDIS_URL=redis://redis:6379/0

# Retrieval
EMBEDDING_MODEL=text-embedding-3-small
KB_TOP_K=3
KB_MIN_SCORE=0.35

# Agent
MAX_HISTORY_TURNS=10
MAX_JOBS_PER_WORKER_SERVER=8  # initial safe default; raise only after benchmark validation

# Timeouts
TIMEOUT_STT_MS=5000
TIMEOUT_LLM_MS=8000
TIMEOUT_TTS_MS=5000
TIMEOUT_KB_MS=200

# Security / Ops
API_KEY=internal-api-key
LOG_LEVEL=INFO
```

### 13.2 Docker Compose Topology

```yaml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [mongodb, chromadb]

  agent:
    build: ./agent
    depends_on: [livekit, mongodb, chromadb]

  livekit:
    image: livekit/livekit-server:latest
    ports:
      - "7880:7880"
      - "5060:5060/udp"
      - "5061:5061"
      - "50000-50050:50000-50050/udp"

  mongodb:
    image: mongo:7

  chromadb:
    image: chromadb/chroma:latest

  redis:
    image: redis:7-alpine

  prometheus:
    image: prom/prometheus:latest

  grafana:
    image: grafana/grafana:latest
```

Important note:

- `docker compose` is for local and staging convenience
- production scaling is not expressed by `deploy.replicas` here
- for local scale tests, use `docker compose up --scale agent=N`

### 13.3 Startup Sequence

```text
1. uv sync --all-packages --dev
2. docker compose up -d mongodb chromadb redis
3. docker compose up -d livekit
4. run SIP trunk / dispatch validation script
5. docker compose up -d backend
6. docker compose up -d --scale agent=<N> agent
7. docker compose up -d prometheus grafana
8. seed the KB
9. run synthetic load tests
10. run PSTN smoke test against public SIP ingress
```

### 13.4 Local Development Caveat

A real inbound PSTN test requires a public SIP endpoint reachable by Twilio.

Therefore:

- Docker Compose is enough for internal service bring-up and synthetic load tests
- end-to-end PSTN verification must use a public staging deployment or LiveKit Cloud / public LiveKit host

This is an important realism point and should be stated explicitly.

Current validation artifacts as of April 5, 2026:

- `tests/e2e/test_synthetic_call_flow.py` covers the local synthetic call path across backend webhooks, shared persistence, the agent turn pipeline, and backend read APIs
- `tests/load/profiles.json` defines stepped `25-calls`, `50-calls`, and `100-calls` synthetic profiles aligned to the PRD acceptance thresholds
- `tests/load/runner.py` writes per-profile JSON reports, and `infra/scripts/load_test.sh` is the wrapper entrypoint for local synthetic load runs
- `docs/staged-pstn-smoke-test.md` is the manual checklist for the public PSTN staging pass

---

## 14. LiveKit Vs Pipecat

### 14.1 Why LiveKit Remains The Right Choice

LiveKit is the right choice for this assignment because:

- the problem is explicitly PSTN + SIP
- a room model is useful
- telephony and media are first-class
- worker dispatch is built into the same platform
- interruption handling aligns naturally with room audio tracks

### 14.2 Why Not Pipecat For This Version

Pipecat remains attractive for transport-agnostic voice apps and richer pipeline composition, but it does not simplify the core requirement here:

- inbound PSTN through SIP trunking
- 100 concurrent calls
- first-class media routing

For this assignment, LiveKit reduces more risk than it adds.

---

## 15. Final Implementation Notes

If this architecture is implemented faithfully, the stack should satisfy the assignment more credibly than the original version because:

1. the telephony path matches the chosen products
2. transfer is still possible
3. FastAPI is removed from the most fragile latency path
4. Redis is no longer adding avoidable hot-path complexity
5. scale claims are tied to measured worker capacity rather than invented host math

---

*End of Document — Platform Architecture v2.0*
