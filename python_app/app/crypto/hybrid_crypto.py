import base64
import hashlib
import json
import os
from typing import Optional
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.crypto.server_key import ServerKeyHolder
from app.model.payment_instruction import PaymentInstruction


class HybridCryptoService:
    """
    Hybrid encryption matching the Java implementation:
      - Generates ephemeral AES-256 key per packet
      - Encrypts JSON payload with AES-256-GCM (12-byte IV, 16-byte tag)
      - Encrypts AES key with RSA-OAEP (SHA-256 + MGF1 SHA-256)
      - Wire format:
        [ 256 bytes RSA-encrypted AES key ][ 12 bytes IV ][ AES ciphertext + tag ]
        encoded as Base64.
    """
    RSA_ENCRYPTED_KEY_BYTES = 256
    GCM_IV_BYTES = 12
    GCM_TAG_BYTES = 16

    def __init__(self, server_key: ServerKeyHolder):
        self.server_key = server_key

    def encrypt(self, instruction: PaymentInstruction, public_key: Optional[rsa.RSAPublicKey] = None) -> str:
        """
        Encrypt a payment instruction using hybrid RSA-OAEP + AES-256-GCM.
        Simulates the sender's phone encrypting with the server's public key.
        """
        if public_key is None:
            public_key = self.server_key.public_key

        payload_bytes = json.dumps(instruction.to_dict()).encode('utf-8')

        # 1. Ephemeral AES-256 key
        aes_key = AESGCM.generate_key(bit_length=256)
        aesgcm = AESGCM(aes_key)

        # 2. AES-256-GCM encryption
        iv = os.urandom(self.GCM_IV_BYTES)
        aes_ciphertext = aesgcm.encrypt(iv, payload_bytes, None)

        # 3. RSA-OAEP encryption of AES key
        encrypted_aes_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # 4. Pack into single buffer: [RSA Encrypted Key][IV][AES Ciphertext + Tag]
        packed = encrypted_aes_key + iv + aes_ciphertext
        return base64.b64encode(packed).decode('ascii')

    def decrypt(self, base64_ciphertext: str) -> PaymentInstruction:
        """
        Decrypt and verify the ciphertext with the server's RSA private key.
        Tampered or malformed payload will raise ValueError or InvalidTag.
        """
        raw = base64.b64decode(base64_ciphertext)
        min_len = self.RSA_ENCRYPTED_KEY_BYTES + self.GCM_IV_BYTES + self.GCM_TAG_BYTES
        if len(raw) < min_len:
            raise ValueError(f"Ciphertext too short ({len(raw)} bytes < {min_len})")

        # Unpack wire format
        encrypted_aes_key = raw[:self.RSA_ENCRYPTED_KEY_BYTES]
        iv = raw[self.RSA_ENCRYPTED_KEY_BYTES:self.RSA_ENCRYPTED_KEY_BYTES + self.GCM_IV_BYTES]
        aes_ciphertext = raw[self.RSA_ENCRYPTED_KEY_BYTES + self.GCM_IV_BYTES:]

        # 1. Decrypt AES key using server RSA private key
        aes_key = self.server_key.private_key.decrypt(
            encrypted_aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # 2. Decrypt payload with AES-GCM and verify auth tag
        aesgcm = AESGCM(aes_key)
        plaintext = aesgcm.decrypt(iv, aes_ciphertext, None)

        data = json.loads(plaintext.decode('utf-8'))
        return PaymentInstruction.from_dict(data)

    @staticmethod
    def hash_ciphertext(base64_ciphertext: str) -> str:
        """
        SHA-256 of the base64 ciphertext string.
        Used as the globally unique idempotency key across all mesh nodes.
        """
        return hashlib.sha256(base64_ciphertext.encode('utf-8')).hexdigest()
