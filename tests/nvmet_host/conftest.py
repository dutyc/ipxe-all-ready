"""nvmet-host 宿主服务单测夹具：env 隔离 + importlib 加载。

NVMET_CONFIGFS 重定向到临时目录（mock configfs），NVMET_HOST_TOKEN 固定测试值；
模块以独立名字 nvmet_host_main 加载，避免与 Agent 的 app 包名冲突。
"""

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_STATE = Path(tempfile.mkdtemp(prefix="nvmet-host-test-"))
os.environ["NVMET_HOST_TOKEN"] = "test-host-token"
os.environ["NVMET_HOST_ADDR"] = "127.0.0.1"
os.environ["NVMET_HOST_PORT"] = "4841"
os.environ["NVMET_CONFIGFS"] = str(_STATE / "configfs-nvmet")

_spec = importlib.util.spec_from_file_location(
    "nvmet_host_main", PROJECT_ROOT / "storager" / "nvmeof" / "nvmet-host" / "app" / "main.py")
main = importlib.util.module_from_spec(_spec)
sys.modules["nvmet_host_main"] = main
_spec.loader.exec_module(main)


@pytest.fixture()
def nvmet():
    """宿主服务模块（NvmetManager 指向 mock configfs 根）。"""
    return main


@pytest.fixture()
def configfs(nvmet):
    """mock configfs 根目录：每用例重建（清理上一用例残留）。"""
    root = Path(nvmet.CONFIGFS_NVMET)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


@pytest.fixture()
def client(nvmet):
    from fastapi.testclient import TestClient
    return TestClient(nvmet.app)


@pytest.fixture()
def auth_headers():
    return {"Authorization": "Bearer test-host-token"}


# Windows 无 SeCreateSymbolicLinkPrivilege（WinError 1314）：os.symlink 不可用。
# 兼容层：symlink → 占位文件 + 记录（records[link_path] = target）；islink 按记录判定；
# unlink 时同步清记录。main.py 的 islink 判断 / unlink 清理 / rmtree 均不受影响。
_symlink_records: dict = {}


@pytest.fixture(autouse=True)
def _symlink_compat(monkeypatch):
    real_unlink = os.unlink
    _symlink_records.clear()

    def fake_symlink(src, dst, target_is_directory=False):
        _symlink_records[str(dst)] = src
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8"):
            pass  # 占位文件：保证 unlink/rmtree 语义与真实 symlink 一致

    def fake_islink(path):
        return str(path) in _symlink_records

    def fake_unlink(path, *args, **kwargs):
        _symlink_records.pop(str(path), None)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "symlink", fake_symlink)
    monkeypatch.setattr(os.path, "islink", fake_islink)
    monkeypatch.setattr(os, "unlink", fake_unlink)


@pytest.fixture()
def symlinks():
    """symlink 兼容层记录：link 绝对路径 → target（测试断言挂载关系）。"""
    return _symlink_records
