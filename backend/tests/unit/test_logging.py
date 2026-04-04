from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import logging

import pytest


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[2] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_configure_logging_clamps_pymongo_noise() -> None:
    logging_module = load_module("backend_logging", "app/middleware/logging.py")

    logging_module.configure_logging("development", "DEBUG")

    assert logging.getLogger("pymongo.topology").level == logging.WARNING
    assert logging.getLogger("pymongo.connection").level == logging.WARNING


@pytest.mark.unit
def test_resolve_log_level_prefers_configured_level() -> None:
    logging_module = load_module("backend_logging", "app/middleware/logging.py")

    assert logging_module.resolve_log_level("development", "INFO") == logging.INFO
