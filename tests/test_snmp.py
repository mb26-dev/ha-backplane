"""SNMP codec, v2c/v3 client and health evaluation tests (no Home Assistant needed)."""

import asyncio
import hashlib
import importlib

snmp = importlib.import_module("backplane.snmp")
usm = importlib.import_module("backplane.usm")
health = importlib.import_module("backplane.health")

ENGINE = bytes.fromhex("000000000000000000000002")


def test_ber_integers_and_oids():
    assert snmp._enc_int(0) == b"\x02\x01\x00"
    assert snmp._enc_int(128) == b"\x02\x02\x00\x80"
    assert snmp._enc_int(-1) == b"\x02\x01\xff"
    oid = (1, 3, 6, 1, 4, 1, 11, 2, 14, 11, 1, 9, 1, 1, 1, 3, 1, 99999)
    assert snmp._dec_oid(snmp._enc_oid(oid)[2:]) == oid
    long = snmp._tlv(0x04, b"x" * 300)
    _, payload, _ = snmp._dec_tlv(long, 0)
    assert len(payload) == 300


def test_rfc3414_key_localization():
    ku = usm.password_to_key("maplesyrup", hashlib.md5)
    assert ku.hex() == "9faf3283884e92834ebc9847d8edd963"
    assert usm.localize_key(ku, ENGINE, hashlib.md5).hex() == "526f5eed9fcce26f8964c2930787d82b"
    ku = usm.password_to_key("maplesyrup", hashlib.sha1)
    assert ku.hex() == "9fb5cc0381497b3793528939ff788d5d79145211"
    assert usm.localize_key(ku, ENGINE, hashlib.sha1).hex() == "6695febc9288e36282235fc7151f128497b38f3f"


def test_v3_encode_decode_roundtrip():
    for auth in ("md5", "sha", "sha256"):
        for priv in (None, "aes", "des"):
            session = usm.UsmSession(usm.V3Params("bp", auth, "authpass123", priv, "privpass123"))
            session.set_engine(b"\x80\x00\x00\x0b\x03\x01\x02\x03\x04\x05\x06", 3, 1000)
            message = session.encode(42, 0xA0, [(1, 3, 6, 1, 2, 1, 1, 1, 0)])
            decoded = session.decode(message)
            assert decoded["request_id"] == 42
            assert decoded["varbinds"][0][0] == (1, 3, 6, 1, 2, 1, 1, 1, 0)


def _response(community, request_id, varbinds):
    body = b"".join(snmp._tlv(0x30, snmp._enc_oid(oid) + snmp._tlv(tag, value)) for oid, (tag, value) in varbinds)
    pdu = snmp._tlv(0xA2, snmp._enc_int(request_id) + snmp._enc_int(0) + snmp._enc_int(0) + snmp._tlv(0x30, body))
    return snmp._tlv(0x30, snmp._enc_int(1) + snmp._tlv(0x04, community) + pdu)


def test_v2c_get_and_walk_against_fake_agent():
    mib = {snmp.parse_oid(f"1.3.6.1.2.1.31.1.1.1.1.{i}"): (0x04, str(i).encode()) for i in range(1, 29)}
    mib[snmp.parse_oid("1.3.6.1.2.1.1.3.0")] = (0x43, (12345).to_bytes(4, "big"))
    keys = sorted(mib)

    class Agent(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            _, message, _ = snmp._dec_tlv(data, 0)
            pos = 0
            _, _, pos = snmp._dec_tlv(message, pos)
            _, community, pos = snmp._dec_tlv(message, pos)
            pdu_type, pdu, _ = snmp._dec_tlv(message, pos)
            pos = 0
            _, raw, pos = snmp._dec_tlv(pdu, pos)
            request_id = int.from_bytes(raw, "big")
            _, _, pos = snmp._dec_tlv(pdu, pos)
            _, raw_max, pos = snmp._dec_tlv(pdu, pos)
            _, vbl, _ = snmp._dec_tlv(pdu, pos)
            _, vb, _ = snmp._dec_tlv(vbl, 0)
            _, raw_oid, _ = snmp._dec_tlv(vb, 0)
            oid = snmp._dec_oid(raw_oid)
            if pdu_type == 0xA0:
                out = [(oid, mib.get(oid, (0x81, b"")))]
            else:
                out = []
                current = oid
                for _ in range(int.from_bytes(raw_max, "big")):
                    following = [k for k in keys if k > current]
                    if not following:
                        out.append((current, (0x82, b"")))
                        break
                    current = following[0]
                    out.append((current, mib[current]))
            self.transport.sendto(_response(community, request_id, out), addr)

    async def run():
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(Agent, local_addr=("127.0.0.1", 0))
        port = transport.get_extra_info("sockname")[1]
        client = snmp.SnmpClient("127.0.0.1", "public", port, timeout=1, retries=0)
        values = await client.get([snmp.parse_oid("1.3.6.1.2.1.1.3.0")])
        names = await client.walk(snmp.parse_oid("1.3.6.1.2.1.31.1.1.1.1"), max_repetitions=7)
        client.close()
        transport.close()
        return values, names

    values, names = asyncio.run(run())
    assert values[snmp.parse_oid("1.3.6.1.2.1.1.3.0")] == 12345
    assert len(names) == 28 and names[(28,)] == b"28"


def test_health_evaluation():
    data = {
        "system": {"cpu": 5, "uptime": 10 * 86400},
        "sensors": [{"id": 1, "name": "Fan Sensor", "status": "bad"}],
        "poe": {"budget": 100, "used": 85, "on": True},
        "ports": [
            {"n": "1", "k": "eth", "up": True, "spd": 1000, "err_h": 20, "dup": "half"},
            {"n": "2", "k": "eth", "up": False, "spd": 0},
            {"n": "3", "k": "eth", "up": True, "spd": 1000},
            {"n": "Trk1", "k": "lag", "up": True, "spd": 2000, "mem": ["2", "3"]},
        ],
    }
    result = health.evaluate(data)
    codes = {f["code"] for f in result["findings"]}
    assert {"hw_bad", "poe_budget", "errors", "half_duplex", "lag_degraded"} <= codes
    assert result["grade"] == "critical"
    assert result["score"] == 100 - 25 - 10 * 4
    html, text = health.render_report([{"title": "sw", "system": {"host": "1.2.3.4", "uptime": 100, "cpu": 5}, "totals": {"up": 2, "total": 3, "in": 0}, "poe": None, "health": result}])
    assert "Switch Health Report" in html and "display:flex" not in html
    assert "sw (1.2.3.4)" in text
