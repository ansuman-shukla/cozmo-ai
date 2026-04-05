"""Worker-process system utilization sampling."""

from __future__ import annotations

from dataclasses import dataclass
import os
import resource
from threading import Event, Thread
from time import monotonic

from app.observability.metrics import (
    calculate_cpu_utilization_pct,
    calculate_memory_utilization_pct,
    record_worker_system_utilization,
)


def read_process_cpu_seconds() -> float:
    """Return total user+system CPU time consumed by the current process."""

    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


def read_process_rss_bytes() -> int:
    """Return current resident-set size for the current process on Linux."""

    with open("/proc/self/statm", encoding="utf-8") as handle:
        parts = handle.read().strip().split()
    if len(parts) < 2:
        return 0
    page_size = os.sysconf("SC_PAGE_SIZE")
    return int(parts[1]) * int(page_size)


def read_total_memory_bytes() -> int:
    """Return total physical memory available to the current host."""

    return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))


@dataclass(slots=True)
class WorkerSystemMonitor:
    """Background poller for worker-process CPU and memory utilization."""

    worker_name: str
    poll_interval_ms: int = 5000
    cpu_count: int = os.cpu_count() or 1
    total_memory_bytes: int = read_total_memory_bytes()

    def start_in_background(self) -> Thread:
        """Start the monitor in a daemon thread and return the thread handle."""

        stop_event = Event()
        thread = Thread(
            target=self._run_loop,
            args=(stop_event,),
            name=f"{self.worker_name}-system-metrics",
            daemon=True,
        )
        thread.start()
        return thread

    def sample_once(
        self,
        *,
        previous_cpu_seconds: float,
        previous_wall_time: float,
        current_cpu_seconds: float | None = None,
        current_wall_time: float | None = None,
        rss_bytes: int | None = None,
    ) -> tuple[float, float, float]:
        """Compute and publish one worker-utilization sample."""

        current_cpu_seconds = (
            read_process_cpu_seconds() if current_cpu_seconds is None else current_cpu_seconds
        )
        current_wall_time = monotonic() if current_wall_time is None else current_wall_time
        rss_bytes = read_process_rss_bytes() if rss_bytes is None else rss_bytes

        cpu_pct = calculate_cpu_utilization_pct(
            cpu_seconds_delta=current_cpu_seconds - previous_cpu_seconds,
            wall_seconds_delta=current_wall_time - previous_wall_time,
            cpu_count=self.cpu_count,
        )
        memory_pct = calculate_memory_utilization_pct(
            rss_bytes=rss_bytes,
            total_memory_bytes=self.total_memory_bytes,
        )
        record_worker_system_utilization(
            self.worker_name,
            cpu_utilization_pct=cpu_pct,
            memory_utilization_pct=memory_pct,
        )
        return current_cpu_seconds, current_wall_time, memory_pct

    def _run_loop(self, stop_event: Event) -> None:
        """Continuously sample process utilization until the process exits."""

        previous_cpu_seconds = read_process_cpu_seconds()
        previous_wall_time = monotonic()
        record_worker_system_utilization(
            self.worker_name,
            cpu_utilization_pct=0.0,
            memory_utilization_pct=calculate_memory_utilization_pct(
                rss_bytes=read_process_rss_bytes(),
                total_memory_bytes=self.total_memory_bytes,
            ),
        )
        while not stop_event.wait(self.poll_interval_ms / 1000.0):
            previous_cpu_seconds, previous_wall_time, _ = self.sample_once(
                previous_cpu_seconds=previous_cpu_seconds,
                previous_wall_time=previous_wall_time,
            )
