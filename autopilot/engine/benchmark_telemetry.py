"""Low-dependency host and process telemetry for Blender diagnostics.

This module is shared by the normal Python runner and Blender's embedded Python.
It deliberately records only an allowlist of non-secret environment variables.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

_ENV_ALLOWLIST = (
    "EGL_PLATFORM",
    "LIBGL_ALWAYS_SOFTWARE",
    "MESA_LOADER_DRIVER_OVERRIDE",
    "GALLIUM_DRIVER",
    "LP_NUM_THREADS",
    "OMP_NUM_THREADS",
    "BLAS_NUM_THREADS",
    "BLENDER_RENDER_WORKERS",
    "BLENDER_THREADS_PER_WORKER",
    "BLENDER_RENDER_WIDTH",
    "BLENDER_RENDER_HEIGHT",
    "BLENDER_RENDER_FPS",
    "BLENDER_RENDER_SAMPLES",
    "BLENDER_RENDER_TIMEOUT_SECONDS",
    "BLENDER_RENDER_PREFLIGHT_ENABLED",
    "BENCH_MAX_FRAMES",
    "BENCH_EGL_MODE",
)


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write valid JSON atomically so an interrupted render leaves the last report intact."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return destination


def _read_text(path: str | Path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _command_output(command: list[str]) -> str | None:
    if not shutil.which(command[0]):
        return None
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr or "").strip()
    return output[:16000] if output else None


def _parse_meminfo() -> dict[str, str]:
    values: dict[str, str] = {}
    raw = _read_text("/proc/meminfo") or ""
    for line in raw.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def _cgroup_diagnostics() -> dict[str, Any]:
    values: dict[str, Any] = {}
    cpu_max = _read_text("/sys/fs/cgroup/cpu.max")
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) == 2:
            try:
                quota = None if parts[0] == "max" else int(parts[0])
                period = int(parts[1])
                values["cpu_max_raw"] = cpu_max
                values["cpu_quota_cores"] = (
                    round(quota / period, 3) if quota is not None and period > 0 else None
                )
            except ValueError:
                values["cpu_max_raw"] = cpu_max
    memory_max = _read_text("/sys/fs/cgroup/memory.max")
    if memory_max:
        values["memory_max_bytes"] = (
            None if memory_max == "max" else memory_max
        )
    memory_current = _read_text("/sys/fs/cgroup/memory.current")
    if memory_current:
        values["memory_current_bytes"] = memory_current

    # Keep v1 details as well, since self-hosted and older Linux runners may use them.
    for key, candidate in (
        ("cpu_quota_v1", "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"),
        ("cpu_period_v1", "/sys/fs/cgroup/cpu/cpu.cfs_period_us"),
        ("memory_limit_v1", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
        ("memory_usage_v1", "/sys/fs/cgroup/memory/memory.usage_in_bytes"),
    ):
        value = _read_text(candidate)
        if value:
            values[key] = value
    return values


def capture_host_diagnostics(output_path: str | Path) -> dict[str, Any]:
    """Capture CPU, memory, runner, cgroup and renderer-related environment facts."""
    affinity = None
    if hasattr(os, "sched_getaffinity"):
        try:
            affinity = sorted(os.sched_getaffinity(0))
        except OSError:
            pass

    lscpu = _command_output(["lscpu"])
    nproc = _command_output(["nproc"])
    nproc_all = _command_output(["nproc", "--all"])
    meminfo = _parse_meminfo()
    environment = {
        key: os.environ.get(key)
        for key in _ENV_ALLOWLIST
        if key in os.environ
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "hardware": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "cpu_count_os": os.cpu_count(),
            "cpu_affinity": affinity,
            "nproc_visible": nproc,
            "nproc_all": nproc_all,
            "lscpu": lscpu,
            "memory_total": meminfo.get("MemTotal"),
            "memory_available": meminfo.get("MemAvailable"),
            "memory_free": meminfo.get("MemFree"),
            "swap_total": meminfo.get("SwapTotal"),
            "swap_free": meminfo.get("SwapFree"),
            "cgroup": _cgroup_diagnostics(),
        },
        "runner": {
            key: os.environ.get(key)
            for key in (
                "RUNNER_OS",
                "RUNNER_ARCH",
                "RUNNER_NAME",
                "ImageOS",
                "ImageVersion",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_WORKFLOW",
                "GITHUB_REF",
            )
            if os.environ.get(key) is not None
        },
        "environment": environment,
    }
    write_json_atomic(output_path, payload)
    return payload


def process_snapshot() -> dict[str, Any]:
    """Return current Blender process CPU time, resident memory and thread count."""
    result: dict[str, Any] = {
        "pid": os.getpid(),
        "cpu_count_os": os.cpu_count(),
    }
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        result["cpu_user_seconds"] = round(float(usage.ru_utime), 6)
        result["cpu_system_seconds"] = round(float(usage.ru_stime), 6)
        result["peak_rss_kib"] = int(usage.ru_maxrss)
    except (ImportError, OSError, ValueError):
        pass

    status = _read_text(f"/proc/{os.getpid()}/status") or ""
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            result["rss"] = line.split(":", 1)[1].strip()
        elif line.startswith("VmHWM:"):
            result["peak_rss"] = line.split(":", 1)[1].strip()
        elif line.startswith("Threads:"):
            try:
                result["threads"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return result
