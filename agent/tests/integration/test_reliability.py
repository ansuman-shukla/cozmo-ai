from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[2] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def add_repo_paths() -> tuple[str, str]:
    agent_root = str(Path(__file__).resolve().parents[2])
    contracts_root = str(Path(__file__).resolve().parents[3] / "contracts")
    sys.path.insert(0, agent_root)
    sys.path.insert(0, contracts_root)
    return agent_root, contracts_root


def remove_repo_paths(*paths: str) -> None:
    for path in paths:
        if path in sys.path:
            sys.path.remove(path)
    for name in list(sys.modules):
        if (
            name == "app"
            or name.startswith("app.")
            or name == "cozmo_contracts"
            or name.startswith("cozmo_contracts.")
            or name in {"agent_job_module_recovery", "agent_transcripts_reliability"}
        ):
            sys.modules.pop(name, None)


class FakeTranscriptRepository:
    def __init__(self, turns) -> None:
        self.turns = list(turns)

    def list_by_room_name(self, room_name: str):
        return list(self.turns)


class FakeRecoveryLeaseRepository:
    def __init__(self) -> None:
        self.claimed = set()

    def claim_recovery(self, room_name: str) -> bool:
        if room_name in self.claimed:
            return False
        self.claimed.add(room_name)
        return True


class FakeCallStateRepository:
    def __init__(self) -> None:
        self.recovery_marked = []

    def mark_recovery_pending(self, room_name: str):
        self.recovery_marked.append(room_name)
        return {"room_name": room_name, "recovery_count": len(self.recovery_marked)}


class FakeFlakyTranscriptSink:
    def __init__(self, *, failures_before_success: int = 0) -> None:
        self.failures_before_success = failures_before_success
        self.turns = []
        self.attempts = 0

    def append_transcript_turn(self, turn):
        self.attempts += 1
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise RuntimeError("transient write failure")
        self.turns.append(turn)
        return turn

    def next_turn_index(self, room_name: str) -> int:
        return 0

    def mark_transcript_turn_interrupted(self, room_name: str, turn_index: int):
        return None


class FakeDeadLetterSink:
    def __init__(self) -> None:
        self.entries = []

    def enqueue_failed_turn(self, entry):
        self.entries.append(entry)
        return entry


class FakeLocalParticipant:
    def __init__(self) -> None:
        self.attributes = {}

    async def set_attributes(self, attributes):
        self.attributes = dict(attributes)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_simulated_job_crash_triggers_recovery_path() -> None:
    inserted_paths = add_repo_paths()

    try:
        job = load_module("agent_job_module_recovery", "app/job.py")
        from cozmo_contracts.models import TranscriptTurn, TurnSpeaker

        transcript_repo = FakeTranscriptRepository(
            [
                TranscriptTurn(
                    room_name="call-+16625640501-a1b2",
                    turn_index=0,
                    speaker=TurnSpeaker.USER,
                    text="Hello",
                    timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC),
                ),
                TranscriptTurn(
                    room_name="call-+16625640501-a1b2",
                    turn_index=1,
                    speaker=TurnSpeaker.AGENT,
                    text="Hi there",
                    timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC),
                ),
            ]
        )
        recovery_repo = FakeRecoveryLeaseRepository()
        call_state_repo = FakeCallStateRepository()

        class FakeStore:
            client = object()

            def __init__(self):
                self.repository = object()

            def close(self):
                return None

        ctx = SimpleNamespace(
            room=SimpleNamespace(
                name="call-+16625640501-a1b2",
                local_participant=FakeLocalParticipant(),
            )
        )

        settings = SimpleNamespace(
            call_room_prefix="call-",
            mongo_database="cozmo",
        )

        async def _async_bootstrap(*args, **kwargs):
            raise RuntimeError("simulated job crash")

        job.get_settings = lambda: settings
        job.MongoAgentConfigStore.from_settings = classmethod(lambda cls, settings: FakeStore())
        job.MongoTranscriptStore.from_connection = classmethod(
            lambda cls, **kwargs: SimpleNamespace(repository=transcript_repo)
        )
        job.MongoTranscriptDeadLetterStore.from_connection = classmethod(
            lambda cls, **kwargs: SimpleNamespace(repository=object())
        )
        job.MongoRecoveryStore.from_connection = classmethod(
            lambda cls, **kwargs: SimpleNamespace(repository=recovery_repo)
        )
        job.MongoCallStateStore.from_connection = classmethod(
            lambda cls, **kwargs: SimpleNamespace(repository=call_state_repo)
        )
        job._bootstrap_job = _async_bootstrap

        with pytest.raises(RuntimeError, match="simulated job crash"):
            await job.inbound_agent_entrypoint(ctx)

        assert call_state_repo.recovery_marked == ["call-+16625640501-a1b2"]
        assert ctx.room.local_participant.attributes["cozmo.recovery_state"] == "recoverable"
        assert ctx.room.local_participant.attributes["cozmo.recovery_dispatch"] == "replacement_requested"
        assert "Hello" in ctx.room.local_participant.attributes["cozmo.recovery_prompt"]
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_transcript_write_retry_succeeds_after_transient_failure() -> None:
    inserted_paths = add_repo_paths()

    try:
        transcripts = load_module("agent_transcripts_reliability", "app/transcripts.py")

        sink = FakeFlakyTranscriptSink(failures_before_success=1)
        recorder = transcripts.TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=sink,
            max_retries=2,
            dead_letter_sink=FakeDeadLetterSink(),
        )

        stored = recorder.record_user_turn("retry this write")

        assert stored.turn_index == 0
        assert sink.attempts == 2
        assert len(sink.turns) == 1
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_duplicate_event_delivery_leaves_one_consistent_final_record() -> None:
    inserted_paths = add_repo_paths()

    try:
        transcripts = load_module("agent_transcripts_reliability", "app/transcripts.py")

        sink = FakeFlakyTranscriptSink()
        recorder = transcripts.TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=sink,
        )

        first = recorder.record_agent_turn("duplicate-safe", idempotency_key="evt-duplicate-1")
        second = recorder.record_agent_turn("duplicate-safe", idempotency_key="evt-duplicate-1")

        assert len(sink.turns) == 1
        assert sink.turns[0].turn_index == 0
        assert sink.turns[0].text == "duplicate-safe"
        assert first.turn_index == second.turn_index == 0
    finally:
        remove_repo_paths(*inserted_paths)
