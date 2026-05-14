"""Unit tests for wol.py — Wake-on-LAN magic packet."""

import socket
from unittest.mock import MagicMock, patch

import pytest

from server.wol import build_magic_packet, send_wol


class TestBuildMagicPacket:
    """Tests for build_magic_packet."""

    def test_length(self) -> None:
        """Magic packet must be exactly 102 bytes (6 + 16*6)."""
        pkt = build_magic_packet("AA:BB:CC:DD:EE:FF")
        assert len(pkt) == 102

    def test_header(self) -> None:
        """First 6 bytes must be 0xFF."""
        pkt = build_magic_packet("AA:BB:CC:DD:EE:FF")
        assert pkt[:6] == b"\xff" * 6

    def test_mac_repeated_16_times(self) -> None:
        """MAC bytes must appear 16 times after the header."""
        mac_bytes = bytes.fromhex("AABBCCDDEEFF")
        pkt = build_magic_packet("AA:BB:CC:DD:EE:FF")
        payload = pkt[6:]
        assert payload == mac_bytes * 16

    def test_dash_separator(self) -> None:
        """MAC address with dash separators must be accepted."""
        pkt_colon = build_magic_packet("AA:BB:CC:DD:EE:FF")
        pkt_dash = build_magic_packet("AA-BB-CC-DD-EE-FF")
        assert pkt_colon == pkt_dash

    def test_lowercase_mac(self) -> None:
        """Lowercase MAC must produce the same packet as uppercase."""
        pkt_upper = build_magic_packet("AA:BB:CC:DD:EE:FF")
        pkt_lower = build_magic_packet("aa:bb:cc:dd:ee:ff")
        assert pkt_upper == pkt_lower

    def test_invalid_mac_raises(self) -> None:
        """Non-hex or wrong-length MAC must raise ValueError."""
        with pytest.raises(ValueError):
            build_magic_packet("ZZ:BB:CC:DD:EE:FF")

    def test_too_short_mac_raises(self) -> None:
        """MAC with fewer than 6 octets must raise ValueError."""
        with pytest.raises(ValueError):
            build_magic_packet("AA:BB:CC:DD:EE")


class TestSendWol:
    """Tests for send_wol."""

    def test_sends_to_correct_address(self) -> None:
        """send_wol must send the magic packet to (broadcast, port)."""
        mock_sock = MagicMock()
        with patch("server.wol.socket.socket", return_value=mock_sock):
            send_wol("AA:BB:CC:DD:EE:FF", broadcast="192.168.1.255", port=9)

        expected_pkt = build_magic_packet("AA:BB:CC:DD:EE:FF")
        mock_sock.sendto.assert_called_once_with(expected_pkt, ("192.168.1.255", 9))

    def test_socket_broadcast_option_set(self) -> None:
        """send_wol must enable SO_BROADCAST on the socket."""
        mock_sock = MagicMock()
        with patch("server.wol.socket.socket", return_value=mock_sock):
            send_wol("AA:BB:CC:DD:EE:FF", broadcast="255.255.255.255", port=9)

        mock_sock.setsockopt.assert_called_once_with(
            socket.SOL_SOCKET, socket.SO_BROADCAST, 1
        )

    def test_socket_closed_after_send(self) -> None:
        """send_wol must close the socket even on success."""
        mock_sock = MagicMock()
        with patch("server.wol.socket.socket", return_value=mock_sock):
            send_wol("AA:BB:CC:DD:EE:FF", broadcast="255.255.255.255", port=9)

        mock_sock.close.assert_called_once()

    def test_socket_closed_on_error(self) -> None:
        """send_wol must close the socket even if sendto raises."""
        mock_sock = MagicMock()
        mock_sock.sendto.side_effect = OSError("network error")
        with patch("server.wol.socket.socket", return_value=mock_sock):
            with pytest.raises(OSError):
                send_wol("AA:BB:CC:DD:EE:FF", broadcast="255.255.255.255", port=9)

        mock_sock.close.assert_called_once()
