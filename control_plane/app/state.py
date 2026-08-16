import datetime as _dt
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml


class FileStateStore:
    def __init__(self, workers_file: Path):
        self.workers_file = workers_file
        self._lock = threading.RLock()

    @contextmanager
    def locked(self):
        with self._lock:
            yield

    def load_workers(self) -> dict[str, Any]:
        data = _load_yaml(self.workers_file, {"workers": {}})
        workers = data.get("workers")
        if workers is None:
            data["workers"] = {}
        if not isinstance(data["workers"], dict):
            raise ValueError(f"invalid workers file: {self.workers_file}")
        return data

    def save_workers(self, data: dict[str, Any]) -> None:
        if "workers" not in data:
            data["workers"] = {}
        _atomic_write_text(self.workers_file, yaml.safe_dump(data, sort_keys=True, allow_unicode=False))


class DeviceStore:
    """设备台账存储（devices.yml）：原子写 + 线程锁，模式同 FileStateStore。
    绑定关系唯一权威（bound_worker_id），worker 侧只投影不存储。"""

    def __init__(self, devices_file: Path):
        self.devices_file = devices_file
        self._lock = threading.RLock()

    @contextmanager
    def locked(self):
        with self._lock:
            yield

    def load(self) -> dict[str, Any]:
        data = _load_yaml(self.devices_file, {"devices": {}})
        devices = data.get("devices")
        if devices is None:
            data["devices"] = {}
        if not isinstance(data["devices"], dict):
            raise ValueError(f"invalid devices file: {self.devices_file}")
        return data

    def save(self, data: dict[str, Any]) -> None:
        if "devices" not in data:
            data["devices"] = {}
        _atomic_write_text(self.devices_file, yaml.safe_dump(data, sort_keys=True, allow_unicode=False))


class RuntimeSettings:
    """运行时设置（布尔开关）：文件存在则覆盖环境变量默认值（进程内立即生效、重启保留），
    文件不存在时回退环境变量默认。
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    @contextmanager
    def locked(self):
        with self._lock:
            yield

    def get(self, key: str, default: bool) -> bool:
        data = _load_yaml(self.path, {})
        if key in data:
            return bool(data[key])
        return default

    def set(self, key: str, value: bool) -> bool:
        with self._lock:
            data = _load_yaml(self.path, {})
            data[key] = bool(value)
            _atomic_write_text(self.path, yaml.safe_dump(data, sort_keys=True))
            return bool(value)


class OperationLog:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._next_id = 0
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                self._next_id = sum(1 for line in f if line.strip())

    def record(self, op: str, status: str, **extra: Any) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            entry = {
                "id": self._next_id,
                # 跟随容器时区（/etc/localtime 挂载或 TZ 环境变量），输出带偏移的本地时间
                "ts": _dt.datetime.now().astimezone().isoformat(),
                "op": op,
                "status": status,
            }
            entry.update(extra)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry

    def read(self, since: int = 0, limit: int = 1000) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("id", 0) > since:
                        entries.append(entry)
                        if len(entries) >= limit:
                            break
        return {"next_cursor": entries[-1]["id"] if entries else since, "entries": entries}


def _load_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return dict(default)
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"expected YAML mapping in {path}")
    return loaded


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

