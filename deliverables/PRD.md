# Product Requirements Document
## Cozmo AI Voice Agent Platform

**Version:** 3.0  
**Status:** Deliverable draft  
**Last updated:** April 5, 2026

## 1. Product Summary

The product is an inbound PSTN voice agent that answers business phone calls, responds naturally, supports interruption, uses a knowledge base for domain grounding, and exposes enough observability to measure whether it can scale to the assignment target of 100 concurrent calls.

The system is built on:

- Twilio Elastic SIP Trunking for PSTN ingress
- LiveKit SIP + SFU for room admission and media routing
- `livekit-agents` for per-call execution
- Deepgram for streaming STT and TTS
- Gemini 3 Flash for response generation
- FastAPI for the control plane
- MongoDB for session and transcript durability
- ChromaDB for retrieval
- Prometheus and Grafana for metrics and dashboards

## 2. Problem Statement

Enterprises need phone automation that is not only conversational, but also operationally credible. A useful voice agent for inbound calls must do four things well at the same time:

- answer quickly enough to feel real-time
- support barge-in and turn-taking without awkward overlap
- answer domain-specific questions with grounded context
- remain observable and recoverable under load

The assignment asks for a system that can move from a working local prototype to a credible 100-call architecture without rethinking the entire design.

## 3. Goals

| ID | Goal | Priority |
|---|---|---|
| G1 | Accept inbound PSTN calls through Twilio SIP trunking into LiveKit SIP | P0 |
| G2 | Start one isolated voice session per active call | P0 |
| G3 | Support natural interruption and graceful turn-taking | P0 |
| G4 | Use retrieval-grounded responses against a mini knowledge base | P0 |
| G5 | Provide a safe fallback when retrieval confidence is low | P0 |
| G6 | Expose latency, setup, saturation, and room-quality metrics | P0 |
| G7 | Provide at least one concrete worker recovery path | P1 |
| G8 | Scale cleanly from 1 to 100+ concurrent calls through horizontal worker growth | P0 |
| G9 | Provide a documented path from 100 to 1000+ calls | P1 |

## 4. Non-Goals

- outbound dialing campaigns
- agent desktop tooling
- multilingual support
- browser-first voice experiences
- full enterprise HA guarantees across every dependency
- complex human transfer workflows for this delivery

## 5. Users And Primary Scenarios

### Caller

The caller wants a fast, natural, interruption-friendly conversation with the business line.

### Operator

The operator wants configurable personas, grounded knowledge responses, transcripts, and dashboards.

### Platform Engineer

The platform engineer wants a system that is easy to reason about, easy to scale, and easy to debug under live traffic.

## 6. Functional Requirements

### Telephony And Call Lifecycle

- The system must accept inbound PSTN calls through Twilio SIP trunking.
- LiveKit must create the room and dispatch the call to an available worker.
- Each call must map to one room and one call-session record.
- DID-based routing must determine which agent configuration handles the call.
- The platform must persist call lifecycle state including created, active, completed, and failed setup outcomes.

### Conversational Runtime

- The agent must greet the caller automatically.
- Caller speech must stream into STT with low-latency endpointing.
- The response path must be:
  - speech to text
  - retrieval
  - LLM
  - TTS
  - caller playback
- The agent must support barge-in.
- The agent must persist transcript turns with timing metadata.
- The agent must handle at least one objection scenario with a bounded policy path.

### Knowledge And Fallback

- The platform must ingest and index business knowledge into a vector store.
- Retrieval must be thresholded, not unconditional.
- The agent must prefer grounded answers when relevant knowledge is found.
- The agent must fall back gracefully when knowledge confidence is insufficient.

### Resilience

- The platform must implement at least one worker recovery mechanism.
- The platform must protect transcript persistence against transient write failures.
- The platform must avoid duplicate side effects when repeated events arrive.

### Observability

- The platform must expose metrics for:
  - STT latency
  - LLM TTFT
  - TTS first-audio latency
  - perceived RTT
  - call setup timing
  - active calls
  - active worker jobs
  - worker queue depth
  - failed setup rate
  - room MOS / jitter / packet loss

## 7. Performance Targets

These are the product targets for the assignment, not assumptions.

| Metric | Target |
|---|---|
| Caller speech-end -> agent audio start | < 600 ms average across 100 concurrent calls |
| Perceived RTT p95 | < 900 ms |
| Failed call setup rate | < 1% |
| Barge-in interruption | perceptibly immediate, target < 200 ms |
| Active call concurrency | 100 |

## 8. Acceptance Criteria

### Core Product

- A caller can dial the assigned number and reach the AI agent.
- The agent greets the caller and can respond on multiple turns.
- The caller can interrupt the agent while it is speaking.
- The agent can answer domain questions from the knowledge base.
- The agent uses a fallback when no grounded answer is available.

### Reliability

- A recoverable worker failure triggers a replacement-job recovery flow.
- Transcript persistence retries transient failures and preserves ordering.

### Observability

- Prometheus can scrape backend and worker metrics.
- Grafana displays active calls, setup rate, latency, worker load, and room quality.
- The system can produce evidence for staged PSTN smoke tests and stepped load tests.

### Scalability

- The codebase contains a 25 / 50 / 100-call load validation path.
- The architecture doc explains how to scale worker capacity without changing call flow fundamentals.

## 9. Product Decisions

### Why FastAPI is not on the first-hop telephony path

Call admission must stay as deterministic as possible. Twilio hands off to LiveKit SIP, LiveKit creates the room, and the worker joins directly. FastAPI remains essential, but it is not used as the PSTN admission router.

### Why live conversational state stays in the worker

Turn-taking, barge-in, and low-latency audio control all require the active worker job to own the live state. Persisted state is used for durability and inspection, not as the hot path for every token or frame.

### Why RAG is a first-class product capability

The assignment explicitly asks for domain-specific answers. A voice agent without grounded retrieval would either hallucinate or become too scripted. The product therefore treats ingestion, retrieval, and fallback as core capabilities, not optional enhancements.

## 10. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| LLM TTFT dominates perceived latency | Slow caller experience | stage-level metrics, load testing, provider tuning |
| Provider API limits under concurrency | degraded throughput | quota-aware scaling and provider-specific tuning |
| Worker saturation at higher concurrency | queueing and rising RTT | horizontal worker scaling and saturation dashboards |
| Room-quality visibility inconsistent across short-lived calls | harder quality debugging | persist room-quality snapshots into durable session metrics |
| Setup failures inflate production-like metrics in dev history | misleading dashboards | use rate metrics and clean test datasets for formal validation |

## 11. Success Definition

The product is successful for this assignment when it can be demonstrated as:

- telephony-correct
- interruption-capable
- knowledge-grounded
- observable
- recoverable
- architecturally credible at 100 concurrent calls

The final performance claim, especially `< 600 ms average across 100 calls`, must be backed by measured load-validation output rather than architecture alone.
