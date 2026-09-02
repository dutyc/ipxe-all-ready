"""TOFU 引导链服务器证书引导：控制面启动时幂等生成自签证书（nginx 443 使用）。

证书生命周期归控制面（2026-08-22 裁定：自动生成，gen-cert.sh 废止）：
- 首次启动生成 RSA-2048 自签叶证书（CA=False），已存在即跳过（轮换 = 删 state/certs/ 后重启控制面）
- SAN 来自 spec.serverCert.san（逗号分隔 IP:/DNS: 条目）；TOFU pin 叶证书指纹，SAN 不参与设备侧校验
- 指纹输出 state/certs/fingerprint.txt：DER SHA-256 hex（与 openssl x509 -outform DER | sha256sum 一致）
"""

import datetime as _dt
import hashlib
import ipaddress
import logging
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

log = logging.getLogger("control-plane")

# 与 nginx 443 配置（/etc/nginx/certs/server.crt|key）一致
CERT_FILENAME = "server.crt"
KEY_FILENAME = "server.key"
FINGERPRINT_FILENAME = "fingerprint.txt"
DEFAULT_CN = "kurrent-controller"


def parse_san(san_spec: str) -> list[x509.GeneralName]:
    """解析 spec.serverCert.san：逗号分隔的 IP:/DNS: 条目，非法条目忽略并告警。"""
    names: list[x509.GeneralName] = []
    for raw in (part.strip() for part in san_spec.split(",")):
        if not raw:
            continue
        kind, _, value = raw.partition(":")
        value = value.strip()
        if kind == "IP":
            try:
                names.append(x509.IPAddress(ipaddress.ip_address(value)))
            except ValueError:
                log.warning("cert: ignoring invalid SAN IP %r", value)
        elif kind == "DNS" and value:
            names.append(x509.DNSName(value))
        else:
            log.warning("cert: ignoring invalid SAN entry %r", raw)
    return names


def ensure_server_cert(
    cert_dir: Path,
    san_spec: str = "IP:127.0.0.1,DNS:localhost",
    days: int = 3650,
) -> str | None:
    """幂等生成自签服务器证书。返回叶证书指纹（DER SHA-256 hex）；证书已存在返回 None。"""
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / CERT_FILENAME
    key_path = cert_dir / KEY_FILENAME
    if cert_path.exists() and key_path.exists():
        return None

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, DEFAULT_CN)])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(parse_san(san_spec)), critical=False)
        .sign(private_key=key, algorithm=hashes.SHA256())
    )
    # 私钥 0600：仅属主可读写（与 openssl genrsa 权限一致）
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    (cert_dir / FINGERPRINT_FILENAME).write_text(f"{fingerprint}  {CERT_FILENAME}\n")
    log.info("cert: generated self-signed server certificate, fingerprint=%s", fingerprint)
    return fingerprint
