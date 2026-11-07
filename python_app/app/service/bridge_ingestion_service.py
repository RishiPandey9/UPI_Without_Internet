import logging
import time
from typing import Optional, NamedTuple
from app.crypto.hybrid_crypto import HybridCryptoService
from app.model.mesh_packet import MeshPacket
from app.model.transaction import Transaction
from app.service.idempotency_service import IdempotencyService
from app.service.settlement_service import SettlementService

log = logging.getLogger(__name__)


class IngestResult(NamedTuple):
    outcome: str
    packet_hash: str
    reason: Optional[str] = None
    transaction_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "packetHash": self.packet_hash,
            "reason": self.reason,
            "transactionId": self.transaction_id
        }


class BridgeIngestionService:
    """
    Orchestrates ingestion of packets submitted by bridge nodes:
      1. Hash ciphertext (SHA-256 idempotency key).
      2. Claim via IdempotencyService (drops duplicates before doing heavy work).
      3. Decrypt ciphertext using server's RSA private key.
      4. Check freshness window (24 hours).
      5. Hand off to SettlementService.
    """
    def __init__(
        self,
        crypto: HybridCryptoService,
        idempotency: IdempotencyService,
        settlement: SettlementService,
        max_age_seconds: int = 86400
    ):
        self.crypto = crypto
        self.idempotency = idempotency
        self.settlement = settlement
        self.max_age_seconds = max_age_seconds

    def ingest(self, packet: MeshPacket, bridge_node_id: str, hop_count: int) -> IngestResult:
        try:
            packet_hash = self.crypto.hash_ciphertext(packet.ciphertext)

            # 1. Idempotency Gate
            if not self.idempotency.claim(packet_hash):
                log.info(
                    "DUPLICATE packet %s... from bridge %s — dropped",
                    packet_hash[:12], bridge_node_id
                )
                return IngestResult(outcome="DUPLICATE_DROPPED", packet_hash=packet_hash)

            # 2. Decrypt
            try:
                instruction = self.crypto.decrypt(packet.ciphertext)
            except Exception as e:
                log.warning(
                    "Decryption failed for packet %s...: %s",
                    packet_hash[:12], str(e)
                )
                return IngestResult(outcome="INVALID", packet_hash=packet_hash, reason="decryption_failed")

            # 3. Freshness Check (Replay Protection)
            now_epoch_ms = int(time.time() * 1000)
            age_seconds = (now_epoch_ms - instruction.signed_at) / 1000.0

            if age_seconds > self.max_age_seconds:
                log.warning(
                    "Packet %s... too old (%.1fs), rejected",
                    packet_hash[:12], age_seconds
                )
                return IngestResult(outcome="INVALID", packet_hash=packet_hash, reason="stale_packet")

            if age_seconds < -300:  # Allow 5 minutes clock skew
                return IngestResult(outcome="INVALID", packet_hash=packet_hash, reason="future_dated")

            # 4. Settle Transaction
            tx = self.settlement.settle(instruction, packet_hash, bridge_node_id, hop_count)
            return IngestResult(outcome="SETTLED", packet_hash=packet_hash, transaction_id=tx.id)

        except Exception as e:
            log.error("Ingestion error: %s", str(e), exc_info=True)
            return IngestResult(outcome="INVALID", packet_hash="?", reason=f"internal_error: {str(e)}")
