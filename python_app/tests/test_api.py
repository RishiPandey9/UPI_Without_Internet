from app.main import (
    app,
    get_server_public_key,
    list_accounts,
    list_transactions,
    demo_send,
    DemoSendRequest,
    get_mesh_state,
    mesh_gossip,
    mesh_flush,
    mesh_reset,
)


def test_server_key_endpoint():
    data = get_server_public_key()
    assert "publicKey" in data
    assert data["algorithm"] == "RSA-2048 / OAEP-SHA256"


def test_accounts_endpoint():
    accounts = list_accounts()
    assert len(accounts) >= 4
    vpas = [a["vpa"] for a in accounts]
    assert "alice@demo" in vpas
    assert "bob@demo" in vpas


def test_mesh_pipeline_flow():
    # 1. Reset mesh
    reset_res = mesh_reset()
    assert "status" in reset_res

    # 2. Inject payment
    req = DemoSendRequest(
        senderVpa="alice@demo",
        receiverVpa="bob@demo",
        amount=250.0,
        pin="1234",
        ttl=5,
        startDevice="phone-alice"
    )
    send_res = demo_send(req)
    assert "packetId" in send_res
    assert send_res["injectedAt"] == "phone-alice"

    # 3. Check mesh state
    state = get_mesh_state()
    alice = next(d for d in state["devices"] if d["deviceId"] == "phone-alice")
    assert alice["packetCount"] == 1

    # 4. Run gossip
    gossip_res = mesh_gossip()
    assert gossip_res["transfers"] > 0

    # 5. Flush bridges
    flush_res = mesh_flush()
    assert flush_res["uploadsAttempted"] >= 1
    outcomes = [r["outcome"] for r in flush_res["results"]]
    assert "SETTLED" in outcomes

    # 6. Check transactions
    txs = list_transactions()
    assert len(txs) > 0
    assert txs[0]["status"] == "SETTLED"
    assert txs[0]["amount"] == 250.0
