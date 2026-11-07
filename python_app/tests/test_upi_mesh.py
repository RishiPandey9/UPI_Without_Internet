import time
import uuid
import pytest
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

from app.crypto.server_key import ServerKeyHolder
from app.crypto.hybrid_crypto import HybridCryptoService
from app.model.account import Account
from app.model.mesh_packet import MeshPacket
from app.model.payment_instruction import PaymentInstruction
from app.service.idempotency_service import IdempotencyService
from app.service.settlement_service import SettlementService
from app.service.bridge_ingestion_service import BridgeIngestionService
from app.service.demo_service import DemoService


@pytest.fixture
def test_setup():
    server_key = ServerKeyHolder()
    crypto = HybridCryptoService(server_key=server_key)
    idempotency = IdempotencyService()
    settlement = SettlementService()
    bridge = BridgeIngestionService(crypto=crypto, idempotency=idempotency, settlement=settlement)
    demo = DemoService(settlement=settlement, crypto=crypto, server_key=server_key)
    return {
        "server_key": server_key,
        "crypto": crypto,
        "idempotency": idempotency,
        "settlement": settlement,
        "bridge": bridge,
        "demo": demo
    }


def test_hybrid_encryption_roundtrip(test_setup):
    crypto = test_setup["crypto"]
    instruction = PaymentInstruction(
        sender_vpa="alice@demo",
        receiver_vpa="bob@demo",
        amount=Decimal("150.00"),
        pin_hash="testpin",
        nonce=str(uuid.uuid4()),
        signed_at=int(time.time() * 1000)
    )

    ciphertext = crypto.encrypt(instruction)
    decrypted = crypto.decrypt(ciphertext)

    assert decrypted.sender_vpa == instruction.sender_vpa
    assert decrypted.receiver_vpa == instruction.receiver_vpa
    assert decrypted.amount == instruction.amount
    assert decrypted.nonce == instruction.nonce


def test_single_packet_delivered_by_three_bridges_settles_exactly_once(test_setup):
    """
    Direct Python equivalent of IdempotencyConcurrencyTest in Java:
    Simulates three bridge nodes delivering the identical packet simultaneously.
    Asserts:
      - exactly one thread settles the transaction
      - exactly two threads receive DUPLICATE_DROPPED
      - sender balance is debited exactly once
    """
    demo = test_setup["demo"]
    bridge = test_setup["bridge"]
    settlement = test_setup["settlement"]

    # Initial balance: Alice ₹5000, Bob ₹1000
    alice_init = settlement.get_account("alice@demo").balance
    bob_init = settlement.get_account("bob@demo").balance

    packet = demo.create_packet("alice@demo", "bob@demo", Decimal("500.00"), "1234", ttl=3)

    bridge_nodes = ["bridge-alpha", "bridge-beta", "bridge-gamma"]

    def upload(node_id):
        return bridge.ingest(packet, node_id, hop_count=2)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(upload, bridge_nodes))

    settled_count = sum(1 for r in results if r.outcome == "SETTLED")
    duplicate_count = sum(1 for r in results if r.outcome == "DUPLICATE_DROPPED")

    assert settled_count == 1, f"Expected 1 settlement, got {settled_count}"
    assert duplicate_count == 2, f"Expected 2 duplicate drops, got {duplicate_count}"

    # Verify ledger state
    alice_after = settlement.get_account("alice@demo").balance
    bob_after = settlement.get_account("bob@demo").balance

    assert alice_after == alice_init - Decimal("500.00")
    assert bob_after == bob_init + Decimal("500.00")


def test_tampered_ciphertext_rejected(test_setup):
    demo = test_setup["demo"]
    bridge = test_setup["bridge"]

    packet = demo.create_packet("alice@demo", "bob@demo", Decimal("100.00"), "1234")

    # Tamper with the ciphertext by flipping characters
    tampered_bytes = bytearray(packet.ciphertext, 'ascii')
    tampered_bytes[-10] = ord('A') if tampered_bytes[-10] != ord('A') else ord('B')
    tampered_packet = MeshPacket(
        packetId=packet.packetId,
        ttl=packet.ttl,
        createdAt=packet.createdAt,
        ciphertext=tampered_bytes.decode('ascii')
    )

    res = bridge.ingest(tampered_packet, "bridge-test", 1)
    assert res.outcome == "INVALID"
    assert "decryption_failed" in res.reason


def test_stale_packet_rejected(test_setup):
    crypto = test_setup["crypto"]
    bridge = test_setup["bridge"]

    # Create packet signed 25 hours ago
    stale_time_ms = int((time.time() - 90000) * 1000)
    instruction = PaymentInstruction(
        sender_vpa="alice@demo",
        receiver_vpa="bob@demo",
        amount=Decimal("50.00"),
        pin_hash="1234",
        nonce=str(uuid.uuid4()),
        signed_at=stale_time_ms
    )
    ciphertext = crypto.encrypt(instruction)
    packet = MeshPacket(
        packetId=str(uuid.uuid4()),
        ttl=1,
        createdAt=stale_time_ms,
        ciphertext=ciphertext
    )

    res = bridge.ingest(packet, "bridge-stale", 4)
    assert res.outcome == "INVALID"
    assert res.reason == "stale_packet"
