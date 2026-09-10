from __future__ import annotations
import asyncio
import subprocess
from dataclasses import dataclass
from netmon.config import PORT_LABELS


@dataclass(frozen=True)
class PortInfo:
    port: int
    pid: str
    cmd: str
    name: str


@dataclass
class PortDiff:
    snapshot: list[PortInfo]
    added: list[PortInfo]
    removed: list[int]


class PortScanner:
    def __init__(self) -> None:
        self._previous: dict[int, PortInfo] = {}
        self._initialized = False

    async def scan(self, preset: str = "All") -> PortDiff:
        raw = await asyncio.to_thread(_run_lsof)
        current = _parse_lsof(raw, preset)
        current_map = {p.port: p for p in current}

        if not self._initialized:
            self._previous = current_map
            self._initialized = True
            return PortDiff(snapshot=current, added=[], removed=[])

        added = [p for port, p in current_map.items() if port not in self._previous]
        removed = [port for port in self._previous if port not in current_map]
        self._previous = current_map
        return PortDiff(snapshot=current, added=added, removed=removed)

    def reset(self) -> None:
        self._previous = {}
        self._initialized = False

    @property
    def current(self) -> dict[int, PortInfo]:
        return self._previous


def _run_lsof() -> str:
    try:
        result = subprocess.run(
            ["lsof", "-i", "-P", "-n"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout
    except Exception:
        return ""


def _parse_lsof(output: str, preset: str) -> list[PortInfo]:
    seen: dict[int, PortInfo] = {}
    for line in output.splitlines():
        if "LISTEN" not in line:
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        cmd = parts[0]
        pid = parts[1]
        addr = parts[8]
        try:
            port = int(addr.rsplit(":", 1)[-1])
        except ValueError:
            continue
        if not _in_preset(port, preset):
            continue
        if port not in seen:
            name = PORT_LABELS.get(port, "")
            seen[port] = PortInfo(port=port, pid=pid, cmd=cmd, name=name)
    return sorted(seen.values(), key=lambda p: p.port)


def _in_preset(port: int, preset: str) -> bool:
    if preset == "All":
        return True
    if preset == "4xx":
        return 4000 <= port <= 4999
    if preset == "8xx":
        return 8000 <= port <= 8999
    return True
