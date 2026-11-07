# UPI Offline Mesh — Python FastAPI Demo

A Python (FastAPI) backend that demonstrates **offline UPI payments routed through a Bluetooth-style mesh network**. You're in a basement with zero connectivity. You send your friend ₹500. Your phone encrypts the payment, broadcasts it to nearby phones, and the packet hops device-to-device until *some* phone walks outside, gets 4G, and silently uploads it to this backend. The backend decrypts, deduplicates, and settles.

This repo is the **Python server side** of that system, plus an in-memory software simulator of the mesh and a live interactive web dashboard so you can demo the whole flow on a single laptop without any real Bluetooth hardware.

---

## Table of Contents

1. [What this demo proves](#what-this-demo-proves)
2. [How to run it](#how-to-run-it)
3. [The demo flow (step by step)](#the-demo-flow-step-by-step)
4. [Architecture](#architecture)
5. [The three hard problems and how they're solved](#the-three-hard-problems-and-how-theyre-solved)
6. [File-by-file walkthrough](#file-by-file-walkthrough)
7. [API reference](#api-reference)
8. [Tests](#tests)
9. [What's NOT real (and what would change for production)](#whats-not-real-and-what-would-change-for-production)
10. [Honest limitations of the concept](#honest-limitations-of-the-concept)
11. [Troubleshooting](#troubleshooting)

---

## What this demo proves

The system shows three things working end to end:

1. **A payment can travel from sender to backend through untrusted intermediaries** without any of them being able to read or tamper with it. (Hybrid RSA-2048 OAEP + AES-256-GCM encryption.)
2. **Even if the same payment reaches the backend simultaneously through multiple bridge nodes, it settles exactly once.** (Idempotency via atomic compare-and-set on the ciphertext SHA-256 hash.)
3. **A tampered or replayed packet is rejected** before it touches the ledger.

You'll see all three in the live web dashboard.

---

## How to run it

### Prerequisites

- **Python 3.10 or newer** installed and on PATH. Check with:
  ```bash
  python --version
  ```
- No external database or Redis required (uses in-memory structures and thread-safe locking).

### 1. Install Dependencies

Open a terminal in the `python_app` folder and run:

```bash
pip install -r requirements.txt
```

### 2. Run the Application

```bash
python run.py
```
*(Or directly using uvicorn: `uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload`)*

### 3. Open the dashboard

Once you see `Uvicorn running on http://0.0.0.0:8080`, open your browser to:

**http://localhost:8080**

You'll get an interactive dark dashboard with controls and live tables to drive the entire mesh demo.

### 4. Stop the server

Press `Ctrl+C` in the terminal.

### 5. Run the tests

```bash
pytest tests
```

The interesting one is `test_single_packet_delivered_by_three_bridges_settles_exactly_once` — it fires three threads delivering the same packet simultaneously and asserts that exactly one settles, two are dropped as duplicates, and the sender is debited exactly once.

---

## The demo flow (step by step)

The dashboard has four buttons that walk through the full pipeline. The intended sequence:

### Step 1 — Compose a payment

Choose sender, receiver, amount, PIN. Click **"📤 Inject into Mesh"**.

**What actually happens on the backend:**
- The server pretends to be the sender's phone.
- It builds a `PaymentInstruction` with a unique nonce and current timestamp.
- It encrypts that with the server's RSA public key (using hybrid encryption — see below).
- It wraps the ciphertext in a `MeshPacket` with a TTL of 5.
- It hands the packet to `phone-alice`, an offline virtual device.

You'll see `phone-alice` now holds 1 packet.

### Step 2 — Run gossip rounds

Click **"🔄 Run Gossip Round"**. Then click it again.

Each round, every device that holds a packet broadcasts it to every other device within "Bluetooth range" (which, in our simulator, means everyone). TTL decrements per hop.

After 1 round: every device holds the packet. After 2 rounds: still every device — TTL is just lower.

In the real system this would happen organically as people walk past each other in the basement.

### Step 3 — Bridge node walks outside

Click **"📡 Bridges Upload to Backend"**.

`phone-bridge` is the only device with `hasInternet=true`. The dashboard simulates that phone walking outside and getting 4G. It POSTs every packet it holds to `/api/bridge/ingest`.

The backend pipeline runs:
1. Hash the ciphertext (`SHA-256`).
2. Try to claim the hash in the idempotency cache.
3. If claimed: decrypt with the server's RSA private key.
4. Verify freshness (signedAt within 24 hours).
5. Run the debit/credit in an atomic transaction.

Watch the **Account Balances** table — money has moved. Watch the **Transaction Ledger** — a new row appears.

### Step 4 — Demonstrate idempotency (the killer feature)

Reset the mesh. Inject a single packet. Run gossip 2 times. Now all 5 devices hold the same packet.

When you click **"📡 Bridges Upload to Backend"**, all bridge nodes attempt upload simultaneously.
To exercise the concurrent duplicate case properly, run:

```bash
pytest tests/test_upi_mesh.py -k test_single_packet_delivered_by_three_bridges_settles_exactly_once
```

This test creates one packet, fires 3 threads at `BridgeIngestionService.ingest()` simultaneously, and verifies that exactly one settles, two are dropped as duplicates, and the sender is debited exactly once.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SENDER PHONE (offline)                          │
│  PaymentInstruction { sender, receiver, amount, pinHash, nonce, time }  │
│              │                                                          │
│              ▼ encrypt with server's RSA public key                     │
│   MeshPacket { packetId, ttl, createdAt, ciphertext }                   │
└──────────────────────────────────────┬──────────────────────────────────┘
                                       │ Bluetooth gossip
                                       ▼
        ┌─────────┐  hop   ┌─────────┐  hop   ┌─────────┐
        │stranger1│ ─────▶ │stranger2│ ─────▶ │ bridge  │ ◀── walks outside
        └─────────┘        └─────────┘        └────┬────┘     gets 4G
                                                   │
                                                   ▼ HTTPS POST
┌─────────────────────────────────────────────────────────────────────────┐
│                     FASTAPI BACKEND (python_app)                        │
│                                                                         │
│  /api/bridge/ingest                                                     │
│       │                                                                 │
│       ▼                                                                 │
│  [1] hash ciphertext (SHA-256)                                          │
│       │                                                                 │
│       ▼                                                                 │
│  [2] IdempotencyService.claim(hash)  ◀── atomic claim (≈ Redis SETNX)   │
│       │                                  Duplicates rejected here,      │
│       │                                  before any work.               │
│       ▼                                                                 │
│  [3] HybridCryptoService.decrypt(ciphertext)                            │
│       │       (RSA-OAEP unwraps AES key, AES-GCM decrypts payload       │
│       │        AND verifies the auth tag — tampering = exception)       │
│       ▼                                                                 │
│  [4] Freshness check: signedAt within last 24h                          │
│       │                                                                 │
│       ▼                                                                 │
│  [5] SettlementService.settle()                                         │
│       Atomic debit sender, credit receiver, write ledger                │
│       Optimistic lock versioning prevents lost updates                  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## The three hard problems and how they're solved

### Problem 1: Untrusted intermediates

A random stranger's phone is carrying your transaction. How do you stop them from reading the amount or changing it?

**Solution: Hybrid encryption (RSA-OAEP + AES-GCM).**

The sender encrypts the payload with the server's public key. Only the server holds the private key, so intermediates see opaque ciphertext.

But RSA can only encrypt small data (~245 bytes for a 2048-bit key). Our payment instruction (JSON) could exceed that. So we use the standard hybrid pattern:

1. Generate a fresh AES-256 key for *this packet*.
2. Encrypt the JSON with **AES-256-GCM** (fast + authenticated).
3. Encrypt just the AES key with **RSA-OAEP** (SHA-256).
4. Concatenate: `[256 bytes RSA-encrypted AES key][12 bytes IV][AES ciphertext + 16-byte GCM tag]`.

**Why GCM specifically?** It's authenticated encryption. If an intermediate flips one bit anywhere in the ciphertext, decryption throws an exception — the GCM tag won't verify. The server cannot be tricked into processing tampered data.

See `app/crypto/hybrid_crypto.py`.

### Problem 2: The duplicate-storm

Three bridge nodes hold the same packet. They all walk outside at the same instant. They all POST to `/api/bridge/ingest` within milliseconds of each other. If you naively process all three, the sender is debited ₹1500 instead of ₹500.

**Solution: Atomic compare-and-set on the ciphertext hash.**

The very first thing the server does on receiving a packet is compute `SHA-256(ciphertext)` and try to "claim" that hash:

```python
# app/service/idempotency_service.py
with self._lock:
    if packet_hash in self._seen:
        if now - self._seen[packet_hash] < self._ttl_seconds:
            return False  # Duplicate!
    self._seen[packet_hash] = now
    return True  # First claimer!
```

Even if 100 threads call it at the exact same nanosecond, exactly one returns `True` (the first claimer) and the rest return `False`. Only the first claimer proceeds to decrypt and settle. The rest are short-circuited as `DUPLICATE_DROPPED`.

**Why hash the ciphertext, not the packetId or the cleartext?**
- `packetId` can be rewritten by a malicious intermediate. Two copies of the same payment could have different packetIds. Bad key.
- The cleartext requires decryption first. We want to dedupe *before* spending CPU on RSA.
- The ciphertext is authenticated by GCM, so any tampering is detectable on decrypt. Two legitimate deliveries of the same payment have byte-identical ciphertexts.

In production this in-memory cache becomes Redis: `SET key NX EX 86400`. Same semantics, distributed across replicas.

### Problem 3: Replay attacks

An attacker who captured a ciphertext weeks ago could replay it whenever convenient.

**Solution: Two layers.**

1. **Inside the encrypted payload**, the sender includes `signedAt` (epoch millis). The server rejects any packet older than 24 hours. The attacker can't change `signedAt` without breaking the GCM tag.
2. **Inside the encrypted payload**, the sender includes a **nonce** (UUID). Even if Alice legitimately sends Bob ₹100 twice, the nonces differ → ciphertexts differ → hashes differ → both settle. But a *replay* of one specific signed packet is byte-identical, so the idempotency cache catches it.

See `app/service/bridge_ingestion_service.py` for the freshness check.

---

## File-by-file walkthrough

```
python_app/
├── requirements.txt                         Dependencies (FastAPI, Uvicorn, Cryptography, Pydantic, Pytest)
├── run.py                                   Startup script for the FastAPI server
├── README.md                                This documentation file
│
├── app/
│   ├── __init__.py
│   ├── main.py                              FastAPI application with all REST and HTML endpoints
│   │
│   ├── model/                               ── Domain Entities
│   │   ├── account.py                       Account dataclass with versioning
│   │   ├── mesh_packet.py                   Pydantic model for over-the-wire packets
│   │   ├── payment_instruction.py           Decrypted payload with nonce, pinHash, signedAt
│   │   └── transaction.py                   Settled/Rejected ledger record
│   │
│   ├── crypto/                              ── Cryptography Layer
│   │   ├── server_key.py                    Generates and holds RSA-2048 keypair
│   │   └── hybrid_crypto.py                 RSA-OAEP + AES-256-GCM encryption & ciphertext SHA-256
│   │
│   ├── service/                             ── Business & Simulation Services
│   │   ├── idempotency_service.py           Thread-safe atomic cache (Redis SETNX equivalent)
│   │   ├── settlement_service.py            Ledger updates, atomic debit/credit & balance validation
│   │   ├── virtual_device.py                Simulated phone node in the mesh
│   │   ├── mesh_simulator_service.py        Gossip protocol rounds and bridge upload collection
│   │   ├── bridge_ingestion_service.py      The core pipeline: hash → claim → decrypt → verify → settle
│   │   └── demo_service.py                  Demo account seeder and sender packet builder
│   │
│   └── templates/
│       └── dashboard.html                   Interactive dark UI with live mesh visualization
│
└── tests/
    ├── __init__.py
    ├── test_upi_mesh.py                     Concurrency idempotency test, tamper test, freshness test
    └── test_api.py                          FastAPI REST endpoints and pipeline integration tests
```

---

## API reference

| Method | Path | What it does |
|---|---|---|
| GET | `/` | Live Dashboard HTML |
| GET | `/api/server-key` | Server's RSA public key (base64 DER SubjectPublicKeyInfo) |
| GET | `/api/accounts` | All accounts and balances |
| GET | `/api/transactions` | Last 20 settled/rejected transactions |
| GET | `/api/mesh/state` | Current state of every virtual device and held packets |
| POST | `/api/demo/send` | Simulate sender phone — encrypt + inject packet |
| POST | `/api/mesh/gossip` | Run one round of gossip across the mesh |
| POST | `/api/mesh/flush` | Bridges with internet upload to backend (parallel) |
| POST | `/api/mesh/reset` | Clear mesh + idempotency cache |
| POST | `/api/bridge/ingest` | **The production endpoint.** Real bridges POST here |

### Request format for `/api/bridge/ingest`

```http
POST /api/bridge/ingest
Content-Type: application/json
X-Bridge-Node-Id: phone-bridge-42
X-Hop-Count: 3

{
  "packetId": "550e8400-e29b-41d4-a716-446655440000",
  "ttl": 2,
  "createdAt": 1730000000000,
  "ciphertext": "base64-encoded-RSA-and-AES-blob"
}
```

Response:
```json
{
  "outcome": "SETTLED",                     // or "DUPLICATE_DROPPED" or "INVALID"
  "packetHash": "a3f8c9...",
  "reason": null,                            // populated on INVALID
  "transactionId": 42                        // populated on SETTLED
}
```

---

## Tests

Run all tests:
```bash
pytest tests
```

The key tests included:

- **`test_hybrid_encryption_roundtrip`** — Verifies that RSA-OAEP + AES-GCM encryption and decryption preserves all fields.
- **`test_single_packet_delivered_by_three_bridges_settles_exactly_once`** — The headline test: 3 parallel worker threads deliver the same packet simultaneously. Asserts exactly 1 `SETTLED`, 2 `DUPLICATE_DROPPED`, and that the sender's balance changed exactly once.
- **`test_tampered_ciphertext_rejected`** — Flips bytes in the ciphertext, verifying that `BridgeIngestionService` returns `INVALID` with reason `decryption_failed` rather than corrupting the ledger.
- **`test_stale_packet_rejected`** — Replays a packet signed >24 hours ago and confirms rejection with `stale_packet`.
- **`test_api_endpoints`** — Validates key retrieval, account listing, and the end-to-end injection → gossip → flush workflow via FastAPI.

---

## What's NOT real (and what would change for production)

This is a teaching demo. To make it production-grade you'd swap these things:

| What's in the demo | What it would be in production |
|---|---|
| In-memory Python dicts | PostgreSQL / MySQL with read replicas |
| Threading Lock for idempotency | Redis with `SET NX EX` |
| RSA keypair regenerated on startup | Private key in HSM (AWS KMS, HashiCorp Vault). Public key cached on devices |
| Server-side `DemoService.create_packet()` | Same code running on Android, in a Kotlin port |
| Software-simulated mesh (`MeshSimulatorService`) | Real BLE GATT or Wi-Fi Direct between phones |
| One settlement service that owns the ledger | Integration with NPCI / a real core banking system |
| No auth on `/api/bridge/ingest` | Mutual TLS (mTLS) or signed bridge-node certificates |
| In-memory accounts seeded on startup | Real KYC'd users, real VPAs, real PIN verification against bank HSM |
| Console logs | Structured JSON logging to Datadog / OpenSearch / ELK, alerts on `INVALID` spikes |

The cryptography and idempotency architecture is production-shaped. The infrastructure around it is what changes.

---

## Honest limitations of the concept

1. **The receiver has no way to verify the sender has the funds.** When sender hands receiver a phone showing "₹500 sent," it's an IOU, not a settled payment. If the sender's account is empty when the packet finally reaches the backend, the settlement will be `REJECTED` and the receiver is out ₹500 with no recourse. *This is why real offline UPI (UPI Lite) uses a pre-funded hardware-backed wallet on the phone* — to give cryptographic proof of available funds offline.
2. **A malicious sender can double-spend offline.** With ₹500 in their account, they could send a packet to Bob in basement A, walk to basement B, and send another ₹500 to Carol. Whichever packet hits the backend first wins; the other gets `REJECTED`. Same root cause as #1.
3. **Bluetooth in real life is hard.** Background BLE on Android is heavily throttled since Android 8. iOS peripheral mode is locked down. Two strangers' phones reliably forming a GATT connection while the apps aren't actively open is genuinely difficult. This demo skips that hardware hurdle by simulating the mesh.
4. **Privacy / liability.** A stranger carries your encrypted transaction packet on their phone. They can't read it, but its existence is metadata.

For a portfolio project: frame this honestly as **"mesh-routed deferred settlement"** rather than "real-time offline UPI," and you will have a rock-solid engineering pitch.

---

## Troubleshooting

- **`python: command not found`** — Install Python 3.10+ from python.org or via package manager (`winget install Python.Python.3.11`).
- **Port 8080 already in use** — In `run.py`, change `port=8080` to another port (e.g. `8085`).
- **Missing packages** — Run `pip install -r requirements.txt`.

---

## License

Demo code for educational and learning purposes.
