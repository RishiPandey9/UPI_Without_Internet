import threading
from typing import Dict, List
from app.model.mesh_packet import MeshPacket


class VirtualDevice:
    """
    Simulated phone device in the offline BLE mesh network.
    Holds mesh packets it has received via gossip.
    """
    def __init__(self, device_id: str, has_internet: bool):
        self.device_id = device_id
        self.has_internet = has_internet
        self._held_packets: Dict[str, MeshPacket] = {}
        self._lock = threading.Lock()

    def hold(self, packet: MeshPacket) -> None:
        with self._lock:
            if packet.packetId not in self._held_packets:
                self._held_packets[packet.packetId] = packet

    def get_held_packets(self) -> List[MeshPacket]:
        with self._lock:
            return list(self._held_packets.values())

    def holds(self, packet_id: str) -> bool:
        with self._lock:
            return packet_id in self._held_packets

    def packet_count(self) -> int:
        with self._lock:
            return len(self._held_packets)

    def clear(self) -> None:
        with self._lock:
            self._held_packets.clear()
