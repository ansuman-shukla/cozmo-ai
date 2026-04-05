# Staged PSTN Smoke Test Checklist

Use this checklist only after backend, agent, Prometheus, and Grafana are already running and the LiveKit/Twilio setup is pointed at the active environment.

## 1. Preflight

- Confirm `GET /ready` returns `200`.
- Confirm `curl http://127.0.0.1:9090/api/v1/targets` shows backend and agent scrape targets `up`.
- Confirm the active DID has an `agent_config` in Mongo.
- Confirm the LiveKit webhook still points to the current public backend URL.
- Confirm the worker is registered as `inbound-agent`.

## 2. Execute One Live Call

- Place one inbound PSTN call to the configured Twilio number.
- Let the call ring, connect, and remain active for at least 10 seconds.
- Speak once after the greeting placeholder to trigger transcript and pipeline activity.
- Hang up normally from the caller side.

## 3. Evidence To Capture

- Backend log lines for `/webhooks/livekit` and any Twilio status callback.
- Worker log lines for `received job request`, `bootstrapped inbound call`, and disconnect.
- `GET /calls`
- `GET /calls/{room_name}`
- `GET /calls/{room_name}/transcript`
- Grafana screenshots for:
  - Active Calls
  - Call Setup And RTT
  - Worker Saturation
  - Room Quality

## 4. Pass Criteria

- Call lands in LiveKit and is dispatched to `inbound-agent`.
- `call_sessions` record exists with the expected DID, ANI, and `agent_config_id`.
- `metrics_summary.call_setup_ms` is populated.
- `voice_quality` contains jitter, packet loss, or MOS data after the call stays connected long enough.
- Transcript turns are persisted in order.
- Prometheus shows no target scrape failures during the call.

## 5. Failure Triage

- `401` on `/webhooks/livekit`: check LiveKit webhook signing key vs backend env.
- No worker job request: check LiveKit dispatch rule and `LIVEKIT_DISPATCH_AGENT_NAME`.
- No session record: check backend Mongo connectivity and webhook logs.
- Prometheus target `down`: check whether backend and agent are running on the host or inside Compose and verify the current Prometheus scrape targets.
