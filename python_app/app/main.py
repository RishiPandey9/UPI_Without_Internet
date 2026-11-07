import os
from decimal import Decimal
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Header, Response, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.crypto.server_key import ServerKeyHolder
from app.crypto.hybrid_crypto import HybridCryptoService
from app.model.mesh_packet import MeshPacket
from app.service.idempotency_service import IdempotencyService
from app.service.settlement_service import SettlementService
from app.service.virtual_device import VirtualDevice
from app.service.mesh_simulator_service import MeshSimulatorService
from app.service.bridge_ingestion_service import BridgeIngestionService
from app.service.demo_service import DemoService

app = FastAPI(
    title="UPI Without Internet (Mesh) - Python FastAPI Edition",
    description="Offline UPI mesh routing demonstration with hybrid RSA-OAEP + AES-GCM encryption and idempotency deduplication."
)

# Initialize core services (singleton lifecycle)
server_key = ServerKeyHolder()
crypto = HybridCryptoService(server_key=server_key)
idempotency = IdempotencyService(ttl_seconds=86400)
settlement = SettlementService()
mesh = MeshSimulatorService()
bridge = BridgeIngestionService(crypto=crypto, idempotency=idempotency, settlement=settlement)
demo = DemoService(settlement=settlement, crypto=crypto, server_key=server_key)


# ============================================================================
# Dashboard HTML
# ============================================================================
@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>UPI Mesh Dashboard</h1>"


# ============================================================================
# Key Endpoints
# ============================================================================
@app.get("/api/server-key")
def get_server_public_key():
    """
    Exposes server's public key (RSA-2048) so simulated sender phones
    can fetch it and encrypt offline payment instructions.
    """
    return {
        "publicKey": server_key.get_public_key_base64(),
        "algorithm": "RSA-2048 / OAEP-SHA256",
        "hybridScheme": "RSA-OAEP encrypts an AES-256-GCM session key"
    }


# ============================================================================
# Demo Endpoints
# ============================================================================
class DemoSendRequest(BaseModel):
    senderVpa: str
    receiverVpa: str
    amount: float
    pin: str
    ttl: Optional[int] = 5
    startDevice: Optional[str] = "phone-alice"


@app.post("/api/demo/send")
def demo_send(req: DemoSendRequest):
    """
    Simulates sender phone creating a signed & encrypted PaymentInstruction
    and injecting the resulting MeshPacket into the starting mesh node.
    """
    packet = demo.create_packet(
        sender_vpa=req.senderVpa,
        receiver_vpa=req.receiverVpa,
        amount=Decimal(str(req.amount)),
        pin=req.pin,
        ttl=req.ttl if req.ttl is not None else 5
    )

    start_device = req.startDevice or "phone-alice"
    mesh.inject(start_device, packet)

    return {
        "packetId": packet.packetId,
        "ciphertextPreview": packet.ciphertext[:64] + "...",
        "ttl": packet.ttl,
        "injectedAt": start_device
    }


# ============================================================================
# Mesh Simulator Endpoints
# ============================================================================
@app.get("/api/mesh/state")
def get_mesh_state():
    """
    Returns current device statuses, held packets, and idempotency cache size.
    """
    device_data = []
    for d in mesh.get_devices():
        device_data.append({
            "deviceId": d.device_id,
            "hasInternet": d.has_internet,
            "packetCount": d.packet_count(),
            "packetIds": [p.packetId[:8] for p in d.get_held_packets()]
        })
    return {
        "devices": device_data,
        "idempotencyCacheSize": idempotency.size()
    }


@app.post("/api/mesh/gossip")
def mesh_gossip():
    """
    Runs one gossip round where devices broadcast packets to neighboring peers.
    """
    res = mesh.gossip_once()
    return {
        "transfers": res.transfers,
        "deviceCounts": res.device_counts
    }


@app.post("/api/mesh/flush")
def mesh_flush():
    """
    Simulates bridge devices walking outside into cellular coverage and
    uploading all held packets simultaneously to test concurrent idempotency.
    """
    uploads = mesh.collect_bridge_uploads()
    results = []

    # Execute concurrent bridge uploads via ThreadPoolExecutor
    def upload_worker(up):
        hop_count = 5 - up.packet.ttl
        r = bridge.ingest(up.packet, up.bridge_node_id, hop_count)
        return {
            "bridgeNode": up.bridge_node_id,
            "packetId": up.packet.packetId[:8],
            "outcome": r.outcome,
            "reason": r.reason or "",
            "transactionId": r.transaction_id if r.transaction_id is not None else -1
        }

    with ThreadPoolExecutor(max_workers=max(1, len(uploads))) as pool:
        results = list(pool.map(upload_worker, uploads))

    return {
        "uploadsAttempted": len(uploads),
        "results": results
    }


@app.post("/api/mesh/reset")
def mesh_reset():
    """
    Clears all packets from all virtual devices and clears the idempotency cache.
    """
    mesh.reset_mesh()
    idempotency.clear()
    return {"status": "mesh and idempotency cache cleared"}


# ============================================================================
# Production Bridge Ingestion Endpoint
# ============================================================================
@app.post("/api/bridge/ingest")
def ingest_packet(
    packet: MeshPacket,
    x_bridge_node_id: str = Header("unknown", alias="X-Bridge-Node-Id"),
    x_hop_count: int = Header(0, alias="X-Hop-Count")
):
    """
    THE PRODUCTION ENDPOINT.
    Receives uploaded mesh packets from bridge nodes that gained internet access.
    """
    res = bridge.ingest(packet, x_bridge_node_id, x_hop_count)
    return res.to_dict()


# ============================================================================
# Ledger and Accounts
# ============================================================================
@app.get("/api/accounts")
def list_accounts():
    return [acc.to_dict() for acc in settlement.list_accounts()]


@app.get("/api/transactions")
def list_transactions():
    return [tx.to_dict() for tx in settlement.list_transactions()]
