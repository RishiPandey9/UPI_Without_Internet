from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class Account:
    """
    Simulated bank account ledger entity.
    """
    vpa: str
    holder_name: str
    balance: Decimal
    version: int = 0

    def to_dict(self) -> dict:
        return {
            "vpa": self.vpa,
            "holderName": self.holder_name,
            "balance": float(self.balance),
            "version": self.version
        }
