from pydantic import BaseModel, Field


class MeshPacket(BaseModel):
    """
    Over-the-wire mesh packet format hopping via BLE/mesh gossip.
    Outer fields (packetId, ttl, createdAt) are readable by intermediate nodes for routing.
    The ciphertext is hybrid-encrypted and can only be decrypted by the server.
    """
    packetId: str = Field(..., description="UUID for intermediate deduplication")
    ttl: int = Field(5, ge=0, description="Hops remaining")
    createdAt: int = Field(..., description="Epoch millis timestamp")
    ciphertext: str = Field(..., description="Base64 encoded hybrid encrypted blob")

    def model_dump_dict(self) -> dict:
        return {
            "packetId": self.packetId,
            "ttl": self.ttl,
            "createdAt": self.createdAt,
            "ciphertext": self.ciphertext
        }
