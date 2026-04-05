"""Worker server entrypoint for the Cozmo voice agent."""

import os
from pathlib import Path
import shutil


def _prepare_prometheus_multiprocess_dir() -> None:
    """Configure a shared Prometheus multiprocess directory before worker imports."""

    directory = Path(
        os.environ.get("COZMO_AGENT_PROMETHEUS_MULTIPROC_DIR", "/tmp/cozmo-agent-prometheus")
    )
    os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", str(directory))
    ready_flag = "COZMO_AGENT_PROMETHEUS_MULTIPROC_READY"
    if os.environ.get(ready_flag) != "1":
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[ready_flag] = "1"
    else:
        directory.mkdir(parents=True, exist_ok=True)


_prepare_prometheus_multiprocess_dir()

from app.job import run_worker


def main() -> None:
    run_worker()


if __name__ == "__main__":
    main()
