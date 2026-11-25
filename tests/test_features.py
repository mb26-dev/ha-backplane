"""Tests for SET encoding, v3 report matching and the extended health checks."""

import importlib

snmp = importlib.import_module("backplane.snmp")
usm = importlib.import_module("backplane.usm")
health = importlib.import_module("backplane.health")
vendors = importlib.import_module("backplane.vendors")


def _base(**extra):
    data = {
        "system": {"uptime": 10 * 86400, "cpu": 3},
        "ports": [],
        "poe": None,
        "sensors": [],
        "totals": {"in": 0, "out": 0, "up": 0, "total": 0},
    }
    data.update(extra)
    return data


def _port(name, **extra):
    port = {"n": name, "k": "eth", "up": True, "spd": 1000, "in": 0, "out": 0, "ie": 0, "oe": 0}
    port.update(extra)
    return port


def test_set_varbind_carries_integer_value():
    oid = (1, 3, 6, 1, 2, 1, 105, 1, 1, 1, 3, 1, 9)
    message = snmp.encode_request("private", snmp.PDU_SET, 7, [(oid, snmp.encode_int_value(2))])
    assert message.endswith(snmp._enc_oid(oid) + b"\x02\x01\x02")
    plain = snmp.encode_request("public", snmp.PDU_GET, 7, [oid])
    assert plain.endswith(snmp._enc_oid(oid) + b"\x05\x00")


def test_v3_set_message_encodes():
    params = usm.V3Params(user="backplane", auth_protocol="sha", auth_password="authpass1",
                          priv_protocol="aes", priv_password="privpass1")
    session = usm.UsmSession(params)
    session.set_engine(bytes.fromhex("000000000000000000000002"), 1, 100)
    oid = (1, 3, 6, 1, 2, 1, 105, 1, 1, 1, 3, 1, 9)
    message = session.encode(42, snmp.PDU_SET, [(oid, snmp.encode_int_value(1))])
    assert message[0] == 0x30 and len(message) > 60


def test_saturated_and_busy_ports():
    data = _base(ports=[_port("1", u=97.0), _port("2", u=85.0), _port("3", u=10.0)])
    codes = {f["code"]: f["level"] for f in health.evaluate(data)["findings"]}
    assert codes["port_saturated"] == "warning"
    assert codes["port_busy"] == "info"
    assert len(codes) == 2


def test_broadcast_storm_levels():
    data = _base(ports=[_port("5", bc=6000), _port("6", bc=1500), _port("7", bc=20)])
    found = [(f["code"], f["port"]) for f in health.evaluate(data)["findings"]]
    assert ("broadcast_storm", "5") in found
    assert ("broadcast_high", "6") in found
    assert all(port != "7" for _, port in found)


def test_spanning_tree_instability():
    unstable = health.evaluate(_base(stp={"tc": 40, "tc_h": 5}))
    assert unstable["findings"][0]["code"] == "stp_unstable"
    assert unstable["grade"] == "warning"
    calm = health.evaluate(_base(stp={"tc": 40, "tc_h": 0}))
    assert calm["findings"] == [] and calm["score"] == 100


def test_vendor_detection():
    hp = (1, 3, 6, 1, 4, 1, 11, 2, 3, 7, 11, 181)
    assert vendors.detect_vendor(hp, "HP J9773A 2530-24G-PoEP Switch, revision YA.16.11") == "HPE Aruba"
    assert vendors.detect_vendor((1, 3, 6, 1, 4, 1, 14988, 1), "RouterOS CRS326") == "MikroTik"
    assert vendors.detect_vendor((1, 3, 6, 1, 4, 1, 890, 1), "GS1900-24") == "Zyxel"
    assert vendors.detect_vendor((1, 3, 6, 1, 4, 1, 4526, 100), "GS308T") == "Netgear"
    assert vendors.detect_vendor((1, 3, 6, 1, 4, 1, 99999), "something") == ""


def _agent_report(msg_id: int, request_id: int, oid: tuple, engine: bytes) -> bytes:
    t = snmp._tlv
    header = t(0x30, snmp._enc_int(msg_id) + snmp._enc_int(65507) + t(0x04, b"\x00") + snmp._enc_int(3))
    sec = t(0x30, t(0x04, engine) + snmp._enc_int(1) + snmp._enc_int(100) + t(0x04, b"") + t(0x04, b"") + t(0x04, b""))
    varbind = t(0x30, snmp._enc_oid(oid) + t(0x41, b"\x01"))
    pdu = t(0xA8, snmp._enc_int(request_id) + snmp._enc_int(0) + snmp._enc_int(0) + t(0x30, varbind))
    scoped = t(0x30, t(0x04, engine) + t(0x04, b"") + pdu)
    return t(0x30, snmp._enc_int(3) + header + t(0x04, sec) + scoped)


def _msg_id(data: bytes) -> int:
    _, message, _ = snmp._dec_tlv(data, 0)
    _, _, pos = snmp._dec_tlv(message, 0)
    _, header, _ = snmp._dec_tlv(message, pos)
    _, raw, _ = snmp._dec_tlv(header, 0)
    return int.from_bytes(raw, "big", signed=True)


def test_v3_wrong_digest_report_with_request_id_zero():
    import asyncio

    engine = bytes.fromhex("80000b0103001122334455")
    unknown_engine = (1, 3, 6, 1, 6, 3, 15, 1, 1, 4, 0)
    wrong_digest = (1, 3, 6, 1, 6, 3, 15, 1, 1, 5, 0)

    class Agent(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport
            self.seen = 0

        def datagram_received(self, data, addr):
            self.seen += 1
            oid = unknown_engine if self.seen == 1 else wrong_digest
            # like many agents: request-id 0, only the msgID is echoed
            self.transport.sendto(_agent_report(_msg_id(data), 0, oid, engine), addr)

    async def run():
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(Agent, local_addr=("127.0.0.1", 0))
        port = transport.get_extra_info("sockname")[1]
        params = usm.V3Params(user="backplane", auth_protocol="sha256", auth_password="wrongpass1",
                              priv_protocol="aes", priv_password="wrongpass1")
        client = snmp.SnmpClient("127.0.0.1", "", port, timeout=1.0, retries=1, v3=params)
        try:
            await client.get([(1, 3, 6, 1, 2, 1, 1, 5, 0)])
        except usm.SnmpAuthError as err:
            return str(err)
        finally:
            client.close()
            transport.close()
        return "no error"

    message = asyncio.run(run())
    assert "wrong digest" in message
