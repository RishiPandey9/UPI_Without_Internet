import base64
import logging
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

log = logging.getLogger(__name__)


class ServerKeyHolder:
    """
    Holds the server's RSA keypair (2048-bit).
    In production, this would reside in an HSM or KMS.
    """
    def __init__(self):
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        self._public_key = self._private_key.public_key()
        log.info(
            "Server RSA keypair generated (2048-bit). Public key fingerprint: %s...",
            self.get_public_key_base64()[:32]
        )

    @property
    def private_key(self) -> rsa.RSAPrivateKey:
        return self._private_key

    @property
    def public_key(self) -> rsa.RSAPublicKey:
        return self._public_key

    def get_public_key_base64(self) -> str:
        """Returns X.509 SubjectPublicKeyInfo in DER format, Base64-encoded (compatible with Java)."""
        der = self._public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return base64.b64encode(der).decode('ascii')
