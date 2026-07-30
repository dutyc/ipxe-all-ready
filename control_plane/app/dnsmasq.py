import re
from dataclasses import dataclass
from pathlib import Path

import docker

from .state import _atomic_write_text


MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


@dataclass(frozen=True)
class HostBinding:
    mac: str
    hostname: str


class DnsmasqHosts:
    def __init__(self, hosts_file: Path, container_name: str, reload_enabled: bool = True):
        self.hosts_file = hosts_file
        self.container_name = container_name
        self.reload_enabled = reload_enabled

    def list_bindings(self) -> list[HostBinding]:
        return [_parse_binding(line) for line in self._read_lines() if _parse_binding(line) is not None]

    def find_mac(self, hostname: str) -> str | None:
        for binding in self.list_bindings():
            if binding.hostname == hostname:
                return binding.mac
        return None

    def ensure_free(self, mac: str, hostname: str) -> None:
        mac = normalize_mac(mac)
        for binding in self.list_bindings():
            if binding.mac == mac:
                raise ValueError(f"mac already bound: {mac}")
            if binding.hostname == hostname:
                raise ValueError(f"hostname already bound in dnsmasq: {hostname}")

    def add_binding(self, mac: str, hostname: str) -> None:
        mac = normalize_mac(mac)
        self.ensure_free(mac, hostname)
        lines = self._read_lines()
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{mac},{hostname}")
        self._write_lines(lines)

    def remove_hostname(self, hostname: str) -> bool:
        lines = self._read_lines()
        kept: list[str] = []
        removed = False
        for line in lines:
            binding = _parse_binding(line)
            if binding and binding.hostname == hostname:
                removed = True
                continue
            kept.append(line)
        if removed:
            self._write_lines(kept)
        return removed

    def reload(self) -> dict[str, str]:
        if not self.reload_enabled:
            return {"status": "skipped", "reason": "disabled"}
        try:
            client = docker.from_env()
            container = client.containers.get(self.container_name)
            result = container.exec_run(["killall", "-HUP", "dnsmasq"])
        except docker.errors.NotFound as exc:
            raise RuntimeError(f"dnsmasq container not found: {self.container_name}") from exc
        except docker.errors.DockerException as exc:
            raise RuntimeError(f"docker error while reloading dnsmasq: {exc}") from exc
        output = result.output.decode(errors="replace") if result.output else ""
        if result.exit_code != 0:
            raise RuntimeError(f"dnsmasq reload failed rc={result.exit_code}: {output.strip()}")
        return {"status": "ok"}

    def _read_lines(self) -> list[str]:
        self.hosts_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.hosts_file.exists():
            return []
        return self.hosts_file.read_text(encoding="utf-8").splitlines()

    def _write_lines(self, lines: list[str]) -> None:
        text = "\n".join(lines).rstrip() + "\n" if lines else ""
        _atomic_write_text(self.hosts_file, text)


def normalize_mac(mac: str) -> str:
    normalized = mac.strip().lower()
    if not MAC_RE.match(normalized):
        raise ValueError(f"invalid mac address: {mac}")
    return normalized


def _parse_binding(line: str) -> HostBinding | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = [part.strip() for part in stripped.split(",")]
    if len(parts) < 2:
        return None
    mac = parts[0].lower()
    hostname = parts[1]
    if not MAC_RE.match(mac) or not hostname:
        return None
    return HostBinding(mac=mac, hostname=hostname)

