"""证书自动生成（T5 引导链）：幂等、指纹格式、SAN 解析与证书内容。"""

import hashlib
import ipaddress
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from control_plane.app.cert_bootstrap import DEFAULT_CN, ensure_server_cert, parse_san


def _load_cert(cert_dir: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate((cert_dir / "server.crt").read_bytes())


def test_ensure_server_cert_generates_files_and_fingerprint(tmp_path: Path):
    fp = ensure_server_cert(tmp_path)
    assert fp and len(fp) == 64
    assert int(fp, 16) >= 0
    cert = _load_cert(tmp_path)
    # 指纹 = DER SHA-256（与 openssl x509 -outform DER | sha256sum 一致）
    assert fp == hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    assert (tmp_path / "fingerprint.txt").read_text().split()[0] == fp
    # 私钥 PEM + 0600 权限（POSIX 语义；Windows 上 os.chmod 权限位不生效，跳过）
    key = serialization.load_pem_private_key((tmp_path / "server.key").read_bytes(), password=None)
    assert key.key_size == 2048
    if sys.platform != "win32":
        assert os.stat(tmp_path / "server.key").st_mode & 0o777 == 0o600


def test_ensure_server_cert_idempotent(tmp_path: Path):
    assert ensure_server_cert(tmp_path) is not None
    crt_before = (tmp_path / "server.crt").read_bytes()
    key_before = (tmp_path / "server.key").read_bytes()
    # 已存在 → 跳过不覆盖（轮换 = 删除目录后重启）
    assert ensure_server_cert(tmp_path) is None
    assert (tmp_path / "server.crt").read_bytes() == crt_before
    assert (tmp_path / "server.key").read_bytes() == key_before


def test_ensure_server_cert_subject_and_san(tmp_path: Path):
    ensure_server_cert(tmp_path, san_spec="IP:192.168.80.3,DNS:localhost")
    cert = _load_cert(tmp_path)
    assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == DEFAULT_CN
    assert cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address("192.168.80.3")]
    assert san.get_values_for_type(x509.DNSName) == ["localhost"]


def test_parse_san_skips_invalid_entries():
    names = parse_san("IP:127.0.0.1, DNS:localhost, IP:not-an-ip, bogus, ")
    assert [type(n).__name__ for n in names] == ["IPAddress", "DNSName"]
    assert names[0].value == ipaddress.ip_address("127.0.0.1")
    assert names[1].value == "localhost"
