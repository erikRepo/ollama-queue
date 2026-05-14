"""Wake-on-LAN magic packet construction and transmission."""

import logging
import socket

logger = logging.getLogger(__name__)

_MAC_BYTE_LENGTH = 6
_MAC_REPETITIONS = 16


def build_magic_packet(mac: str) -> bytes:
    """Build a Wake-on-LAN magic packet for *mac*.

    Args:
        mac: MAC address in colon- or dash-separated hex notation,
             e.g. ``"AA:BB:CC:DD:EE:FF"`` or ``"AA-BB-CC-DD-EE-FF"``.

    Returns:
        102-byte magic packet (6 × 0xFF header + MAC repeated 16 times).

    Raises:
        ValueError: if *mac* is not a valid 6-octet hex address.
    """
    clean = mac.replace(":", "").replace("-", "")
    if len(clean) != _MAC_BYTE_LENGTH * 2:
        raise ValueError(f"Invalid MAC address: {mac!r}")
    try:
        mac_bytes = bytes.fromhex(clean)
    except ValueError:
        raise ValueError(f"Invalid MAC address: {mac!r}") from None
    return b"\xff" * _MAC_BYTE_LENGTH + mac_bytes * _MAC_REPETITIONS


def send_wol(mac: str, broadcast: str, port: int) -> None:
    """Send a Wake-on-LAN magic packet over UDP.

    Args:
        mac: Target MAC address (colon- or dash-separated hex).
        broadcast: UDP broadcast address, e.g. ``"255.255.255.255"``.
        port: UDP port (typically 7 or 9).

    Raises:
        ValueError: if *mac* is invalid.
        OSError: if the packet cannot be sent.
    """
    packet = build_magic_packet(mac)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
        logger.info("WoL packet sent to MAC=%s via %s:%d", mac, broadcast, port)
    finally:
        sock.close()
