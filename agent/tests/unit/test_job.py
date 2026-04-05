from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

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
            or name in {"agent_job_module", "livekit"}
        ):
            sys.modules.pop(name, None)


class FakePublication:
    sid = "PUB_123"


class FakeLocalParticipant:
    def __init__(self) -> None:
        self.identity = "agent-local"
        self.attributes = {}
        self.unpublished_sid = None

    async def publish_track(self, track):
        self.track = track
        return FakePublication()

    async def unpublish_track(self, sid: str) -> None:
        self.unpublished_sid = sid

    async def set_attributes(self, attributes):
        self.attributes = dict(attributes)


class FakeRoom:
    def __init__(self) -> None:
        self.local_participant = FakeLocalParticipant()
        self.handlers = {}

    def on(self, event: str, callback) -> None:
        self.handlers[event] = callback

    def emit(self, event: str, *args) -> None:
        callback = self.handlers.get(event)
        if callback is not None:
            callback(*args)


class FakeAudioSource:
    room = None
    instances = []

    def __init__(self, sample_rate: int, num_channels: int, queue_size_ms: int = 0) -> None:
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.queue_size_ms = queue_size_ms
        self.frames = []
        self.cleared = False
        self.waited = False
        FakeAudioSource.instances.append(self)

    async def capture_frame(self, frame) -> None:
        self.frames.append(frame)
        if len(self.frames) == 1 and FakeAudioSource.room is not None:
            FakeAudioSource.room.emit(
                "active_speakers_changed",
                [SimpleNamespace(identity="sip-caller-1")],
            )

    async def wait_for_playout(self) -> None:
        self.waited = True

    def clear_queue(self) -> None:
        self.cleared = True

    async def aclose(self) -> None:
        return None


class FakeLocalAudioTrack:
    @classmethod
    def create_audio_track(cls, name: str, source: FakeAudioSource):
        return SimpleNamespace(name=name, source=source)


class FakeAudioFrame:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_greeting_audio_interrupts_on_remote_active_speaker() -> None:
    inserted_paths = add_repo_paths()

    try:
        livekit_module = ModuleType("livekit")
        livekit_module.rtc = SimpleNamespace(
            AudioSource=FakeAudioSource,
            LocalAudioTrack=FakeLocalAudioTrack,
            AudioFrame=FakeAudioFrame,
        )
        sys.modules["livekit"] = livekit_module

        job = load_module("agent_job_module", "app/job.py")
        from app.pipeline.interruption import InterruptionCoordinator

        room = FakeRoom()
        FakeAudioSource.room = room
        FakeAudioSource.instances.clear()
        ctx = SimpleNamespace(room=room)
        settings = SimpleNamespace(worker_name="cozmo-agent-1")

        with pytest.raises(job.GreetingPlaybackInterrupted, match="caller_speech"):
            await job._publish_greeting_audio(
                ctx,
                settings=settings,
                agent_name="Main Reception",
                agent_config_id="main-inbound",
                coordinator=InterruptionCoordinator(),
            )

        assert FakeAudioSource.instances[0].cleared is True
        assert FakeAudioSource.instances[0].waited is False
        assert room.local_participant.attributes["cozmo.greeting_state"] == "interrupted"
        assert room.local_participant.attributes["cozmo.greeting_interruption_reason"] == "caller_speech"
        assert room.local_participant.unpublished_sid == "PUB_123"
    finally:
        FakeAudioSource.room = None
        remove_repo_paths(*inserted_paths)
