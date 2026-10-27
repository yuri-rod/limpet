from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import tempfile


@dataclass
class Config:
    host: str
    port: int
    token: str


def _dir():
    return Path(os.environ.get("LIMPET_CONFIG_DIR", Path.home() / ".config" / "limpet"))


def ensure_token(path):
    path = Path(path)
    if path.exists():
        token = path.read_text().strip()
        if len(token) >= 32:
            path.chmod(0o600)
            return token
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    # mkstemp creates at 0600, so the token is never briefly world-readable
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    return token


class ConfigError(Exception):
    pass


def load():
    d = _dir()
    cfg_path = d / "config.json"
    try:
        raw = json.loads(cfg_path.read_text())
        host = raw["host"]
        port = int(raw.get("port", 8737))
    except (OSError, ValueError, TypeError, KeyError) as e:
        raise ConfigError(f"{cfg_path}: {e}") from e
    if not isinstance(host, str) or not host.strip():
        raise ConfigError(f"{cfg_path}: host must be a non-empty string")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            # Socket APIs also accept abbreviated and hexadecimal IPv4 literals.
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            address = None
    if address is not None and address.is_unspecified:
        raise ConfigError(
            f"{cfg_path}: host {host!r} would bind the bridge on all "
            "interfaces; use a tailnet address or 127.0.0.1 (or --dev "
            "for local-only)"
        )
    return Config(host=host, port=port, token=ensure_token(d / "token"))
