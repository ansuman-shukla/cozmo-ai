from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

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
            or name == "agent_transcripts"
        ):
            sys.modules.pop(name, None)


class FakeTranscriptSink:
    def __init__(self, *, next_turn_index: int = 0) -> None:
        self.next_turn_index_value = next_turn_index
        self.turns = []

    def append_transcript_turn(self, turn):
        self.turns.append(turn)
        return turn

    def next_turn_index(self, room_name: str) -> int:
        return self.next_turn_index_value

    def mark_transcript_turn_interrupted(self, room_name: str, turn_index: int):
        for turn in self.turns:
            if turn.room_name == room_name and turn.turn_index == turn_index:
                turn.interrupted = True
                return turn
        return None


class FlakyTranscriptSink(FakeTranscriptSink):
    def __init__(self, *, failures_before_success: int) -> None:
        super().__init__()
        self.failures_before_success = failures_before_success
        self.append_attempts = 0

    def append_transcript_turn(self, turn):
        self.append_attempts += 1
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise RuntimeError("temporary mongo failure")
        return super().append_transcript_turn(turn)


class FakeDeadLetterSink:
    def __init__(self) -> None:
        self.entries = []

    def enqueue_failed_turn(self, entry):
        self.entries.append(entry)
        return entry


@pytest.mark.unit
def test_transcript_recorder_stores_turns_in_order() -> None:
    inserted_paths = add_repo_paths()

    try:
        transcripts = load_module("agent_transcripts", "app/transcripts.py")

        sink = FakeTranscriptSink(next_turn_index=3)
        recorder = transcripts.TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=sink,
        )

        first = recorder.record_user_turn("  Hello there  ")
        second = recorder.record_agent_turn(
            "I can help with that.",
            timestamp=datetime(2026, 4, 5, tzinfo=UTC),
        )

        assert [turn.turn_index for turn in sink.turns] == [3, 4]
        assert first.text == "Hello there"
        assert second.text == "I can help with that."
        assert second.turn_index == 4
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_transcript_recorder_rejects_empty_text() -> None:
    inserted_paths = add_repo_paths()

    try:
        transcripts = load_module("agent_transcripts", "app/transcripts.py")

        recorder = transcripts.TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=FakeTranscriptSink(),
        )

        with pytest.raises(ValueError, match="non-empty"):
            recorder.record_agent_turn("   ")
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_transcript_recorder_marks_last_agent_turn_interrupted() -> None:
    inserted_paths = add_repo_paths()

    try:
        transcripts = load_module("agent_transcripts", "app/transcripts.py")

        sink = FakeTranscriptSink()
        recorder = transcripts.TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=sink,
        )
        recorder.record_user_turn("Hello")
        recorder.record_agent_turn("Hi, how can I help?")

        updated = recorder.mark_last_agent_turn_interrupted()

        assert updated is not None
        assert updated.interrupted is True
        assert sink.turns[0].interrupted is False
        assert sink.turns[1].interrupted is True
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_transcript_recorder_retries_transient_write_failure() -> None:
    inserted_paths = add_repo_paths()

    try:
        transcripts = load_module("agent_transcripts", "app/transcripts.py")

        sink = FlakyTranscriptSink(failures_before_success=1)
        recorder = transcripts.TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=sink,
            max_retries=1,
        )

        stored = recorder.record_user_turn("Please retry this write.")

        assert stored.turn_index == 0
        assert sink.append_attempts == 2
        assert len(sink.turns) == 1
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_transcript_recorder_enqueues_failed_write_for_replay() -> None:
    inserted_paths = add_repo_paths()

    try:
        transcripts = load_module("agent_transcripts", "app/transcripts.py")

        sink = FlakyTranscriptSink(failures_before_success=5)
        dlq = FakeDeadLetterSink()
        recorder = transcripts.TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=sink,
            max_retries=1,
            dead_letter_sink=dlq,
        )

        stored = recorder.record_agent_turn("This write will dead-letter.")

        assert stored.turn_index == 0
        assert len(sink.turns) == 0
        assert len(dlq.entries) == 1
        assert dlq.entries[0].room_name == "call-+16625640501-a1b2"
        assert dlq.entries[0].attempts == 2
        assert dlq.entries[0].payload["text"] == "This write will dead-letter."
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_transcript_recorder_idempotency_key_suppresses_duplicate_side_effects() -> None:
    inserted_paths = add_repo_paths()

    try:
        transcripts = load_module("agent_transcripts", "app/transcripts.py")

        sink = FakeTranscriptSink()
        recorder = transcripts.TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=sink,
        )

        first = recorder.record_user_turn("hello", idempotency_key="evt-1")
        second = recorder.record_user_turn("hello", idempotency_key="evt-1")

        assert len(sink.turns) == 1
        assert first.turn_index == second.turn_index == 0
    finally:
        remove_repo_paths(*inserted_paths)
