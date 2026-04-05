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
            or name.startswith("agent_call_state_")
        ):
            sys.modules.pop(name, None)


class FakeCollection:
    def __init__(self, document):
        self.document = dict(document)

    def find_one(self, query, projection=None):
        if query.get("room_name") != self.document.get("room_name"):
            return None
        if projection is None:
            return dict(self.document)
        return {
            key: value
            for key, value in self.document.items()
            if key in projection or projection.get(key)
        }

    def update_one(self, query, update):
        if query.get("room_name") != self.document.get("room_name"):
            return None
        self.document.update(update.get("$set", {}))
        return None


@pytest.mark.unit
def test_mark_active_sets_status_and_connected_at_when_missing() -> None:
    inserted_paths = add_repo_paths()

    try:
        call_state = load_module("agent_call_state_module", "app/call_state.py")

        collection = FakeCollection(
            {
                "room_name": "call-+16625640501-a1b2",
                "status": "created",
                "connected_at": None,
            }
        )
        repository = call_state.MongoCallStateRepository(collection)

        stored = repository.mark_active("call-+16625640501-a1b2")

        assert stored["status"] == "active"
        assert stored["connected_at"] is not None
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_mark_active_preserves_existing_connected_at() -> None:
    inserted_paths = add_repo_paths()

    try:
        call_state = load_module("agent_call_state_existing_connected", "app/call_state.py")

        existing_connected_at = datetime(2026, 4, 5, 10, 0, tzinfo=UTC)
        collection = FakeCollection(
            {
                "room_name": "call-+16625640501-a1b2",
                "status": "created",
                "connected_at": existing_connected_at,
            }
        )
        repository = call_state.MongoCallStateRepository(collection)

        stored = repository.mark_active(
            "call-+16625640501-a1b2",
            connected_at=datetime(2026, 4, 5, 11, 0, tzinfo=UTC),
        )

        assert stored["status"] == "active"
        assert stored["connected_at"] == existing_connected_at
    finally:
        remove_repo_paths(*inserted_paths)
