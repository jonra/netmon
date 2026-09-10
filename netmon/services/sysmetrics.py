from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CpuSnapshot:
    user: float
    system: float
    idle: float


@dataclass(frozen=True)
class MemSnapshot:
    physical: int
    used: int
    cached: int
    swap_used: int
    app: int
    wired: int
    compressed: int
    pressure: float  # 0–100, higher = more pressure


def collect_cpu() -> CpuSnapshot | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.check_output(
            ["top", "-l", "1", "-n", "0"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    match = re.search(
        r"CPU usage:\s*([\d.]+)%\s*user,\s*([\d.]+)%\s*sys,\s*([\d.]+)%\s*idle",
        out,
    )
    if not match:
        return None
    user, system, idle = (float(match.group(i)) for i in range(1, 4))
    return CpuSnapshot(user=user, system=system, idle=idle)


def collect_memory() -> MemSnapshot | None:
    if sys.platform != "darwin":
        return None
    try:
        page_size = int(_sysctl("hw.pagesize"))
        physical = int(_sysctl("hw.memsize"))
        pages = _parse_vm_stat()
        swap_used = _parse_swap_used()
        pressure = _parse_memory_pressure()
    except (subprocess.SubprocessError, OSError, ValueError):
        return None

    def pages_to_bytes(key: str) -> int:
        return pages.get(key, 0) * page_size

    wired = pages_to_bytes("Pages wired down")
    compressed = pages_to_bytes("Pages occupied by compressor")
    active = pages_to_bytes("Pages active")
    inactive = pages_to_bytes("Pages inactive")
    purgeable = pages_to_bytes("Pages purgeable")
    file_backed = pages_to_bytes("File-backed pages")
    anonymous = pages_to_bytes("Anonymous pages")

    used = active + inactive + wired + compressed
    cached = purgeable + file_backed
    app = max(anonymous - compressed, 0)

    return MemSnapshot(
        physical=physical,
        used=used,
        cached=cached,
        swap_used=swap_used,
        app=app,
        wired=wired,
        compressed=compressed,
        pressure=pressure,
    )


def _sysctl(name: str) -> str:
    return subprocess.check_output(["sysctl", "-n", name], text=True).strip()


def _parse_vm_stat() -> dict[str, int]:
    out = subprocess.check_output(["vm_stat"], text=True)
    pages: dict[str, int] = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        val = rest.strip().rstrip(".")
        if not val.isdigit():
            continue
        pages[key.strip()] = int(val)
    return pages


def _parse_swap_used() -> int:
    out = subprocess.check_output(["sysctl", "vm.swapusage"], text=True)
    match = re.search(r"used\s*=\s*([\d.]+)M", out)
    if not match:
        return 0
    return int(float(match.group(1)) * 1024 * 1024)


def _parse_memory_pressure() -> float:
    try:
        out = subprocess.check_output(
            ["memory_pressure"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1,
        )
    except (subprocess.SubprocessError, OSError):
        return 0.0
    match = re.search(
        r"System-wide memory free percentage:\s*(\d+)%",
        out,
    )
    if not match:
        return 0.0
    free_pct = float(match.group(1))
    return max(0.0, min(100.0, 100.0 - free_pct))


def format_bytes(n: int) -> str:
    """Compact size like Activity Monitor (e.g. 19,82 GB)."""
    if n >= 1024**3:
        gb = n / (1024**3)
        return f"{gb:,.2f} GB".replace(".", ",")
    if n >= 1024**2:
        mb = n / (1024**2)
        return f"{mb:,.0f} MB".replace(",", ".")
    return f"{n:,} B"
