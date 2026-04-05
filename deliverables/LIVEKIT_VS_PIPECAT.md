# LiveKit vs Pipecat — Framework Comparison

**Context:** This write-up compares LiveKit and Pipecat as primary frameworks for building real-time voice AI agents, with a focus on production telephony at scale.

---

## Core Philosophy

| | LiveKit | Pipecat |
|---|---|---|
| **What it is** | Real-time media infrastructure platform with an Agents framework on top | Transport-agnostic conversational AI orchestration framework |
| **Primary strength** | Owns the full media stack — WebRTC transport, SFU routing, session management, SIP ingress | Owns the pipeline logic — modular, pluggable stages for STT → LLM → TTS orchestration |
| **Architecture model** | Infrastructure-first: media server + agent runtime as one cohesive system | Pipeline-first: agent logic is decoupled from transport entirely |

---

## Head-to-Head Comparison

### Telephony and SIP

| Dimension | LiveKit | Pipecat |
|---|---|---|
| SIP ingress | Native SIP Bridge — terminates SIP INVITE directly into rooms | No built-in SIP. Requires external SIP-to-WebSocket bridge or third-party transport |
| PSTN integration | Twilio SIP trunk → LiveKit SIP → Room → Worker. Clean, well-documented path | Requires custom glue: Twilio → media bridge → Pipecat pipeline |
| Call lifecycle | Room-native: create, join, leave, close events are first-class | Application-defined: developer builds lifecycle management manually |
| **Verdict** | ✅ Stronger for telephony-first systems | Better when telephony is secondary to browser/WebSocket use cases |

### Media Plane and Real-Time Control

| Dimension | LiveKit | Pipecat |
|---|---|---|
| Media transport | WebRTC SFU with room-level control, participant management, selective track subscriptions | Transport-agnostic — works with Daily, LiveKit, raw WebSockets, etc. |
| Barge-in | Worker has direct visibility into TTS playback + caller speech inside the room. Interruption handling is natural | Achievable but requires more manual coordination between transport callbacks and pipeline state |
| Room-level stats | Jitter, packet loss, MOS, participant bitrate — available via SDK | Depends on which transport is used underneath |
| **Verdict** | ✅ Stronger for low-latency media control and observability | Better when you need transport flexibility across multiple backends |

### Worker Orchestration and Scaling

| Dimension | LiveKit | Pipecat |
|---|---|---|
| Worker model | `livekit-agents` provides job dispatch, room assignment, worker registration, and concurrency management out of the box | No built-in worker orchestration. Application defines how agents are spawned and assigned |
| Horizontal scaling | Scale worker servers → more available jobs. Queue depth and active jobs are observable | Scaling is custom: developer manages process pools, load distribution, and failover |
| Failure recovery | Job-level failure detection + replacement dispatch is architecturally supported | Requires custom crash detection, state recovery, and re-assignment logic |
| **Verdict** | ✅ Stronger for concurrent call handling at scale | Better when you want full control over agent lifecycle outside a media framework |

### Pipeline Flexibility

| Dimension | LiveKit | Pipecat |
|---|---|---|
| Pipeline composition | Structured around the `AgentSession` abstraction. STT → LLM → TTS with hooks | Fully modular pipeline graph. Insert custom processors, filters, parallel branches at any stage |
| Provider swapping | Supported but within the LiveKit ecosystem's adapter model | Extremely easy — large library of pre-built integrations for STT, TTS, LLM providers |
| Custom logic injection | Possible via hooks and plugins, but the pipeline shape is more fixed | Core strength — pipeline stages are composable building blocks |
| **Verdict** | Good for standard voice agent patterns | ✅ Stronger for experimental, rapidly-iterating, or non-standard conversational flows |

### Observability and Production-Readiness

| Dimension | LiveKit | Pipecat |
|---|---|---|
| Metrics | Room quality, worker saturation, dispatch latency — all available for Prometheus/Grafana integration | Application-defined. Developer instruments their own metrics |
| Logging | Structured logs from both server and agent SDK | Standard Python logging |
| Production deployment | Designed for production-scale WebRTC. Battle-tested at high concurrency | Production-capable but the developer owns more of the operational stack |
| **Verdict** | ✅ Stronger for production telemetry out of the box | Sufficient when the team already has strong observability practices |

---

## Decision Matrix

| Criterion | LiveKit | Pipecat | Winner for this project |
|---|---|---|---|
| SIP / PSTN alignment | Native SIP Bridge | Custom integration | **LiveKit** |
| Media-plane ownership | WebRTC SFU, room-native | Transport-agnostic | **LiveKit** |
| Worker dispatch and scaling | Built-in job model | Application-defined | **LiveKit** |
| Barge-in / interruption control | Room-level, low-latency | Pipeline-level, more manual | **LiveKit** |
| Pipeline flexibility | Good | Exceptional | **Pipecat** |
| Production observability | Strong, integrated | Application-defined | **LiveKit** |
| Rapid prototyping | Good | Excellent | **Pipecat** |
| 100-call scalability story | Proven architecture | Depends on orchestration | **LiveKit** |

---

## When to Choose Each

### Choose LiveKit when:

- The system is **PSTN-first or SIP-first** — LiveKit's native SIP bridge eliminates an entire integration layer
- You need **100+ concurrent calls** with clear horizontal scaling and worker orchestration
- **Room-level media control** matters — barge-in, selective track subscription, room quality metrics
- You want **production-grade observability** without building the telemetry layer yourself
- The assignment or product specifically mandates LiveKit in the tech stack

### Choose Pipecat when:

- The system is **browser-first or WebSocket-first** — telephony is secondary or handled externally
- You need **maximum pipeline flexibility** — rapid experimentation with different STT/TTS/LLM combinations
- The product requires **custom multimodal orchestration** beyond standard voice agent patterns
- Your team prefers a **Python-native, modular development workflow** with full control over agent lifecycle
- Transport flexibility matters — you may switch between Daily, LiveKit, or custom WebSocket backends

---

## Why LiveKit Was Chosen for This Project

This project's hardest constraints are not conversational — they are **telephony, scalability, and operational clarity**:

1. **Inbound PSTN through Twilio SIP trunking** — LiveKit's SIP Bridge handles this natively
2. **100 concurrent calls** — LiveKit's worker dispatch and job model provide a clear scaling path
3. **Observable, recoverable system** — room-level metrics, job-level failure detection, and replacement dispatch are architecturally supported
4. **Sub-600ms perceived RTT** — WebRTC media transport with in-process STT/TTS streaming keeps the hot path tight

Pipecat could have made the conversational pipeline more flexible, but it would have introduced more custom integration work in the exact areas where this project needs the most reliability: SIP ingestion, room lifecycle, worker orchestration, and production observability.

**LiveKit is the more defensible architectural choice for this system.**
