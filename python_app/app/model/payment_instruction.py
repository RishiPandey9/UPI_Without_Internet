from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class PaymentInstruction:
    """
    The actual decrypted payment instruction.
    Contains nonce and timestamp for replay protection.
    """
    sender_vpa: str
    receiver_vpa: str
    amount: Decimal
    pin_hash: str
    nonce: str
    signed_at: int  # epoch millis

    def to_dict(self) -> dict:
        return {
            "senderVpa": self.sender_vpa,
            "receiverVpa": self.receiver_vpa,
            "amount": str(self.amount),
            "pinHash": self.pin_hash,
            "nonce": self.nonce,
            "signedAt": self.signed_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PaymentInstruction":
        return cls(
            sender_vpa=data["senderVpa"],
            receiver_vpa=data["receiverVpa"],
            amount=Decimal(str(data["amount"])),
            pin_hash=data["pinHash"],
            nonce=data["nonce"],
            signed_at=int(data["signedAt"])
        )
