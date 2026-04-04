# Product Requirements Document
## Cozmo AI — Enterprise Voice AI Agent Platform (PSTN)

**Document version:** 2.0  
**Status:** Draft — Hardened for Implementation  
**Author:** Cozmo AI Platform Engineering  
**Last updated:** 2026-04-04  
**Companion document:** `platform-architecture-cozmo.md`

---

## 1. Executive Summary

This document defines the v1 product requirements for a production-oriented inbound voice AI platform that answers PSTN calls using:

- **Twilio Elastic SIP Trunking** for PSTN ingress
- **LiveKit SIP + dispatch rules** for media admission and room creation
- **livekit-agents** for per-call voice agent execution
- **FastAPI** for control-plane APIs, configuration, session storage, knowledge ingestion, and observability

The corrected architecture removes FastAPI from the inbound telephony admission path. That is the main hardening decision in this revision. Twilio routes calls to LiveKit over SIP, LiveKit authenticates the trunk and dispatches the room, and the agent worker joins the room directly. FastAPI remains critical, but not for first-hop call setup.

This design is simpler, matches the actual SIP product boundaries, preserves a clean path to human transfer, and scales more credibly to the assignment target of **100 concurrent active PSTN calls**.

---

## 2. Problem Statement

Enterprises want phone automation that sounds natural, responds quickly, and does not collapse under concurrent traffic. A voice AI system for PSTN has to solve three hard problems at once:

- low-latency turn taking and barge-in
- reliable SIP/PSTN integration
- operational visibility and recovery under load

The assignment requires a system that can:

- answer inbound PSTN calls
- support barge-in and graceful turn-taking
- use a small knowledge base
- handle at least one objection scenario
- recover from at least one failure mode
- sustain **100 concurrent calls**
- keep average end-to-end response time under **600 ms**

---

## 3. Goals And Non-Goals

### 3.1 Goals

| # | Goal | Priority |
|---|------|----------|
| G1 | Accept inbound PSTN calls through Twilio SIP trunking into LiveKit SIP with no application webhook on the admission path | P0 |
| G2 | Run one voice agent session per active call with interruptible speech output and natural turn-taking | P0 |
| G3 | Achieve average **perceived** response latency below 600 ms across 100 concurrent calls | P0 |
| G4 | Support 100 concurrent active calls with explicit capacity headroom and a documented path to 1000+ | P0 |
| G5 | Ground answers in a mini knowledge base and fall back safely when relevant knowledge is unavailable | P0 |
| G6 | Expose per-turn latency, call setup latency, worker saturation, and room quality metrics | P0 |
| G7 | Support at least one recovery path for worker/job failure without dropping the PSTN call immediately | P1 |
| G8 | Support human escalation through a telephony path that is actually compatible with the selected stack | P1 |
| G9 | Keep the repository and runtime setup simple enough for take-home implementation with `uv` and Docker Compose | P1 |

### 3.2 Non-Goals

- outbound campaigns or dialer workflows
- full multi-tenant SaaS provisioning
- agent desktop or supervisor UI
- compliance archiving, call recording governance, or PCI workflows
- multilingual support in v1
- browser/web voice transport as a first-class target
- exact production HA guarantees beyond what is actually implemented and tested

---

## 4. Locked Product Decisions

These decisions are fixed for this version of the plan.

### 4.1 Telephony Admission

Inbound PSTN calls will use:

- **Twilio Elastic SIP Trunking**
- **LiveKit inbound SIP trunk**
- **LiveKit dispatch rules**

The platform will **not** rely on Twilio Programmable Voice webhooks plus TwiML `<Dial><Sip>` as the primary call admission flow.

### 4.2 FastAPI Role

FastAPI remains in scope, but its role is:

- agent configuration and DID mapping
- knowledge ingestion APIs
- session and transcript APIs
- LiveKit and Twilio webhook/event handling
- metrics and health endpoints
- provisioning helpers for SIP resources and dispatch metadata

FastAPI is **not** the first-hop router for inbound calls.

### 4.3 State Management

Per-call conversational state is kept **in memory inside the agent job** for the duration of the call.

Redis is **not** on the per-turn hot path. If included, Redis is limited to:

- idempotency keys for duplicate events
- watchdog leases / orphaned-call recovery
- replay queue for failed transcript writes

### 4.4 Scalability Model

The system scales by independently scaling:

- LiveKit SIP/SFU capacity
- agent worker servers
- FastAPI replicas
- storage backends

Capacity for 100 calls is not justified by static per-process RAM guesses. It is justified by:

- a worker pool architecture that can scale horizontally
- benchmark-derived `verified_jobs_per_worker_server`
- a load test that proves the SLO

---

## 5. Personas And User Stories

### 5.1 Personas

**Enterprise buyer**  
Needs confidence that the system is reliable, secure, and operationally legible.

**Enterprise operator**  
Needs configurable personas, knowledge updates, transcripts, and performance visibility.

**End caller**  
Needs fast, natural, interruption-friendly conversation and a path to human help.

**Platform engineer**  
Needs clear boundaries between telephony, media, agent execution, and control-plane state.

### 5.2 User Stories

| ID | User story | Priority |
|----|------------|----------|
| US-01 | A caller can dial a normal phone number and hear an agent greeting within a few seconds | P0 |
| US-02 | A caller can interrupt the agent while it is speaking | P0 |
| US-03 | The agent can answer domain-specific questions using grounded knowledge | P0 |
| US-04 | The system falls back safely when no relevant knowledge exists | P0 |
| US-05 | Different DIDs can map to different agent configurations | P1 |
| US-06 | The system can transfer a caller to a human using a supported telephony path | P1 |
| US-07 | Engineers can inspect per-stage latency and identify the bottleneck | P0 |
| US-08 | The platform can recover from an agent job crash without immediately terminating the PSTN leg | P1 |

---

## 6. Functional Requirements

### 6.1 Telephony And Call Admission

**FR-T1 — Inbound PSTN routing**  
Inbound PSTN calls MUST arrive through Twilio Elastic SIP Trunking and MUST be forwarded to LiveKit SIP over a pre-provisioned inbound trunk.

**FR-T2 — LiveKit admission and dispatch**  
LiveKit MUST authenticate the inbound SIP trunk, create a SIP participant automatically for the caller, place that participant into a room, and dispatch the room to an available `livekit-agents` worker job.

**FR-T3 — One room per call**  
Each inbound call MUST map 1:1 to a unique LiveKit room. Room naming MAY use a deterministic prefix such as `call-`.

**FR-T4 — DID-based configuration**  
The platform MUST support binding a DID or SIP ingress path to a specific agent configuration. This mapping MUST be resolved by telephony provisioning metadata or dispatch configuration, not by a synchronous FastAPI lookup on the call admission path.

**FR-T5 — Call lifecycle persistence**  
The platform MUST create and update a call session record containing:

- provider call identifier if available
- LiveKit room name
- DID
- ANI when available
- agent configuration identifier
- timestamps for created, connected, and ended
- disposition and escalation target when applicable

**FR-T6 — Human escalation**  
Human escalation MUST use a compatible SIP transfer path. For v1, this means a LiveKit-supported transfer or outbound SIP/PSTN handoff path, not an unsupported TwiML-only assumption.

### 6.2 Media And Agent Execution

**FR-M1 — Real-time media layer**  
LiveKit MUST be the media plane for inbound audio and outbound synthesized audio.

**FR-M2 — Agent worker model**  
Agent execution MUST use `livekit-agents` worker servers that register with LiveKit and accept dispatched jobs. Each active call MUST run in an isolated job context.

**FR-M3 — Audio subscription**  
The agent job MUST subscribe to the caller audio track as soon as the SIP participant is live in the room.

### 6.3 Conversational Pipeline

**FR-A1 — Turn detection**  
The platform MUST detect speech start and speech end using low-latency endpointing suitable for PSTN audio. Silero VAD through `livekit-agents` is the baseline.

**FR-A2 — STT**  
The platform MUST use a streaming STT provider. The hardened baseline is **Deepgram Nova-3 streaming**. The implementation MUST keep the provider configurable.

**FR-A3 — LLM**  
The platform MUST use a low-latency streaming text model. The provider and model name MUST be configuration, not architecture.

**FR-A4 — RAG**  
Before each response, the platform MUST query the knowledge base and inject only relevant retrieved chunks into the prompt. If no chunk clears the relevance threshold, the platform MUST use a no-answer fallback.

**FR-A5 — TTS**  
The platform MUST use streaming TTS and begin publishing audio as soon as the first stable chunk is available. The hardened baseline is **Deepgram Aura-2** with model/voice configurable.

**FR-A6 — Barge-in**  
If the caller starts speaking while TTS is active, the system MUST stop or cancel the current response stream quickly enough for the caller to perceive interruption support.

**FR-A7 — Conversation state**  
Conversation history for the active call MUST be stored in memory inside the agent job, trimmed by token budget, and persisted asynchronously to MongoDB for audit and recovery.

**FR-A8 — Objection handling**  
The platform MUST handle at least one objection scenario with either:

- a scripted rebuttal
- a bounded LLM instruction
- escalation to human handoff

### 6.4 Knowledge Base

**FR-K1 — Knowledge store**  
The v1 knowledge store MUST be ChromaDB. The architecture MUST allow migration to a different vector store later without changing call flow.

**FR-K2 — Ingestion**  
FastAPI MUST expose authenticated endpoints or scripts for ingesting text, FAQ JSON, and file-derived content into ChromaDB.

**FR-K3 — Fallback**  
If retrieval returns no relevant context, the agent MUST not invent a factual answer. It MUST use a configured fallback response and MAY escalate.

### 6.5 Observability

**FR-O1 — Per-turn timing**  
The platform MUST emit at least:

- end-of-speech timestamp
- STT completion timestamp
- first LLM token timestamp
- first TTS audio timestamp

**FR-O2 — Two latency definitions**  
The system MUST track both:

- `pipeline_rtt`: endpoint detected → first agent audio
- `perceived_rtt`: last caller speech frame → first agent audio

The assignment SLO is evaluated against **perceived RTT**.

**FR-O3 — Setup metrics**  
The system MUST track inbound call setup latency, dispatch delay, active jobs, failed setups, and room quality metrics.

**FR-O4 — Voice quality**  
The system MUST collect packet loss, jitter, and a call quality estimate from LiveKit room stats.

**FR-O5 — Transcript logging**  
User and agent turns MUST be persisted asynchronously in turn order and MUST NOT block the hot path.

---

## 7. Non-Functional Requirements

### 7.1 Latency

| Requirement | Target | Hard limit |
|-------------|--------|------------|
| Average perceived RTT across 100 concurrent calls | < 600 ms | < 900 ms p95 |
| Average pipeline RTT across 100 concurrent calls | < 400 ms | < 650 ms p95 |
| STT latency | < 150 ms avg | < 300 ms |
| LLM time-to-first-token | < 250 ms avg | < 500 ms |
| TTS time-to-first-audio | < 150 ms avg | < 300 ms |
| KB retrieval latency | < 50 ms avg | < 100 ms |
| Barge-in cancellation | < 100 ms target | < 200 ms |
| Agent dispatch delay | < 500 ms target | < 1000 ms |

### 7.2 Scalability

| Requirement | Target |
|-------------|--------|
| Concurrent active calls | 100 |
| Capacity buffer at steady state | 30% verified headroom |
| Worker scaling unit | active agent jobs per worker server |
| LiveKit topology for 100 calls | single SIP/SFU node acceptable if benchmarked |
| FastAPI topology | 2+ stateless replicas recommended, but not required for call admission |

Scaling math for the worker layer:

```text
verified_jobs_per_worker_server = result of load test
required_worker_servers = ceil(target_calls / verified_jobs_per_worker_server * 1.3)
```

This formula is normative. Any hard host-count claim in implementation docs must be backed by a benchmark.

### 7.3 Reliability

| Requirement | Target |
|-------------|--------|
| Failed call setup rate | < 1% |
| Automatic recovery from agent job crash | implemented and demonstrated |
| Recovery target after agent job loss | best effort, target < 5 s |
| Call metadata durability for v1 | single MongoDB node with journaling |

Important clarification:

- A single MongoDB node is acceptable for the take-home.
- It is **not** a highly available design.
- The docs MUST NOT claim no-data-loss on single-node failure.

### 7.4 Maintainability

- Python dependency management MUST use **`uv`**
- The repository MUST use `pyproject.toml` and `uv.lock`
- Services MUST be containerized
- Local/staging startup MUST be reproducible with Docker Compose
- Model providers and model names MUST be configuration, not hardcoded architecture

---

## 8. System Constraints And Assumptions

### 8.1 Fixed Technology Choices

| Component | Choice |
|-----------|--------|
| Backend | FastAPI |
| Database | MongoDB |
| Telephony | Twilio SIP trunking |
| Media layer | LiveKit |
| Agent framework | `livekit-agents` |
| Vector store | ChromaDB |
| Package manager | `uv` |

### 8.2 Deployment Assumptions

- Twilio trunking credentials and routing are provisioned before testing.
- LiveKit SIP ingress is publicly reachable from Twilio.
- End-to-end PSTN testing requires a public SIP endpoint; purely local Docker Compose is insufficient for a real inbound phone test.
- The knowledge base is relatively small in v1 and can be kept warm in memory.
- The demo architecture is allowed to use a single LiveKit node and single MongoDB node, provided the docs are explicit about the limits.

### 8.3 Call-Quality Assumptions

- English only in v1
- standard PSTN audio quality
- average call length 2 to 5 minutes
- no DTMF-first IVR flows in scope

---

## 9. Success Metrics And Acceptance Criteria

### 9.1 Hard Gates

| ID | Criterion | Measurement |
|----|-----------|-------------|
| AC-01 | 100 concurrent active calls supported | load test against benchmark environment |
| AC-02 | Average perceived RTT < 600 ms | metrics from load test |
| AC-03 | p95 perceived RTT < 900 ms | metrics from load test |
| AC-04 | Barge-in succeeds in > 95% of test attempts | scripted QA |
| AC-05 | KB answers correct on a fixed evaluation set | manual or scripted eval |
| AC-06 | Agent job failure recovery is demonstrated | chaos test |
| AC-07 | Failed call setup rate < 1% | telephony/load test telemetry |
| AC-08 | Required metrics are visible in Prometheus during live calls | observability check |

### 9.2 Metrics That Must Exist

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

---

## 10. Risks And Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Misconfigured SIP trunk or dispatch rule prevents calls from landing in LiveKit | Medium | High | treat telephony provisioning as a first-class setup artifact; validate with a smoke test before app work |
| LLM TTFT spikes break the latency target | Medium | High | keep model configurable, stream immediately, and benchmark with the actual chosen model |
| Endpointing window makes perceived RTT fail even when pipeline RTT looks good | High | High | track both latency definitions and tune endpointing explicitly |
| Worker saturation causes dispatch delay | Medium | High | scale on verified jobs-per-worker-server, not guessed memory math |
| ChromaDB degrades under concurrent reads | Low | Medium | keep KB small for v1, warm the index, and document Qdrant as future scale path |
| MongoDB outage loses transcripts or metadata writes | Medium | Medium | async writes, dead-letter/retry queue, explicit statement that v1 storage is not HA |
| Transfer path fails if implemented with the wrong telephony primitive | Medium | High | use LiveKit-compatible SIP transfer flow only |

---

## 11. Out Of Scope And Future Work

### Out of Scope For v1

- outbound dialing
- full active-active HA
- multi-region media routing
- multi-tenant isolation
- browser transport
- compliance archiving

### Future Work

- migrate vector storage if KB size or tenant count outgrows ChromaDB
- add active-passive or clustered LiveKit for stronger uptime
- add call recording and redaction
- add multilingual models
- add web and mobile voice transports

---

## 12. Final Architecture Summary

The v1 platform is locked to the following shape:

1. Twilio trunking delivers inbound PSTN calls directly to LiveKit SIP.
2. LiveKit inbound trunk and dispatch rules create one room per call and dispatch the agent.
3. Agent workers run per-call jobs with in-memory conversation state.
4. FastAPI handles everything around the call, but not first-hop admission.
5. Redis, if used, supports recovery and idempotency only.
6. Scalability to 100 calls is justified by horizontal worker scaling plus load-tested verified capacity, not speculative per-process host math.

---

*End of Document — PRD v2.0*
