# UPI Offline Mesh — Interview Preparation Guide

This document is your complete cheat sheet for technical interviews. It covers **why you built this**, **how to pitch it**, **deep architectural questions**, and **honest explanations of why real-world production differs**.

---

## 1. Project Pitch & Motivation

### Q: Why did you choose to build this project instead of a standard web app?
> **Answer:**  
> "Most resume projects are standard CRUD applications with a database and a React frontend. I wanted to build something that tackled real distributed systems and security problems: **asynchronous routing, hybrid cryptography, untrusted intermediaries, and strict idempotency**.  
> 
> In India and developing regions, digital payment adoption drops significantly in basements, underground parking, remote rural areas, or during natural disasters where cellular data drops. I wanted to demonstrate how a peer-to-peer gossip protocol over BLE, paired with hybrid RSA-OAEP and AES-GCM encryption, can safely ferry financial instructions through untrusted strangers' devices and guarantee exact-once settlement when any device touches connectivity."

---

## 2. Real-World Reality Checks & Limitations

### Q: Why is this mesh-gossip architecture not used in official production UPI today?
> **Answer:**  
> "There are four fundamental real-world constraints that make deferred mesh settlement dangerous for general-purpose payments:
> 
> 1. **No Proof of Funds for the Receiver (Counterparty Risk):**  
>    When Alice hands Bob her phone showing '₹500 Sent' in a basement, Bob is holding an **IOU**, not a cleared payment. If Alice’s bank balance is actually ₹0 when the packet finally reaches the bank hours later, the transaction is `REJECTED`, and Bob has already parted with his goods.
> 2. **Offline Double Spending:**  
>    Without a centralized ledger or trusted hardware element, Alice can send ₹500 to Bob in Basement A, walk over to Basement B, and send the same ₹500 to Carol. Whichever packet reaches a 4G bridge node first will settle; the second will bounce.
> 3. **OS-Level Mobile BLE Throttling:**  
>    Since Android 8 and on all iOS versions, background BLE broadcasting and scanning are heavily restricted to save battery. Spontaneous mesh formation between locked phones in people's pockets is difficult and unreliable in practice without custom OS support.
> 4. **Regulatory & Audit Trails:**  
>    Carrying stranger's encrypted financial packets introduces legal and compliance gray areas under RBI / financial regulations regarding data handling and auditability."

### Q: How does real-world offline UPI (like UPI Lite / RBI Offline Framework) actually work?
> **Answer:**  
> "Real-world offline UPI uses a **pre-funded hardware wallet model (UPI Lite)**:
> - The user loads money (e.g., up to ₹2,000) from their bank account into an on-device balance while online.
> - The balance is locked in a **Secure Element (SE) / eSIM / Trusted Execution Environment (TEE)** on the smartphone.
> - When offline, the payment uses cryptographic counters signed by the device's hardware key, guaranteeing the funds exist and cannot be double-spent, even before reaching the bank's core ledger."

---

## 3. Deep Technical & Cryptography Questions

### Q: Why did you use Hybrid Encryption (RSA + AES) instead of just RSA?
> **Answer:**  
> "RSA is an asymmetric cipher based on integer factorization and has two major constraints:
> 1. **Data Size Limit:** A 2048-bit RSA key with OAEP padding can only encrypt payloads up to ~214 bytes ($256 - 2 \times 32 - 2$). A JSON payment instruction with signatures, nonces, and metadata easily exceeds this limit.
> 2. **Computational Cost:** RSA encryption and decryption are orders of magnitude slower and more CPU-intensive than symmetric ciphers.
> 
> **Hybrid pattern:** We generate a fresh, ephemeral **AES-256 key** for each packet, encrypt the arbitrary-length JSON payload with **AES-256-GCM**, and then encrypt only the 32-byte AES key using **RSA-OAEP**. This gives us the key-distribution benefits of asymmetric cryptography with the speed and flexibility of symmetric encryption."

### Q: Why AES-GCM specifically instead of AES-CBC?
> **Answer:**  
> "AES-GCM is an **Authenticated Encryption with Associated Data (AEAD)** cipher.  
> With AES-CBC, encryption only guarantees confidentiality, not integrity; an attacker can manipulate ciphertext bits (malleability attacks or padding oracle attacks).  
> AES-GCM computes a 128-bit authentication tag alongside the ciphertext. If an intermediate peer flips even a single bit in the ciphertext, decryption immediately throws an authentication tag error and the packet is discarded before touching the database."

### Q: Why is the idempotency key `SHA-256(ciphertext)` instead of `packetId`?
> **Answer:**  
> "Because `packetId` is in the unencrypted outer header. A malicious intermediate node could forward the exact same payment with a modified `packetId`, which would bypass deduplication if we keyed on `packetId`.  
> Conversely, the ciphertext is immutable and cryptographically bound to the payment instruction. Two copies of the same transaction packet will always produce the exact same SHA-256 ciphertext hash. By claiming this hash atomically before decryption, we drop duplicate bridge uploads in O(1) time without wasting CPU on RSA decryption."

### Q: How do you prevent replay attacks?
> **Answer:**  
> "Two complementary layers:
> 1. **Inside the encrypted payload**, the sender includes an ephemeral `nonce` (UUID) and a `signedAt` epoch timestamp.
> 2. When decrypted, the backend enforces a **freshness window** (e.g., rejects packets older than 24 hours or with future timestamps outside clock-skew tolerance).
> 3. Even within that 24-hour window, any replayed copy of the packet will have the identical ciphertext hash and will be caught by the idempotency cache."

### Q: How does the idempotency claim work concurrently?
> **Answer:**  
> "In Python, we use a thread-safe atomic lock over an in-memory dictionary. In production, this maps directly to **Redis `SET key NX EX 86400`** (Set if Not eXists with 24h expiration). If three bridge nodes simultaneously POST the same packet upon getting 4G, only the first request claims the key; the other two immediately receive `DUPLICATE_DROPPED`."

---

## 4. System Design & Behavioral Questions

### Q: What was the hardest bug you ran into during this project?
> **Answer:**  
> "The most subtle issue was handling **concurrent duplicate flushes**. When multiple bridge devices held the same packet and flushed concurrently, standard non-atomic checks (`if key in dict: ... dict[key] = val`) created a race condition where two threads would both see the key as absent and debit the sender twice.  
> I fixed this by ensuring the claim operation is strictly atomic (compare-and-set pattern), backed up by a database unique constraint on the transaction's packet hash as defense-in-depth."

### Q: If you had to scale this backend to 100,000 payments per second, what would you change?
> **Answer:**  
> 1. **Distributed Idempotency:** Replace in-memory locking with a Redis Cluster using consistent hashing on the ciphertext hash.
> 2. **Asynchronous Ingestion:** Have the `/api/bridge/ingest` endpoint write packets to an Apache Kafka partition keyed by sender VPA, allowing worker pools to decrypt and settle concurrently without ledger race conditions.
> 3. **HSM Decryption:** Offload RSA key decryption to Hardware Security Modules (AWS CloudHSM or Vault).
> 4. **Partitioned DB Ledger:** Shard bank account tables by account ID / bank branch with distributed transactions or Saga orchestration for inter-bank transfers.
