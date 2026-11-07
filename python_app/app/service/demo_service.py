import hashlib
import logging
import time
import uuid
from decimal import Decimal
from app.crypto.hybrid_crypto import HybridCryptoService
from app.crypto.server_key import ServerKeyHolder
from app.model.account import Account
from app.model.mesh_packet import MeshPacket
from app.model.payment_instruction import PaymentInstruction
from app.service.settlement_service import SettlementService

log = logging.getLogger(__name__)


class DemoService:
    """
    Seeds demo bank accounts and simulates sender phones composing encrypted packets.
    """
    def __init__(
        self,
        settlement: SettlementService,
        crypto: HybridCryptoService,
        server_key: ServerKeyHolder
    ):
        self.settlement = settlement
        self.crypto = crypto
        self.server_key = server_key
        self.seed_accounts()

    def seed_accounts(self) -> None:
        if not self.settlement.list_accounts():
            self.settlement.save_account(Account("alice@demo", "Alice", Decimal("5000.00")))
            self.settlement.save_account(Account("bob@demo", "Bob", Decimal("1000.00")))
            self.settlement.save_account(Account("carol@demo", "Carol", Decimal("2500.00")))
            self.settlement.save_account(Account("dave@demo", "Dave", Decimal("500.00")))
            log.info("Seeded 4 demo accounts (Alice, Bob, Carol, Dave)")

    def create_packet(
        self,
        sender_vpa: str,
        receiver_vpa: str,
        amount: Decimal,
        pin: str,
        ttl: int = 5
    ) -> MeshPacket:
        now_ms = int(time.time() * 1000)
        instruction = PaymentInstruction(
            sender_vpa=sender_vpa,
            receiver_vpa=receiver_vpa,
            amount=amount,
            pin_hash=hashlib.sha256(pin.encode('utf-8')).hexdigest(),
            nonce=str(uuid.uuid4()),
            signed_at=now_ms
        )

        ciphertext = self.crypto.encrypt(instruction, self.server_key.public_key)

        return MeshPacket(
            packetId=str(uuid.uuid4()),
            ttl=ttl,
            createdAt=now_ms,
            ciphertext=ciphertext
        )
