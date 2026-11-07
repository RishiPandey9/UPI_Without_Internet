from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional
from datetime import datetime


class TransactionStatus(str, Enum):
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


@dataclass
class Transaction:
    """
    Immutable ledger record of settled or rejected payments.
    """
    id: int
    packet_hash: str
    sender_vpa: str
    receiver_vpa: str
    amount: Decimal
    signed_at: datetime
    settled_at: datetime
    bridge_node_id: str
    hop_count: int
    status: TransactionStatus

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "packetHash": self.packet_hash,
            "senderVpa": self.sender_vpa,
            "receiverVpa": self.receiver_vpa,
            "amount": float(self.amount),
            "signedAt": self.signed_at.isoformat(),
            "settledAt": self.settled_at.isoformat(),
            "bridgeNodeId": self.bridge_node_id,
            "hopCount": self.hop_count,
            "status": self.status.value
        }
