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
            or name == "agent_rejoin_recovery"
        ):
            sys.modules.pop(name, None)


class FakeRecoveryLeaseSink:
    def __init__(self) -> None:
        self.claimed = set()

    def claim_recovery(self, room_name: str) -> bool:
        if room_name in self.claimed:
            return False
        self.claimed.add(room_name)
        return True


class FakeTranscriptHistorySource:
    def __init__(self, turns) -> None:
        self.turns = turns

    def list_by_room_name(self, room_name: str):
        return list(self.turns)


@pytest.mark.unit
def test_rejoin_coordinator_marks_room_recoverable_only_once() -> None:
    inserted_paths = add_repo_paths()

    try:
        recovery = load_module("agent_rejoin_recovery", "app/recovery/rejoin.py")
        from cozmo_contracts.models import TranscriptTurn, TurnSpeaker

        history = [
            TranscriptTurn(
                room_name="call-+16625640501-a1b2",
                turn_index=0,
                speaker=TurnSpeaker.USER,
                text="Hello",
                timestamp=datetime(2026, 4, 5, tzinfo=UTC),
            ),
            TranscriptTurn(
                room_name="call-+16625640501-a1b2",
                turn_index=1,
                speaker=TurnSpeaker.AGENT,
                text="Hi, how can I help?",
                timestamp=datetime(2026, 4, 5, tzinfo=UTC),
                interrupted=True,
            ),
        ]
        coordinator = recovery.RejoinCoordinator(
            lease_sink=FakeRecoveryLeaseSink(),
            transcript_source=FakeTranscriptHistorySource(history),
        )

        first = coordinator.plan_replacement("call-+16625640501-a1b2")
        second = coordinator.plan_replacement("call-+16625640501-a1b2")

        assert first.should_dispatch_replacement is True
        assert first.recovery_prompt is not None
        assert "Caller: Hello" in first.recovery_prompt
        assert "Agent: Hi, how can I help? [interrupted]" in first.recovery_prompt
        assert second.should_dispatch_replacement is False
    finally:
        remove_repo_paths(*inserted_paths)
