import logging
from typing import Dict, List, NamedTuple
from app.model.mesh_packet import MeshPacket
from app.service.virtual_device import VirtualDevice

log = logging.getLogger(__name__)


class GossipResult(NamedTuple):
    transfers: int
    device_counts: Dict[str, int]


class BridgeUpload(NamedTuple):
    bridge_node_id: str
    packet: MeshPacket


class MeshSimulatorService:
    """
    Simulates the Bluetooth mesh gossip protocol and multi-hop routing.
    In a real system, packets are exchanged peer-to-peer over BLE GATT.
    """
    def __init__(self):
        self._devices: Dict[str, VirtualDevice] = {}
        self.seed_default_devices()

    def seed_default_devices(self) -> None:
        self._devices = {
            "phone-alice": VirtualDevice("phone-alice", has_internet=False),
            "phone-stranger1": VirtualDevice("phone-stranger1", has_internet=False),
            "phone-stranger2": VirtualDevice("phone-stranger2", has_internet=False),
            "phone-stranger3": VirtualDevice("phone-stranger3", has_internet=False),
            "phone-bridge": VirtualDevice("phone-bridge", has_internet=True),
        }

    def get_devices(self) -> List[VirtualDevice]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> VirtualDevice:
        dev = self._devices.get(device_id)
        if not dev:
            raise ValueError(f"Unknown device: {device_id}")
        return dev

    def inject(self, sender_device_id: str, packet: MeshPacket) -> None:
        dev = self.get_device(sender_device_id)
        dev.hold(packet)
        log.info(
            "Packet %s injected at %s (TTL=%s)",
            packet.packetId[:8], sender_device_id, packet.ttl
        )

    def gossip_once(self) -> GossipResult:
        """
        Executes one gossip round across all devices in range.
        TTL decrements by 1 each hop. Packets with TTL <= 0 are not forwarded further.
        """
        transfers = 0
        device_list = list(self._devices.values())

        # Snapshot held packets to prevent instant propagation across 5 hops in 1 step
        snapshot = {d.device_id: d.get_held_packets() for d in device_list}

        for src in device_list:
            for pkt in snapshot.get(src.device_id, []):
                if pkt.ttl <= 0:
                    continue
                for dst in device_list:
                    if dst == src:
                        continue
                    if dst.holds(pkt.packetId):
                        continue
                    # Create decremented copy
                    copy_pkt = MeshPacket(
                        packetId=pkt.packetId,
                        ttl=pkt.ttl - 1,
                        createdAt=pkt.createdAt,
                        ciphertext=pkt.ciphertext
                    )
                    dst.hold(copy_pkt)
                    transfers += 1

        log.info("Gossip round complete: %s packet transfers", transfers)
        return GossipResult(transfers, self.snapshot_map())

    def snapshot_map(self) -> Dict[str, int]:
        return {d.device_id: d.packet_count() for d in self._devices.values()}

    def collect_bridge_uploads(self) -> List[BridgeUpload]:
        """
        Gathers all packets from devices with internet connectivity (bridge nodes).
        Simulates them walking outside and getting cellular data.
        """
        uploads: List[BridgeUpload] = []
        for d in self._devices.values():
            if not d.has_internet:
                continue
            for pkt in d.get_held_packets():
                uploads.append(BridgeUpload(bridge_node_id=d.device_id, packet=pkt))
        return uploads

    def reset_mesh(self) -> None:
        for d in self._devices.values():
            d.clear()
