# ==============================================================================
# Creator: Anshul Vashist
# Email: vashistanshul.7@gmail.com
# LinkedIn: https://www.linkedin.com/in/av-0001/
# ==============================================================================
"""
HoudiniMind — Secure Credential Store

Stores API keys using the OS keyring (macOS Keychain, Windows Credential Manager,
Linux Secret Service).  If the ``keyring`` package is not available or the OS
backend is broken, falls back to a machine-bound encrypted file so the file is
useless on any other computer.

Usage:
    from houdinimind.agent.credential_store import CredentialStore

    store = CredentialStore()
    store.save_api_key("nvapi-xxxxxxxxx")
    key = store.get_api_key()          # -> "nvapi-xxxxxxxxx"
    store.delete_api_key()             # wipe
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform
import uuid

logger = logging.getLogger("houdinimind.credentials")

_SERVICE_NAME = "HoudiniMind"
_ACCOUNT_NAME = "api_key"

# -- Keyring backend --------------------------------------------------------

_KEYRING_AVAILABLE = False
try:
    import keyring as _keyring

    # Quick sanity check -- some installs ship a stub keyring that
    # silently discards passwords.  Detect that early.
    _backend = getattr(_keyring, "get_keyring", lambda: None)()
    _backend_name = type(_backend).__name__ if _backend else ""
    if "fail" in _backend_name.lower() or "null" in _backend_name.lower():
        raise RuntimeError(f"Unusable keyring backend: {_backend_name}")
    _KEYRING_AVAILABLE = True
except Exception as _exc:
    logger.debug("OS keyring unavailable (%s) -- will use encrypted file fallback", _exc)
    _keyring = None  # type: ignore[assignment]


# -- Machine-bound encryption fallback --------------------------------------


def _machine_id() -> str:
    """Return a stable, machine-specific identifier.

    Used as the key derivation seed so the encrypted credential file
    is useless on any other machine.
    """
    try:
        # macOS: hardware UUID from IOKit
        if platform.system() == "Darwin":
            import subprocess

            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                text=True,
                timeout=5,
            )
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]

        # Windows: MachineGuid from registry
        if platform.system() == "Windows":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(val)

        # Linux: /etc/machine-id
        mid_path = "/etc/machine-id"
        if os.path.isfile(mid_path):
            with open(mid_path) as f:
                return f.read().strip()
    except Exception:
        pass

    # Ultimate fallback: MAC address (stable across reboots)
    return str(uuid.getnode())


def _derive_key(machine_id: str) -> bytes:
    """Derive a 32-byte key from the machine identifier."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        machine_id.encode("utf-8"),
        salt=b"HoudiniMind_CredentialStore_v1",
        iterations=200_000,
    )


def _encrypt(plaintext: str, key: bytes) -> str:
    """Stream cipher encryption with random IV.  Machine-bound so the
    ciphertext file is useless on another computer."""
    iv = os.urandom(16)
    pt_bytes = plaintext.encode("utf-8")
    stream = b""
    counter = 0
    while len(stream) < len(pt_bytes):
        stream += hashlib.sha256(key + iv + counter.to_bytes(4, "big")).digest()
        counter += 1
    cipher = bytes(a ^ b for a, b in zip(pt_bytes, stream[: len(pt_bytes)], strict=True))
    return base64.b64encode(iv + cipher).decode("ascii")


def _decrypt(ciphertext_b64: str, key: bytes) -> str:
    """Reverse of _encrypt."""
    raw = base64.b64decode(ciphertext_b64)
    iv = raw[:16]
    cipher = raw[16:]
    stream = b""
    counter = 0
    while len(stream) < len(cipher):
        stream += hashlib.sha256(key + iv + counter.to_bytes(4, "big")).digest()
        counter += 1
    pt_bytes = bytes(a ^ b for a, b in zip(cipher, stream[: len(cipher)], strict=True))
    return pt_bytes.decode("utf-8")


# ==========================================================================
#  Public API
# ==========================================================================


class CredentialStore:
    """Secure, cross-platform credential storage for HoudiniMind API keys.

    Priority order:
      1. OS keyring (macOS Keychain / Windows Credential Manager / Linux SS)
      2. Machine-bound encrypted file (``<data_dir>/db/.credentials.enc``)

    The encrypted file is automatically created if the keyring is unavailable.
    It is keyed to this machine's hardware UUID so it cannot be decrypted on
    another computer.
    """

    def __init__(self, data_dir: str = ""):
        self._data_dir = data_dir
        self._key: bytes | None = None  # lazily derived

    # -- File fallback paths ------------------------------------------------

    @property
    def _enc_path(self) -> str:
        d = self._data_dir or os.path.join(os.path.expanduser("~"), ".houdinimind")
        return os.path.join(d, "db", ".credentials.enc")

    def _get_key(self) -> bytes:
        if self._key is None:
            self._key = _derive_key(_machine_id())
        return self._key

    # -- Keyring operations -------------------------------------------------

    def _keyring_get(self) -> str | None:
        if not _KEYRING_AVAILABLE:
            return None
        try:
            return _keyring.get_password(_SERVICE_NAME, _ACCOUNT_NAME)
        except Exception as exc:
            logger.debug("keyring.get_password failed: %s", exc)
            return None

    def _keyring_set(self, value: str) -> bool:
        if not _KEYRING_AVAILABLE:
            return False
        try:
            _keyring.set_password(_SERVICE_NAME, _ACCOUNT_NAME, value)
            return True
        except Exception as exc:
            logger.debug("keyring.set_password failed: %s", exc)
            return False

    def _keyring_delete(self) -> bool:
        if not _KEYRING_AVAILABLE:
            return False
        try:
            _keyring.delete_password(_SERVICE_NAME, _ACCOUNT_NAME)
            return True
        except Exception as exc:
            logger.debug("keyring.delete_password failed: %s", exc)
            return False

    # -- Encrypted file operations ------------------------------------------

    def _file_get(self) -> str | None:
        try:
            if not os.path.isfile(self._enc_path):
                return None
            with open(self._enc_path, encoding="utf-8") as f:
                payload = json.load(f)
            ct = payload.get("ct", "")
            if not ct:
                return None
            return _decrypt(ct, self._get_key())
        except Exception as exc:
            logger.debug("Encrypted credential file read failed: %s", exc)
            return None

    def _file_set(self, value: str) -> bool:
        try:
            path = self._enc_path
            os.makedirs(os.path.dirname(path), exist_ok=True)
            ct = _encrypt(value, self._get_key())
            payload = {"_v": 1, "ct": ct}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            # Restrict file permissions (owner-only read/write)
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass  # Windows may not support chmod
            return True
        except Exception as exc:
            logger.debug("Encrypted credential file write failed: %s", exc)
            return False

    def _file_delete(self) -> bool:
        try:
            if os.path.isfile(self._enc_path):
                os.remove(self._enc_path)
            return True
        except Exception:
            return False

    # -- Public API ---------------------------------------------------------

    def get_api_key(self) -> str:
        """Retrieve the stored API key.  Returns empty string if not set."""
        # Try keyring first
        val = self._keyring_get()
        if val:
            return val
        # Fall back to encrypted file
        val = self._file_get()
        return val or ""

    def save_api_key(self, api_key: str) -> bool:
        """Store the API key securely.  Returns True on success."""
        if not api_key or not api_key.strip():
            return self.delete_api_key()

        api_key = api_key.strip()
        # Try keyring first
        if self._keyring_set(api_key):
            logger.info("API key saved to OS keyring (%s)", _SERVICE_NAME)
            # Also keep file backup in case keyring becomes unavailable
            self._file_set(api_key)
            return True
        # Fall back to encrypted file only
        if self._file_set(api_key):
            logger.info("API key saved to encrypted file: %s", self._enc_path)
            return True
        logger.error("Failed to save API key -- neither keyring nor file backend worked")
        return False

    def delete_api_key(self) -> bool:
        """Remove the stored API key from all backends."""
        kr = self._keyring_delete()
        fi = self._file_delete()
        return kr or fi

    def has_api_key(self) -> bool:
        """Check if an API key is stored without retrieving it."""
        return bool(self.get_api_key())

    @staticmethod
    def is_keyring_available() -> bool:
        """Check if the OS keyring backend is available."""
        return _KEYRING_AVAILABLE
