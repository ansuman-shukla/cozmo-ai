# Cozmo AI — Take-Home Assignment

## Problem

Design, implement, and demonstrate a **production-ready voice AI agent system** that can handle **100 concurrent PSTN calls** with real-time responsiveness.

A caller dials a phone number. An AI agent picks up, understands what they say, thinks, and responds — naturally, fast, and without breaking under load.

---

## Constraints

### Tech Stack (fixed)
- **Backend:** FastAPI
- **Database:** MongoDB
- **Telephony:** Twilio SIP trunk (inbound PSTN)
- **Media layer:** LiveKit (WebRTC SFU)
- **Agent framework:** livekit-agents

### Performance
- End-to-end latency (caller speech-end → agent audio start) **< 600ms average** across 100 concurrent calls
- p95 latency < 900ms
- Failed call setup rate < 1%

### Scale
- Must support **100 concurrent active calls** without latency degradation
- Architecture must have a documented path to 1,000+ calls

### Voice UX
- Must support **barge-in** — caller can interrupt the agent mid-speech
- Must handle graceful **turn-taking**
- Must handle at least **one objection scenario** (e.g. "I don't believe that")

### Knowledge
- Must integrate a **mini knowledge base** (vector search)
- Agent must answer domain-specific questions accurately
- Must have a **fallback** when no relevant answer is found

### Resilience
- At least one **failure recovery mechanism** must be implemented (e.g. agent reconnect on drop, retry policy)

---

## Deliverables

### Code & Config
- [ ] Full repo with a working `README.md` and setup instructions
- [ ] FastAPI backend — Twilio webhook handler, LiveKit room creation, session management
- [ ] livekit-agents worker — full pipeline: VAD → STT → RAG → LLM → TTS
- [ ] Barge-in implementation
- [ ] Knowledge base — ingestion script + ChromaDB setup + retrieval integration
- [ ] Failure recovery — agent reconnect logic or retry policy (at least one)
- [ ] `docker-compose.yml` — spins up the full stack (LiveKit, FastAPI, agent workers, MongoDB, ChromaDB)
- [ ] `.env.example` — all required environment variables documented
- [ ] Load test script — simulates 100 concurrent calls

### Observability
- [ ] Per-call latency instrumentation — STT / LLM / TTS / total RTT per turn
- [ ] Prometheus `/metrics` endpoint with all key metrics
- [ ] MOS / jitter / packet loss collection from LiveKit room stats

### Architecture Docs
- [ ] `PRD.md` — product requirements document
- [ ] `PLATFORM_ARCHITECTURE.md` — full technical architecture document
- [ ] Diagram 1 — high-level system architecture
- [ ] Diagram 2 — call flow (control plane + media pipeline)
- [ ] Diagram 3 — scaling plan (1 → 100 → 1000 calls)
- [ ] LiveKit vs Pipecat write-up (pros, cons, when to use each)

### Demo
- [ ] Recorded video showing multiple calls running concurrently
- [ ] One latency measurement run demonstrating < 600ms round-trip
- [ ] Agent handling a barge-in interruption live on the recording

### 1-Pager
- [ ] What breaks at 1,000 calls?
- [ ] How would you fix it?
- [ ] Where is the latency bottleneck today?