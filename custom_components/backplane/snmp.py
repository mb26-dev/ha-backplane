"""Minimal asynchronous SNMP v2c client (GET / GETBULK) without external dependencies.

Backplane deliberately ships its own tiny BER codec instead of pysnmp:
- no blocking MIB loading inside the Home Assistant event loop
- no version conflicts with the pysnmp pinned by Home Assistant core
- small GETBULK windows keep UDP datagrams below tunnel MTUs (VPN / DERP paths)
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterable
from typing import Any

Oid = tuple[int, ...]

# BER / SNMP tags
_INTEGER = 0x02
_OCTET_STRING = 0x04
_NULL = 0x05
_OID = 0x06
_SEQUENCE = 0x30
_IPADDRESS = 0x40
_COUNTER32 = 0x41
_GAUGE32 = 0x42
_TIMETICKS = 0x43
_OPAQUE = 0x44
_COUNTER64 = 0x46
_NO_SUCH_OBJECT = 0x80
_NO_SUCH_INSTANCE = 0x81
_END_OF_MIB_VIEW = 0x82

PDU_GET = 0xA0
PDU_GETNEXT = 0xA1
PDU_RESPONSE = 0xA2
PDU_GETBULK = 0xA5

_ERROR_TOO_BIG = 1


class SnmpError(Exception):
    """Generic SNMP failure."""


class SnmpTimeout(SnmpError):
    """The agent did not answer in time."""


class NoValue:
    """Marker for noSuchObject / noSuchInstance / endOfMibView."""

    __slots__ = ("kind",)

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def __repr__(self) -> str:
        return f"NoValue({self.kind})"


NO_SUCH_OBJECT = NoValue("noSuchObject")
NO_SUCH_INSTANCE = NoValue("noSuchInstance")
END_OF_MIB_VIEW = NoValue("endOfMibView")


def parse_oid(value: str | Oid) -> Oid:
    """Convert '1.3.6.1...' (optional leading dot) to a tuple."""
    if isinstance(value, tuple):
        return value
    return tuple(int(part) for part in value.strip(".").split("."))


def oid_str(oid: Oid) -> str:
    """Dotted representation of an OID tuple."""
    return ".".join(str(part) for part in oid)


# ---------------------------------------------------------------- encoding


def _enc_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + _enc_len(len(payload)) + payload


def _enc_int(value: int) -> bytes:
    if value == 0:
        return _tlv(_INTEGER, b"\x00")
    size = (value.bit_length() + 8) // 8
    return _tlv(_INTEGER, value.to_bytes(size, "big", signed=True))


def _enc_oid(oid: Oid) -> bytes:
    if len(oid) < 2:
        raise ValueError(f"OID too short: {oid}")
    out = bytearray([oid[0] * 40 + oid[1]])
    for sub in oid[2:]:
        if sub == 0:
            out.append(0)
            continue
        chunk: list[int] = []
        while sub:
            chunk.append(sub & 0x7F)
            sub >>= 7
        chunk.reverse()
        last = len(chunk) - 1
        for pos, part in enumerate(chunk):
            out.append(part | (0x80 if pos < last else 0))
    return _tlv(_OID, bytes(out))


def encode_request(
    community: str,
    pdu_type: int,
    request_id: int,
    oids: Iterable[Oid],
    non_repeaters: int = 0,
    max_repetitions: int = 0,
) -> bytes:
    """Build a complete SNMP v2c request message."""
    varbinds = b"".join(
        _tlv(_SEQUENCE, _enc_oid(oid) + _tlv(_NULL, b"")) for oid in oids
    )
    if pdu_type == PDU_GETBULK:
        field2, field3 = non_repeaters, max_repetitions
    else:
        field2, field3 = 0, 0
    pdu = _tlv(
        pdu_type,
        _enc_int(request_id)
        + _enc_int(field2)
        + _enc_int(field3)
        + _tlv(_SEQUENCE, varbinds),
    )
    return _tlv(
        _SEQUENCE,
        _enc_int(1)  # version: v2c
        + _tlv(_OCTET_STRING, community.encode())
        + pdu,
    )


# ---------------------------------------------------------------- decoding


def _dec_tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    if pos + 2 > len(data):
        raise SnmpError("truncated packet")
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        size = length & 0x7F
        if size == 0 or size > 4 or pos + size > len(data):
            raise SnmpError("invalid length")
        length = int.from_bytes(data[pos : pos + size], "big")
        pos += size
    end = pos + length
    if end > len(data):
        raise SnmpError("truncated value")
    return tag, data[pos:end], end


def _dec_oid(payload: bytes) -> Oid:
    if not payload:
        return ()
    first = payload[0]
    if first < 40:
        parts = [0, first]
    elif first < 80:
        parts = [1, first - 40]
    else:
        parts = [2, first - 80]
    value = 0
    for byte in payload[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return tuple(parts)


def _dec_value(tag: int, payload: bytes) -> Any:
    if tag == _INTEGER:
        return int.from_bytes(payload, "big", signed=True) if payload else 0
    if tag in (_COUNTER32, _GAUGE32, _TIMETICKS, _COUNTER64):
        return int.from_bytes(payload, "big", signed=False) if payload else 0
    if tag in (_OCTET_STRING, _OPAQUE):
        return bytes(payload)
    if tag == _OID:
        return _dec_oid(payload)
    if tag == _IPADDRESS:
        return ".".join(str(b) for b in payload)
    if tag == _NULL:
        return None
    if tag == _NO_SUCH_OBJECT:
        return NO_SUCH_OBJECT
    if tag == _NO_SUCH_INSTANCE:
        return NO_SUCH_INSTANCE
    if tag == _END_OF_MIB_VIEW:
        return END_OF_MIB_VIEW
    return bytes(payload)


def decode_response(data: bytes) -> tuple[int, int, int, list[tuple[Oid, Any]]]:
    """Return (request_id, error_status, error_index, varbinds)."""
    tag, message, _ = _dec_tlv(data, 0)
    if tag != _SEQUENCE:
        raise SnmpError("not an SNMP message")
    pos = 0
    _, _version, pos = _dec_tlv(message, pos)
    _, _community, pos = _dec_tlv(message, pos)
    pdu_tag, pdu, _ = _dec_tlv(message, pos)
    if pdu_tag != PDU_RESPONSE:
        raise SnmpError(f"unexpected PDU 0x{pdu_tag:02x}")
    pos = 0
    _, raw, pos = _dec_tlv(pdu, pos)
    request_id = int.from_bytes(raw, "big", signed=True)
    _, raw, pos = _dec_tlv(pdu, pos)
    error_status = int.from_bytes(raw, "big", signed=True)
    _, raw, pos = _dec_tlv(pdu, pos)
    error_index = int.from_bytes(raw, "big", signed=True)
    _, vblist, _ = _dec_tlv(pdu, pos)
    varbinds: list[tuple[Oid, Any]] = []
    pos = 0
    while pos < len(vblist):
        _, vb, pos = _dec_tlv(vblist, pos)
        _, raw_oid, vpos = _dec_tlv(vb, 0)
        vtag, vraw, _ = _dec_tlv(vb, vpos)
        varbinds.append((_dec_oid(raw_oid), _dec_value(vtag, vraw)))
    return request_id, error_status, error_index, varbinds


# ---------------------------------------------------------------- transport


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.pending: dict[int, asyncio.Future] = {}

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: Any) -> None:
        try:
            request_id, status, index, varbinds = decode_response(data)
        except (SnmpError, IndexError, ValueError):
            return
        future = self.pending.pop(request_id, None)
        if future is not None and not future.done():
            future.set_result((status, index, varbinds))

    def error_received(self, exc: Exception) -> None:
        # ICMP port unreachable etc. - let the request time out / retry
        return

    def connection_lost(self, exc: Exception | None) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(SnmpError("transport closed"))
        self.pending.clear()
        self.transport = None


class SnmpClient:
    """Async SNMP v2c client bound to a single agent."""

    def __init__(
        self,
        host: str,
        community: str,
        port: int = 161,
        timeout: float = 3.0,
        retries: int = 2,
        max_varbinds: int = 16,
    ) -> None:
        self.host = host
        self.port = port
        self.community = community
        self.timeout = timeout
        self.retries = retries
        self.max_varbinds = max_varbinds
        self._protocol: _Protocol | None = None
        self._lock = asyncio.Lock()
        self._request_id = random.randint(1, 0x3FFFFFFF)

    def _next_id(self) -> int:
        self._request_id = (self._request_id % 0x7FFFFFF0) + 1
        return self._request_id

    async def _ensure_transport(self) -> _Protocol:
        async with self._lock:
            if self._protocol is None or self._protocol.transport is None:
                loop = asyncio.get_running_loop()
                _, protocol = await loop.create_datagram_endpoint(
                    _Protocol, remote_addr=(self.host, self.port)
                )
                self._protocol = protocol
            return self._protocol

    async def _request(
        self,
        pdu_type: int,
        oids: list[Oid],
        non_repeaters: int = 0,
        max_repetitions: int = 0,
    ) -> list[tuple[Oid, Any]]:
        protocol = await self._ensure_transport()
        loop = asyncio.get_running_loop()
        for _attempt in range(self.retries + 1):
            request_id = self._next_id()
            message = encode_request(
                self.community,
                pdu_type,
                request_id,
                oids,
                non_repeaters,
                max_repetitions,
            )
            future: asyncio.Future = loop.create_future()
            protocol.pending[request_id] = future
            if protocol.transport is None:
                protocol.pending.pop(request_id, None)
                self._protocol = None
                protocol = await self._ensure_transport()
                continue
            protocol.transport.sendto(message)
            try:
                status, index, varbinds = await asyncio.wait_for(
                    future, self.timeout
                )
            except TimeoutError:
                protocol.pending.pop(request_id, None)
                continue
            if status == _ERROR_TOO_BIG and pdu_type == PDU_GET and len(oids) > 1:
                half = len(oids) // 2
                return await self._request(pdu_type, oids[:half]) + await self._request(
                    pdu_type, oids[half:]
                )
            if status:
                raise SnmpError(f"agent error-status {status} at index {index}")
            return varbinds
        raise SnmpTimeout(f"no response from {self.host}:{self.port}")

    async def get(self, oids: Iterable[Oid]) -> dict[Oid, Any]:
        """GET a list of OIDs (split into batches). Missing values are omitted."""
        oid_list = list(oids)
        result: dict[Oid, Any] = {}
        for start in range(0, len(oid_list), self.max_varbinds):
            batch = oid_list[start : start + self.max_varbinds]
            for oid, value in await self._request(PDU_GET, batch):
                if not isinstance(value, NoValue):
                    result[oid] = value
        return result

    async def walk(self, base: Oid, max_repetitions: int = 10) -> dict[Oid, Any]:
        """Walk a subtree with GETBULK. Keys are the index suffix below ``base``."""
        result: dict[Oid, Any] = {}
        current = base
        base_len = len(base)
        for _ in range(5000):
            varbinds = await self._request(
                PDU_GETBULK, [current], 0, max_repetitions
            )
            if not varbinds:
                break
            done = False
            for oid, value in varbinds:
                if isinstance(value, NoValue) or oid[:base_len] != base:
                    done = True
                    break
                if oid <= current:
                    # agent is not increasing - avoid an endless loop
                    done = True
                    break
                result[oid[base_len:]] = value
                current = oid
            if done:
                break
        return result

    def close(self) -> None:
        """Close the UDP socket."""
        if self._protocol is not None and self._protocol.transport is not None:
            self._protocol.transport.close()
        self._protocol = None
