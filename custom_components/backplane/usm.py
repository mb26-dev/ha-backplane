"""SNMPv3 User-based Security Model (RFC 3414 / RFC 3826 / RFC 7860) for Backplane.

Supports authNoPriv and authPriv with
- auth: MD5, SHA (SHA-1), SHA256
- priv: AES (AES-128-CFB), DES (DES-CBC)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from .snmp import (
    PDU_RESPONSE,
    SnmpError,
    _dec_oid,
    _dec_tlv,
    _dec_value,
    _enc_int,
    _enc_oid,
    _tlv,
)

_SEQUENCE = 0x30
_OCTET = 0x04
_NULL = 0x05
PDU_REPORT = 0xA8

AUTH_PROTOCOLS = {
    # name: (hash, mac length)
    "md5": (hashlib.md5, 12),
    "sha": (hashlib.sha1, 12),
    "sha256": (hashlib.sha256, 24),
}
PRIV_PROTOCOLS = ("aes", "des")

# usmStats report OIDs
_NOT_IN_TIME_WINDOW = (1, 3, 6, 1, 6, 3, 15, 1, 1, 2, 0)
_UNKNOWN_ENGINE_ID = (1, 3, 6, 1, 6, 3, 15, 1, 1, 4, 0)
_REPORT_TEXT = {
    (1, 3, 6, 1, 6, 3, 15, 1, 1, 1, 0): "unsupported security level",
    (1, 3, 6, 1, 6, 3, 15, 1, 1, 3, 0): "unknown user name",
    (1, 3, 6, 1, 6, 3, 15, 1, 1, 5, 0): "wrong digest (auth password or protocol)",
    (1, 3, 6, 1, 6, 3, 15, 1, 1, 6, 0): "decryption error (priv password or protocol)",
}


def _cfb(iv: bytes) -> Any:
    try:  # cryptography >= 47 moved CFB to the decrepit package
        from cryptography.hazmat.decrepit.ciphers.modes import CFB
    except ImportError:  # pragma: no cover - older cryptography
        from cryptography.hazmat.primitives.ciphers.modes import CFB
    return CFB(iv)


class SnmpAuthError(SnmpError):
    """Credentials rejected by the agent."""


def password_to_key(password: str, hash_fn: Any) -> bytes:
    """RFC 3414 A.2: hash the password cyclically expanded to 1 MB."""
    raw = password.encode()
    if not raw:
        raise SnmpAuthError("empty password")
    expanded = (raw * (1048576 // len(raw) + 1))[:1048576]
    return hash_fn(expanded).digest()


def localize_key(key: bytes, engine_id: bytes, hash_fn: Any) -> bytes:
    """RFC 3414 A.2.2: Kul = H(Ku || engineID || Ku)."""
    return hash_fn(key + engine_id + key).digest()


def _extend_priv_key(key: bytes, engine_id: bytes, hash_fn: Any, length: int) -> bytes:
    """Blumenthal key extension (needed only if the auth hash is shorter than the priv key)."""
    result = key
    while len(result) < length:
        result += localize_key(hash_fn(result).digest(), engine_id, hash_fn)[: length - len(result)]
    return result[:length]


@dataclass
class V3Params:
    """SNMPv3 credentials."""

    user: str
    auth_protocol: str = "sha"
    auth_password: str = ""
    priv_protocol: str | None = "aes"
    priv_password: str = ""
    context: str = ""


@dataclass
class _Engine:
    engine_id: bytes = b""
    boots: int = 0
    engine_time: int = 0
    synced_at: float = field(default_factory=time.monotonic)

    def now(self) -> tuple[int, int]:
        return self.boots, self.engine_time + int(time.monotonic() - self.synced_at)


class UsmSession:
    """Encodes and decodes SNMPv3 messages for one agent."""

    def __init__(self, params: V3Params) -> None:
        if params.auth_protocol not in AUTH_PROTOCOLS:
            raise SnmpAuthError(f"unsupported auth protocol {params.auth_protocol}")
        if params.priv_protocol and params.priv_protocol not in PRIV_PROTOCOLS:
            raise SnmpAuthError(f"unsupported priv protocol {params.priv_protocol}")
        self.params = params
        self.hash_fn, self.mac_len = AUTH_PROTOCOLS[params.auth_protocol]
        self._ku_auth = password_to_key(params.auth_password, self.hash_fn)
        self._ku_priv = (
            password_to_key(params.priv_password or params.auth_password, self.hash_fn)
            if params.priv_protocol
            else b""
        )
        self.engine = _Engine()
        self.auth_key = b""
        self.priv_key = b""
        self._salt = int.from_bytes(os.urandom(8), "big")

    @property
    def discovered(self) -> bool:
        return bool(self.engine.engine_id)

    def set_engine(self, engine_id: bytes, boots: int, engine_time: int) -> None:
        if engine_id != self.engine.engine_id:
            self.auth_key = localize_key(self._ku_auth, engine_id, self.hash_fn)
            if self.params.priv_protocol:
                priv = localize_key(self._ku_priv, engine_id, self.hash_fn)
                need = 16
                self.priv_key = _extend_priv_key(priv, engine_id, self.hash_fn, need)
        self.engine = _Engine(engine_id, boots, engine_time, time.monotonic())

    # ------------------------------------------------------------ encoding

    def discovery_message(self, msg_id: int) -> bytes:
        """Unauthenticated GET with empty engine ID -> agent answers with a Report."""
        header = _tlv(_SEQUENCE, _enc_int(msg_id) + _enc_int(65507) + _tlv(_OCTET, b"\x04") + _enc_int(3))
        sec = _tlv(
            _SEQUENCE,
            _tlv(_OCTET, b"") + _enc_int(0) + _enc_int(0) + _tlv(_OCTET, b"") + _tlv(_OCTET, b"") + _tlv(_OCTET, b""),
        )
        pdu = _tlv(0xA0, _enc_int(msg_id) + _enc_int(0) + _enc_int(0) + _tlv(_SEQUENCE, b""))
        scoped = _tlv(_SEQUENCE, _tlv(_OCTET, b"") + _tlv(_OCTET, b"") + pdu)
        return _tlv(_SEQUENCE, _enc_int(3) + header + _tlv(_OCTET, sec) + scoped)

    def _encrypt(self, plaintext: bytes) -> tuple[bytes, bytes]:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        boots, engine_time = self.engine.now()
        self._salt = (self._salt + 1) & 0xFFFFFFFFFFFFFFFF
        if self.params.priv_protocol == "aes":
            salt = self._salt.to_bytes(8, "big")
            iv = struct.pack(">II", boots, engine_time) + salt
            enc = Cipher(algorithms.AES(self.priv_key[:16]), _cfb(iv)).encryptor()
            return enc.update(plaintext) + enc.finalize(), salt
        # DES-CBC
        from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES

        salt = struct.pack(">I", boots) + (self._salt & 0xFFFFFFFF).to_bytes(4, "big")
        pre_iv = self.priv_key[8:16]
        iv = bytes(a ^ b for a, b in zip(pre_iv, salt))
        pad = (8 - len(plaintext) % 8) % 8
        des_key = self.priv_key[:8] * 3
        enc = Cipher(TripleDES(des_key), modes.CBC(iv)).encryptor()
        return enc.update(plaintext + b"\x00" * pad) + enc.finalize(), salt

    def _decrypt(self, ciphertext: bytes, salt: bytes, boots: int, engine_time: int) -> bytes:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        if self.params.priv_protocol == "aes":
            iv = struct.pack(">II", boots, engine_time) + salt
            dec = Cipher(algorithms.AES(self.priv_key[:16]), _cfb(iv)).decryptor()
            return dec.update(ciphertext) + dec.finalize()
        from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES

        if len(ciphertext) % 8:
            raise SnmpError("bad DES ciphertext length")
        iv = bytes(a ^ b for a, b in zip(self.priv_key[8:16], salt))
        dec = Cipher(TripleDES(self.priv_key[:8] * 3), modes.CBC(iv)).decryptor()
        return dec.update(ciphertext) + dec.finalize()

    def encode(
        self,
        msg_id: int,
        pdu_type: int,
        oids: list[tuple[int, ...]],
        non_repeaters: int = 0,
        max_repetitions: int = 0,
    ) -> bytes:
        varbinds = b"".join(_tlv(_SEQUENCE, _enc_oid(oid) + _tlv(_NULL, b"")) for oid in oids)
        pdu = _tlv(
            pdu_type,
            _enc_int(msg_id) + _enc_int(non_repeaters) + _enc_int(max_repetitions) + _tlv(_SEQUENCE, varbinds),
        )
        scoped = _tlv(
            _SEQUENCE,
            _tlv(_OCTET, self.engine.engine_id) + _tlv(_OCTET, self.params.context.encode()) + pdu,
        )
        priv = bool(self.params.priv_protocol)
        flags = 0x01 | (0x02 if priv else 0) | 0x04
        if priv:
            encrypted, salt = self._encrypt(scoped)
            msg_data = _tlv(_OCTET, encrypted)
        else:
            salt = b""
            msg_data = scoped
        boots, engine_time = self.engine.now()
        header = _tlv(
            _SEQUENCE,
            _enc_int(msg_id) + _enc_int(65507) + _tlv(_OCTET, bytes([flags])) + _enc_int(3),
        )
        placeholder = b"\x00" * self.mac_len
        sec_inner_head = (
            _tlv(_OCTET, self.engine.engine_id)
            + _enc_int(boots)
            + _enc_int(engine_time)
            + _tlv(_OCTET, self.params.user.encode())
        )
        auth_tlv = _tlv(_OCTET, placeholder)
        sec = _tlv(_SEQUENCE, sec_inner_head + auth_tlv + _tlv(_OCTET, salt))
        sec_octet = _tlv(_OCTET, sec)
        body = _enc_int(3) + header + sec_octet + msg_data
        message = _tlv(_SEQUENCE, body)
        # locate the auth placeholder structurally
        outer_head = len(message) - len(body)
        sec_octet_head = len(sec_octet) - len(sec)
        sec_head = len(sec) - (len(sec_inner_head) + len(auth_tlv) + len(_tlv(_OCTET, salt)))
        offset = (
            outer_head
            + len(_enc_int(3))
            + len(header)
            + sec_octet_head
            + sec_head
            + len(sec_inner_head)
            + (len(auth_tlv) - self.mac_len)
        )
        mac = hmac.new(self.auth_key, message, self.hash_fn).digest()[: self.mac_len]
        return message[:offset] + mac + message[offset + self.mac_len :]

    # ------------------------------------------------------------ decoding

    def decode(self, data: bytes) -> dict[str, Any]:
        """Decode a v3 message. Returns dict with request_id, pdu_tag, status, index, varbinds."""
        tag, message, _ = _dec_tlv(data, 0)
        if tag != _SEQUENCE:
            raise SnmpError("not an SNMP message")
        pos = 0
        _, raw_version, pos = _dec_tlv(message, pos)
        if int.from_bytes(raw_version, "big") != 3:
            raise SnmpError("not SNMPv3")
        _, header, pos = _dec_tlv(message, pos)
        hpos = 0
        _, raw_msg_id, hpos = _dec_tlv(header, hpos)
        _, _max, hpos = _dec_tlv(header, hpos)
        _, raw_flags, hpos = _dec_tlv(header, hpos)
        flags = raw_flags[0] if raw_flags else 0
        _, sec_raw, pos = _dec_tlv(message, pos)
        _, sec, _ = _dec_tlv(sec_raw, 0)
        spos = 0
        _, engine_id, spos = _dec_tlv(sec, spos)
        _, raw_boots, spos = _dec_tlv(sec, spos)
        _, raw_time, spos = _dec_tlv(sec, spos)
        _, _user, spos = _dec_tlv(sec, spos)
        _, _auth, spos = _dec_tlv(sec, spos)
        _, salt, spos = _dec_tlv(sec, spos)
        boots = int.from_bytes(raw_boots, "big") if raw_boots else 0
        engine_time = int.from_bytes(raw_time, "big") if raw_time else 0
        data_tag, msg_data, _ = _dec_tlv(message, pos)
        if flags & 0x02:
            if data_tag != _OCTET:
                raise SnmpError("expected encrypted scopedPDU")
            plain = self._decrypt(msg_data, salt, boots, engine_time)
            _, scoped, _ = _dec_tlv(plain, 0)
        else:
            scoped = msg_data
        cpos = 0
        _, _ctx_engine, cpos = _dec_tlv(scoped, cpos)
        _, _ctx_name, cpos = _dec_tlv(scoped, cpos)
        pdu_tag, pdu, _ = _dec_tlv(scoped, cpos)
        ppos = 0
        _, raw, ppos = _dec_tlv(pdu, ppos)
        request_id = int.from_bytes(raw, "big", signed=True)
        _, raw, ppos = _dec_tlv(pdu, ppos)
        status = int.from_bytes(raw, "big", signed=True)
        _, raw, ppos = _dec_tlv(pdu, ppos)
        index = int.from_bytes(raw, "big", signed=True)
        _, vblist, _ = _dec_tlv(pdu, ppos)
        varbinds = []
        vpos = 0
        while vpos < len(vblist):
            _, vb, vpos = _dec_tlv(vblist, vpos)
            _, raw_oid, opos = _dec_tlv(vb, 0)
            vtag, vraw, _ = _dec_tlv(vb, opos)
            varbinds.append((_dec_oid(raw_oid), _dec_value(vtag, vraw)))
        return {
            "msg_id": int.from_bytes(raw_msg_id, "big", signed=True),
            "request_id": request_id,
            "pdu_tag": pdu_tag,
            "status": status,
            "index": index,
            "varbinds": varbinds,
            "engine_id": engine_id,
            "boots": boots,
            "time": engine_time,
        }

    @staticmethod
    def report_reason(varbinds: list[tuple[tuple[int, ...], Any]]) -> tuple[str, str]:
        """Return (kind, text) for a Report PDU: kind in time|engine|auth|other."""
        for oid, _value in varbinds:
            if oid == _NOT_IN_TIME_WINDOW:
                return "time", "not in time window"
            if oid == _UNKNOWN_ENGINE_ID:
                return "engine", "unknown engine id"
            if oid in _REPORT_TEXT:
                return "auth", _REPORT_TEXT[oid]
        return "other", "agent report"


__all__ = [
    "AUTH_PROTOCOLS",
    "PDU_REPORT",
    "PDU_RESPONSE",
    "PRIV_PROTOCOLS",
    "SnmpAuthError",
    "UsmSession",
    "V3Params",
    "localize_key",
    "password_to_key",
]
