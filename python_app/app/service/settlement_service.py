import logging
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from app.model.account import Account
from app.model.payment_instruction import PaymentInstruction
from app.model.transaction import Transaction, TransactionStatus

log = logging.getLogger(__name__)


class SettlementService:
    """
    Manages accounts and ledger settlement.
    Atomic debit/credit with optimistic locking and thread safety.
    """
    def __init__(self):
        self._accounts: Dict[str, Account] = {}
        self._transactions: List[Transaction] = []
        self._tx_counter: int = 1
        self._lock = threading.Lock()

    def get_account(self, vpa: str) -> Optional[Account]:
        with self._lock:
            return self._accounts.get(vpa)

    def list_accounts(self) -> List[Account]:
        with self._lock:
            return list(self._accounts.values())

    def save_account(self, account: Account) -> None:
        with self._lock:
            self._accounts[account.vpa] = account

    def list_transactions(self, limit: int = 20) -> List[Transaction]:
        with self._lock:
            # Return most recent transactions first
            return list(reversed(self._transactions[-limit:]))

    def settle(
        self,
        instruction: PaymentInstruction,
        packet_hash: str,
        bridge_node_id: str,
        hop_count: int
    ) -> Transaction:
        with self._lock:
            sender = self._accounts.get(instruction.sender_vpa)
            if not sender:
                raise ValueError(f"Unknown sender VPA: {instruction.sender_vpa}")

            receiver = self._accounts.get(instruction.receiver_vpa)
            if not receiver:
                raise ValueError(f"Unknown receiver VPA: {instruction.receiver_vpa}")

            amount = instruction.amount
            if amount <= Decimal("0"):
                raise ValueError("Amount must be positive")

            signed_at_dt = datetime.fromtimestamp(instruction.signed_at / 1000.0, tz=timezone.utc)
            settled_at_dt = datetime.now(timezone.utc)

            # Insufficient funds check
            if sender.balance < amount:
                log.warning(
                    "Insufficient balance: %s has ₹%s, attempted to send ₹%s",
                    sender.vpa, sender.balance, amount
                )
                tx = Transaction(
                    id=self._tx_counter,
                    packet_hash=packet_hash,
                    sender_vpa=instruction.sender_vpa,
                    receiver_vpa=instruction.receiver_vpa,
                    amount=amount,
                    signed_at=signed_at_dt,
                    settled_at=settled_at_dt,
                    bridge_node_id=bridge_node_id,
                    hop_count=hop_count,
                    status=TransactionStatus.REJECTED
                )
                self._tx_counter += 1
                self._transactions.append(tx)
                return tx

            # Atomic debit and credit
            sender.balance -= amount
            sender.version += 1

            receiver.balance += amount
            receiver.version += 1

            tx = Transaction(
                id=self._tx_counter,
                packet_hash=packet_hash,
                sender_vpa=instruction.sender_vpa,
                receiver_vpa=instruction.receiver_vpa,
                amount=amount,
                signed_at=signed_at_dt,
                settled_at=settled_at_dt,
                bridge_node_id=bridge_node_id,
                hop_count=hop_count,
                status=TransactionStatus.SETTLED
            )
            self._tx_counter += 1
            self._transactions.append(tx)

            log.info(
                "SETTLED ₹%s from %s to %s (packetHash=%s..., bridge=%s, hops=%s)",
                amount, sender.vpa, receiver.vpa, packet_hash[:12], bridge_node_id, hop_count
            )
            return tx
