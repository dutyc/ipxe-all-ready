"""组件 PKI（K8S 同构认证体系，2026-08-31）：内部 CA + bootstrap token 引导 + 证书签发。

设计（对照 Kubernetes）：
- 控制面 = kube-apiserver + CA：幂等生成内部 CA（state/pki/ca.{key,crt}），
  为每个组件签发 client cert（身份，CN=<component>-<id>）与 serving cert（TLS 服务端）
- bootstrap token = 一次性引导凭据（仿 cluster-bootstrap 格式 <6位>.<16位>，
  登记只存 sha256 hash，绑定组件身份 + 过期时间；用后即废）
- 组件证书 TTL 90 天（CA 10 年）：轮换 = 组件在证书剩余 <20% 时重新提交 CSR
  （/renew，经 nginx mTLS 校验证书身份），控制面自动签发
- 吊销 = 证书到期自然失效 + 组件从注册表移除后拒绝 renew（不引入 CRL，MVP 够用）

CSR 校验规则（防冒名）：subject CN 必须与 bootstrap token 绑定的组件身份一致；
签名有效；公钥 RSA >= 2048。
"""

import datetime as _dt
import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from . import config

log = logging.getLogger("control-plane")

CA_FILENAME = "ca.crt"
CA_KEY_FILENAME = "ca.key"
TOKENS_FILENAME = "bootstrap-tokens.yml"
CA_DAYS = 3650
CA_CN = "kurrent-ca"
# 组件身份前缀：client cert 的 CN 约定 <prefix>-<id>，enroll/renew 时按组件类型校验
COMPONENT_PREFIX = {"agent": "agent", "nvmet-host": "nvmet", "control-plane": "control-plane"}


# ============================ CA ============================

def _load_key(path: Path):
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _load_cert(path: Path):
    return x509.load_pem_x509_certificate(path.read_bytes())


def ensure_ca(pki_dir: Path) -> tuple:
    """幂等生成内部 CA。返回 (cert, key)；已存在则加载（轮换 = 删 state/pki/ 重启）。"""
    pki_dir.mkdir(parents=True, exist_ok=True)
    cert_path = pki_dir / CA_FILENAME
    key_path = pki_dir / CA_KEY_FILENAME
    if cert_path.exists() and key_path.exists():
        return _load_cert(cert_path), _load_key(key_path)

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_CN)])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=False, content_commitment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(private_key=key, algorithm=hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("pki: generated internal CA (cn=%s, %d days)", CA_CN, CA_DAYS)
    return cert, key


def ca_cert_pem(pki_dir: Path) -> bytes:
    return (pki_dir / CA_FILENAME).read_bytes()


def ensure_control_plane_client_cert(pki_dir: Path, ca_cert, ca_key,
                                     component: str = "control-plane") -> tuple[Path, Path]:
    """幂等生成控制面自身 client cert（cp→agent 的 mTLS 客户端身份，CN=component）。

    存在且未过期即复用；过期则轮换（证书文件名固定，重启后以文件为准）。
    返回 (cert_path, key_path)。
    """
    cert_dir = pki_dir / "components" / component
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "client.crt"
    key_path = cert_dir / "client.key"
    if cert_path.exists() and key_path.exists():
        try:
            if _load_cert(cert_path).not_valid_after_utc > _dt.datetime.now(_dt.timezone.utc):
                return cert_path, key_path
            log.warning("pki: control-plane client cert expired, rotating")
        except ValueError:
            pass
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr_pem = _build_csr(key, component)
    cert = _sign_csr(ca_cert, ca_key, csr_pem, "clientAuth", [], config.COMPONENT_CERT_DAYS)
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert)
    log.info("pki: control-plane client cert ready: %s", cert_path)
    return cert_path, key_path


# ============================ CSR 校验 + 签发 ============================

def _build_csr(key, cn: str, sans: list[str] | None = None) -> bytes:
    """构建 CSR（agent 侧同逻辑，控制面仅测试/自签用）。"""
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    builder = x509.CertificateSigningRequestBuilder().subject_name(name)
    if sans:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(s) if ":" not in s else _ip_or_dns(s) for s in sans]
            ),
            critical=False,
        )
    return builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)


def _ip_or_dns(value: str):
    import ipaddress
    try:
        return x509.IPAddress(ipaddress.ip_address(value))
    except ValueError:
        return x509.DNSName(value)


def _parse_csr(csr_pem: bytes) -> x509.CertificateSigningRequest:
    csr = x509.load_pem_x509_csr(csr_pem)
    if not csr.is_signature_valid:
        raise ValueError("csr signature invalid")
    pub = csr.public_key()
    if isinstance(pub, rsa.RSAPublicKey) and pub.key_size < 2048:
        raise ValueError(f"csr rsa key too small: {pub.key_size}")
    return csr


def _csr_cn(csr: x509.CertificateSigningRequest) -> str:
    names = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return names[0].value if names else ""


def _sign_csr(ca_cert, ca_key, csr_pem: bytes, usage: str,
              sans: list[str] | None, days: int) -> bytes:
    """校验 CSR 并签发。usage = clientAuth | serverAuth。SAN 仅 serverAuth 使用。"""
    csr = _parse_csr(csr_pem)
    now = _dt.datetime.now(_dt.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True, content_commitment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.CLIENT_AUTH if usage == "clientAuth" else ExtendedKeyUsageOID.SERVER_AUTH]
            ),
            critical=False,
        )
    )
    if sans:
        builder = builder.add_extension(x509.SubjectAlternativeName([_ip_or_dns(s) for s in sans]), critical=False)
    cert = builder.sign(private_key=ca_key, algorithm=hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM)


def sign_component_certs(ca_cert, ca_key, agent_id: str, component: str,
                         client_csr: bytes, serving_csr: bytes,
                         serving_sans: list[str]) -> dict[str, bytes]:
    """为组件签发 client + serving 两张证书（agent 代 nvmet-host 的场景同入口）。

    CSR 的 CN 必须与登记身份一致（防冒名）：CN = <prefix>-<agent_id>。
    """
    prefix = COMPONENT_PREFIX.get(component)
    if not prefix:
        raise ValueError(f"unknown component: {component}")
    expected_cn = f"{prefix}-{agent_id}"
    for csr in (client_csr, serving_csr):
        if _csr_cn(_parse_csr(csr)) != expected_cn:
            raise ValueError(f"csr cn mismatch: expect {expected_cn}")
    client_cert = _sign_csr(ca_cert, ca_key, client_csr, "clientAuth", [], config.COMPONENT_CERT_DAYS)
    serving_cert = _sign_csr(ca_cert, ca_key, serving_csr, "serverAuth", serving_sans,
                             config.COMPONENT_CERT_DAYS)
    return {"client.crt": client_cert, "serving.crt": serving_cert}


def client_cert_cn(cert_pem: bytes) -> str:
    """从 PEM 客户端证书提取 CN（控制面校验 mTLS 客户端身份时用）。"""
    cert = x509.load_pem_x509_certificate(cert_pem)
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return names[0].value if names else ""


def parse_dn_cn(dn: str) -> str:
    """从 nginx 透传的客户端证书 DN（$ssl_client_s_dn，如 /C=CN/CN=agent-x）提取 CN。"""
    for part in dn.split("/"):
        key, _, value = part.partition("=")
        if key.strip() == "CN":
            return value.strip()
    return ""


# ============================ bootstrap token ============================

def _token_file(pki_dir: Path) -> Path:
    return pki_dir / TOKENS_FILENAME


def _load_tokens(pki_dir: Path) -> dict:
    try:
        data = yaml.safe_load(_token_file(pki_dir).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _token_key(agent_id: str, component: str) -> str:
    """登记键：agent_id + 组件（同一 agent 的 agent / nvmet-host 各自独立，互不覆盖）。"""
    return f"{agent_id}/{component}"


def _save_tokens(pki_dir: Path, tokens: dict) -> None:
    pki_dir.mkdir(parents=True, exist_ok=True)
    tmp = _token_file(pki_dir).with_suffix(".yml.tmp")
    tmp.write_text(yaml.safe_dump(tokens, allow_unicode=True, sort_keys=True), encoding="utf-8")
    os.replace(tmp, _token_file(pki_dir))
    os.chmod(_token_file(pki_dir), 0o600)


def generate_bootstrap_token(pki_dir: Path, agent_id: str, component: str,
                             days: int | None = None) -> str:
    """登记一次性 bootstrap token，返回明文（仅登记 sha256 hash）。

    格式仿 K8S cluster-bootstrap：<6位>.<16位>（hex 随机）。同日同一组件已有未
    过期 token 则沿用（幂等，便于重试部署）。
    """
    days = days or config.BOOTSTRAP_TOKEN_TTL_DAYS
    tokens = _load_tokens(pki_dir)
    now = _dt.datetime.now(_dt.timezone.utc)
    key = _token_key(agent_id, component)
    existing = tokens.get(key)
    if existing and not existing.get("used"):
        try:
            if _dt.datetime.fromisoformat(existing["expires_at"]) > now:
                # 幂等：登记只存 hash，明文无法恢复；重新生成会覆盖旧 token
                log.warning("pki: active bootstrap token exists for %s/%s; "
                            "delete the entry to reissue", agent_id, component)
                return None
        except ValueError:
            pass
    token_id = secrets.token_hex(3)
    token_secret = secrets.token_hex(8)
    expires = (now + _dt.timedelta(days=days)).isoformat()
    tokens[key] = {
        "component": component,
        "token_id": token_id,
        # 明文仅在生成时可见：登记只存 hash（与 K8S cluster-bootstrap 同思路）
        "token_secret_hash": hashlib.sha256(token_secret.encode()).hexdigest(),
        "expires_at": expires,
        "usage": ["enroll"],
        "used": False,
    }
    _save_tokens(pki_dir, tokens)
    log.info("pki: bootstrap token issued for %s (agent_id=%s, expires=%s)", component, agent_id, expires)
    return f"{token_id}.{token_secret}"


def get_bootstrap_token(pki_dir: Path, agent_id: str, component: str) -> dict | None:
    """只读返回某 agent 组件的 bootstrap token 登记条目（剔除 secret hash）。"""
    entry = _load_tokens(pki_dir).get(_token_key(agent_id, component))
    if not entry:
        return None
    return {k: v for k, v in entry.items() if k != "token_secret_hash"}


def consume_bootstrap_token(pki_dir: Path, token: str, agent_id: str, component: str) -> None:
    """校验并一次性消费 bootstrap token（enroll 用）。

    校验：格式、登记存在、组件匹配、未用过、未过期。通过后标记 used（防重放）。
    失败抛 ValueError（调用方转 401）。
    """
    token = token.strip()
    token_id, _, secret = token.partition(".")
    if not token_id or not secret:
        raise ValueError("malformed bootstrap token")
    tokens = _load_tokens(pki_dir)
    key = _token_key(agent_id, component)
    entry = tokens.get(key)
    if not entry:
        raise ValueError(f"no bootstrap token for {key}")
    if entry.get("used"):
        raise ValueError("bootstrap token already used")
    if not hmac.compare_digest(hashlib.sha256(secret.encode()).hexdigest(),
                               entry.get("token_secret_hash", "")):
        raise ValueError("bootstrap token invalid")
    try:
        expired = _dt.datetime.fromisoformat(entry["expires_at"]) < _dt.datetime.now(_dt.timezone.utc)
    except (KeyError, ValueError):
        expired = True
    if expired:
        raise ValueError("bootstrap token expired")
    entry["used"] = True
    _save_tokens(pki_dir, tokens)
    log.info("pki: bootstrap token consumed: agent_id=%s component=%s", agent_id, component)
