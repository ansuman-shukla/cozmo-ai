# Platform Architecture — Cozmo AI Voice Agent

**Version:** 3.0 · **Last updated:** April 2026

---

## 1. Architecture Principles

The platform is designed around a single core rule: **keep the inbound PSTN and media path as short as possible**, and move control, persistence, retrieval, and observability to adjacent systems that never sit on the first-hop call setup path.

| Concern | Component | Role |
|---|---|---|
| PSTN ingress | Twilio Elastic SIP Trunk | Terminates inbound calls, forwards SIP INVITE |
| Media transport | LiveKit SIP + SFU | Room creation, participant dispatch, WebRTC media |
| Per-call execution | `livekit-agents` worker fleet | Voice pipeline: VAD → STT → RAG → LLM → TTS |
| Speech-to-text | Deepgram Streaming STT | Low-latency endpointing and transcription |
| Speech synthesis | Deepgram Streaming TTS | Real-time audio synthesis |
| Response generation | Gemini 3 Flash | Context-grounded response generation |
| Control plane | FastAPI | Agent config, knowledge APIs, session storage, metrics, webhooks |
| Persistence | MongoDB | Call sessions, transcripts, agent configuration |
| Vector retrieval | ChromaDB | Knowledge base ingestion and semantic search |
| Observability | Prometheus + Grafana | Metrics scraping, dashboards, alerting |

This separation keeps call admission **deterministic** while still giving the system a strong control plane, retrieval layer, and operator visibility.

---

## 2. High-Level System Architecture

```mermaid
flowchart TB
    subgraph PSTN["PSTN Layer"]
        Caller["📞 PSTN Caller"]
        Twilio["Twilio Elastic SIP Trunk"]
    end

    subgraph Media["Media Layer"]
        LiveKit["LiveKit SIP + SFU"]
    end

    subgraph Compute["Compute Layer"]
        Worker["Agent Worker Fleet"]
        DG_STT["Deepgram STT"]
        DG_TTS["Deepgram TTS"]
        Gemini["Gemini 3 Flash"]
    end

    subgraph Control["Control Plane"]
        API["FastAPI"]
    end

    subgraph Data["Data Layer"]
        Mongo[("MongoDB")]
        Chroma[("ChromaDB")]
    end

    subgraph Observability["Observability"]
        Prom["Prometheus"]
        Grafana["Grafana Dashboards"]
    end

    Caller --> Twilio
    Twilio -->|SIP INVITE| LiveKit
    LiveKit -->|Dispatch room| Worker
    Worker <-->|Streaming audio| LiveKit
    Worker -->|Streaming speech| DG_STT
    DG_STT -->|Transcript| Worker
    Worker -->|Response text| DG_TTS
    DG_TTS -->|Audio stream| Worker
    Worker -->|Prompt + context| Gemini
    Gemini -->|Response| Worker
    Worker -->|Knowledge query| API
    Worker -->|Session + transcript writes| Mongo
    API <--> Mongo
    API <--> Chroma
    Worker -.->|Metrics| Prom
    API -.->|Metrics| Prom
    Prom --> Grafana
```

### Why this structure works

- **Twilio + LiveKit handle telephony admission and media routing directly**, so FastAPI is never in the call setup critical path. A call connects to a worker in under one SIP INVITE → room dispatch cycle.
- **Workers own the live conversation state** for the duration of the call. Turn-taking, barge-in, and interruption handling all execute at media-loop speed inside the worker process.
- **FastAPI is the durable control plane** — agent configuration, session inspection, transcript queries, knowledge ingestion, and Prometheus metrics. It does not block any call setup.
- **Vector retrieval is invoked per-turn at response time**, not pre-baked into static prompts. This keeps answers current and grounded.

---

## 3. Call Flow — Control Plane + Media Pipeline

```mermaid
sequenceDiagram
    participant Caller as 📞 Caller
    participant Twilio as Twilio SIP
    participant LK as LiveKit SFU
    participant W as Agent Worker
    participant STT as Deepgram STT
    participant KB as ChromaDB (RAG)
    participant LLM as Gemini 3 Flash
    participant TTS as Deepgram TTS
    participant DB as MongoDB
    participant API as FastAPI

    Note over Caller,LK: ── Call Setup (Control Plane) ──

    Caller->>Twilio: Dial business number
    Twilio->>LK: SIP INVITE (TCP)
    LK->>LK: Create room + SIP participant
    LK->>W: Dispatch inbound job
    W->>LK: Join room, subscribe to caller audio
    W->>DB: Resolve DID → agent config
    W->>DB: Create call session (status: active)
    W->>Caller: 🔊 Initial greeting

    Note over Caller,TTS: ── Conversational Loop (Media Plane) ──

    loop Every caller turn
        Caller->>W: Speech (via LiveKit room audio)
        W->>STT: Stream audio → Deepgram
        STT-->>W: Transcript (endpointed)

        W->>KB: Vector similarity query (top-k)
        KB-->>W: Grounding context (or no-hit)

        W->>LLM: Prompt = persona + history + KB context
        LLM-->>W: Response text (streaming TTFT)

        W->>TTS: Synthesize response audio
        TTS-->>W: Audio stream

        W->>Caller: 🔊 Interruptible speech output
        W-->>DB: Persist transcript turn + latency metrics
    end

    Note over Caller,API: ── Lifecycle Events ──

    LK-->>API: Webhook (room closed, participant left)
    API->>DB: Update session → completed / failed
```

### Critical design choices in this flow

| Choice | Rationale |
|---|---|
| Worker is the conversational state owner | Turn-taking, barge-in, and interruption all require the active process to hold live state. No round-trips to a database on the hot path. |
| Retrieval is invoked at response time | Not pre-baked into static prompts. Each turn gets fresh, relevant context from the knowledge base. |
| Transcript and session writes are async | They are side-effects, not blockers for the caller-facing media loop. The caller never waits on a MongoDB write. |
| Barge-in is handled inside the worker | The worker sees both TTS playback state and caller speech simultaneously, so it can cancel playback within ~200 ms. |
| Filler speech covers retrieval latency | When RAG takes noticeably longer, the agent uses filler speech to prevent dead air while the system checks the knowledge base. |

---

## 4. Conversational Runtime Design

Each active call runs as an **isolated worker job** with the following responsibilities:

```mermaid
flowchart LR
    subgraph Job["Per-Call Worker Job"]
        direction TB
        J1["Join dispatched LiveKit room"]
        J2["Resolve DID → agent config"]
        J3["Start streaming AgentSession"]
        J4["Maintain in-memory conversation history"]
        J5["Run speech pipeline"]
        J6["Persist transcripts + call state"]
        J7["Emit stage-level latency metrics"]

        J1 --> J2 --> J3 --> J4 --> J5 --> J6 --> J7
    end

    subgraph Pipeline["Speech Pipeline"]
        direction LR
        P1["🎙️ Caller Audio"] --> P2["STT"]
        P2 --> P3["RAG Retrieval"]
        P3 --> P4["LLM"]
        P4 --> P5["TTS"]
        P5 --> P6["🔊 Caller Audio"]
    end
```

### Voice UX capabilities

| Capability | Implementation |
|---|---|
| **Interruptible TTS (Barge-in)** | Caller speech cancels active TTS playback immediately. Queued audio frames are dropped. |
| **Graceful turn-taking** | VAD + endpointing detect speech boundaries. Agent waits for a clean endpoint before responding. |
| **Recovery-aware bootstrap** | Replacement workers load recent transcript history and resume with a recovery prompt. |
| **Knowledge-grounded responses** | Every turn queries ChromaDB. Responses are built from retrieved context when confidence is above threshold. |
| **No-answer fallback** | When retrieval confidence is low, the agent uses an explicit fallback response instead of hallucinating. |
| **Objection handling** | A policy router directs objections to scripted trust-handling, LLM generation, or human-transfer paths. |

---

## 5. Knowledge Retrieval Architecture

The knowledge subsystem is a proper **RAG retrieval layer**, not a static prompt attachment.

```mermaid
flowchart LR
    subgraph Ingestion["Ingestion Pipeline"]
        direction TB
        S1["Business Knowledge"] --> S2["Ingestion API"]
        S2 --> S3["Chunking + Overlap"]
        S3 --> S4["Embedding (text-embedding-3-small)"]
        S4 --> S5[("ChromaDB")]
    end

    subgraph Retrieval["Per-Turn Retrieval"]
        direction TB
        Q1["Caller transcript"] --> Q2["Vector similarity query"]
        Q2 --> S5
        S5 --> Q3["Top-k + Confidence threshold"]
        Q3 --> Q4{"Score ≥ threshold?"}
        Q4 -->|Yes| Q5["Grounded prompt"]
        Q4 -->|No| Q6["Fallback response"]
    end
```

### Design properties

- **Chunked with overlap** to preserve answer continuity across document boundaries.
- **Thresholded retrieval** — low-confidence matches are filtered before they reach the prompt. The model never sees garbage context.
- **Explicit no-answer path** — when retrieval misses, the system uses a structured fallback rather than relying on the LLM to self-restrain from hallucination.
- **Multi-format ingestion** — supports plain text, structured FAQ JSON, and file-based content.

---

## 6. Recovery and Reliability

The platform implements **real recovery behavior**, not only monitoring.

### Recovery sequence

```mermaid
sequenceDiagram
    participant WA as Worker A (Active)
    participant RC as Recovery Coordinator
    participant DB as MongoDB
    participant WB as Worker B (Replacement)
    participant Call as Live Call

    WA->>DB: Persist call state + transcript
    WA--xRC: ❌ Crash / recoverable failure

    RC->>DB: Claim recovery lease (dedup guard)
    RC->>DB: Increment recovery_count
    RC->>WB: Dispatch replacement job

    WB->>DB: Load recent transcript history
    WB->>WB: Build recovery prompt with context
    WB->>Call: Resume conversation seamlessly

    Note over WB,Call: Caller experiences a brief pause,<br/>not a disconnection
```

### Implemented recovery mechanisms

| Mechanism | Description |
|---|---|
| **Replacement-job dispatch** | When a worker crash is detected, a replacement job is dispatched to the same room. The new worker loads transcript history and resumes with context. |
| **Recovery lease / dedup** | A lease prevents multiple replacement attempts for the same room. Only one recovery can be in flight at a time. |
| **Transcript write retry** | Transient MongoDB write failures are retried with backoff before falling to the dead-letter path. |
| **Dead-letter queue** | Transcript writes that fail after retry are persisted to a dead-letter collection for later replay. |
| **Idempotency protection** | Duplicate transcript events and webhook deliveries are suppressed by idempotency keys. |

---

## 7. Observability Architecture

Prometheus and Grafana are wired into **both** the backend and the worker fleet.

```mermaid
flowchart LR
    subgraph Sources["Metric Sources"]
        W["Agent Workers<br/>:9108/metrics"]
        API["FastAPI Backend<br/>:8000/metrics"]
    end

    subgraph Stack["Observability Stack"]
        Prom["Prometheus<br/>(scrape interval: 15s)"]
        Grafana["Grafana<br/>Cozmo Platform Overview"]
    end

    subgraph Storage["Durable Storage"]
        DB[("MongoDB<br/>session summaries")]
    end

    W --> Prom
    API --> Prom
    Prom --> Grafana

    W --> DB
    API --> DB
```

### Metrics taxonomy

| Category | Metrics |
|---|---|
| **Call setup** | Call setup time (ms), failed setup rate, active calls |
| **Per-turn latency** | Perceived RTT, pipeline RTT, STT latency, LLM TTFT, TTS first-audio latency |
| **Worker health** | Active jobs, queue depth, CPU utilization, memory utilization |
| **Room quality** | Jitter (ms), packet loss (%), MOS score |
| **Recovery** | Recovery count, dead-letter queue depth |

### Why both worker and backend metrics exist

- **Worker metrics** capture live stage latency, worker saturation, and in-call behavior. These are real-time signals.
- **Backend metrics** capture durable session state: active call counts, failed setup rate, persisted room-quality snapshots. These survive after short-lived worker jobs exit.

That split makes the dashboard **resilient** — the operator always has visibility even when individual worker processes have already terminated.

---

## 8. Scaling Plan — 1 → 100 → 1,000 Calls

```mermaid
flowchart TB
    subgraph S1["Stage 1 · 1–10 Calls"]
        A1["Single LiveKit instance"]
        A2["Single FastAPI process"]
        A3["1–2 worker servers"]
        A4["Single MongoDB + ChromaDB"]
        A5["Docker Compose stack"]
    end

    subgraph S2["Stage 2 · 10–100 Calls"]
        B1["Horizontal worker scaling<br/>(measured concurrency per server)"]
        B2["FastAPI behind HTTP load balancer"]
        B3["LiveKit sized for tested concurrency"]
        B4["Prometheus + Grafana for<br/>saturation alerting"]
        B5["Worker autoscaling on<br/>queue depth + p95 RTT"]
    end

    subgraph S3["Stage 3 · 100–1,000+ Calls"]
        C1["Multi-node worker fleet<br/>with autoscaling"]
        C2["Dedicated LiveKit SIP + SFU<br/>capacity pools"]
        C3["Replicated FastAPI control plane"]
        C4["Managed MongoDB (Atlas) +<br/>managed vector DB"]
        C5["Quota-aware provider routing<br/>+ backpressure"]
        C6["Multi-region Deepgram<br/>+ LLM routing"]
    end

    S1 --> S2 --> S3
```

### Worker scaling model

The worker layer is the **primary horizontal scaling unit**:

- One worker server hosts multiple active jobs.
- Safe concurrency per worker is a **measured number**, not a guessed constant — derived from observed CPU, memory, and p95 RTT under load.
- **Worker queue depth** is the first operational alarm that more capacity is needed.
- Autoscaling triggers: active jobs, queue depth, p95 perceived RTT.

### Load balancing and orchestration strategy

| Scale | Strategy |
|---|---|
| **Local / take-home** | Docker Compose. All services on one machine. Sufficient for development and demo. |
| **10–100 calls** | FastAPI behind an HTTP LB (e.g., Nginx, ALB). Workers replicated horizontally. LiveKit sized for tested concurrency. |
| **100–1,000+ calls** | Kubernetes becomes a natural fit — worker autoscaling, stateless FastAPI replicas, rollout management, resource isolation. But the architecture does **not require** Kubernetes to be conceptually scalable. |

### Why this architecture scales from 1 to 100+

| Property | Why it matters |
|---|---|
| Telephony admission offloaded to Twilio + LiveKit | FastAPI is not in the call setup path |
| Worker fleet is horizontally scalable | Add servers, not complexity |
| MongoDB writes are async from media path | Persistence never blocks the caller |
| Retrieval and LLM calls are isolated per job | No shared mutable state between calls |
| Observability exposes real saturation points | You know *where* to scale before it breaks |

Reaching 100 concurrent calls is an exercise in **measured worker concurrency, LiveKit capacity sizing, and provider throughput** — not an architectural rewrite.

---

## 9. Key Trade-Offs

### What this design optimizes for

- ✅ Telephony correctness and fast call setup
- ✅ Low operational ambiguity — every component has a single, clear responsibility
- ✅ Strong observability — stage-level latency, worker saturation, room quality
- ✅ Incremental scalability — scale layers independently
- ✅ Clean separation between media plane and control plane

### What this design deliberately does not optimize for

- ❌ Minimum component count — the system has more components than a quick demo, but each earns its place
- ❌ Zero external dependencies — Twilio, Deepgram, and Gemini are external, but they are the best-in-class choices for this use case
- ❌ Ultra-cheap prototype-only architecture — the structure is what makes the system believable at 100-call scale

---

## 10. Summary

This platform architecture meets every architectural requirement in the assignment:

| Requirement | How it is met |
|---|---|
| Scale 1 → 100+ concurrent calls | Horizontal worker scaling, offloaded telephony, async persistence |
| Workers, load balancing, orchestration | Worker fleet with measured concurrency, HTTP LB for FastAPI, Kubernetes-ready |
| Failure recovery mechanism | Replacement-job dispatch with transcript recovery, write retry, dead-letter, idempotency |
| Diagrams for every major flow | High-level architecture, call flow, scaling plan, retrieval, recovery, observability |
| Observability | Prometheus + Grafana with per-turn latency, worker health, room quality, setup timing |

The remaining proof point is **performance validation under stepped load**, not an architectural rewrite.
