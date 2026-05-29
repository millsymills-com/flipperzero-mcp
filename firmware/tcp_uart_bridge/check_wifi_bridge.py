#!/usr/bin/env python3
"""
Quick sanity check for the ESP32-S2 TCP↔UART bridge + Flipper Protobuf RPC.

Usage (from firmware/tcp_uart_bridge):
  export FLIPPER_WIFI_HOST=<DEVBOARD_IP>
  export FLIPPER_WIFI_PORT=8080
  python3 check_wifi_bridge.py
"""

import asyncio
import os
import sys
from pathlib import Path


def _ensure_repo_imports() -> None:
    """
    Allow running this script directly from the repo without installation.
    """
    repo_root = Path(__file__).resolve().parents[2]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


async def main() -> int:
    _ensure_repo_imports()

    from flipper_mcp.core.transport.wifi import WiFiTransport
    from flipper_mcp.core.protobuf_rpc import ProtobufRPC

    host = (os.environ.get("FLIPPER_WIFI_HOST") or "").strip()
    port_str = (os.environ.get("FLIPPER_WIFI_PORT") or "8080").strip()

    if not host:
        print("❌ FLIPPER_WIFI_HOST is not set.")
        print("   Example: export FLIPPER_WIFI_HOST=192.168.1.100")
        return 2

    try:
        port = int(port_str)
    except ValueError:
        print(f"❌ FLIPPER_WIFI_PORT must be an integer, got: {port_str!r}")
        return 2

    transport = WiFiTransport(
        {
            "host": host,
            "port": port,
            "connect_timeout": 3.0,
            "read_chunk_size": 4096,
        }
    )

    print(f"Connecting to bridge: {host}:{port} ...")
    if not await transport.connect():
        print("❌ tcp_connected=False")
        print("rpc_responsive=False")
        return 1

    try:
        rpc = ProtobufRPC(transport)
        echoed = await rpc.ping(b"mcp")
        rpc_ok = bool(echoed == b"mcp")
        print("✅ tcp_connected=True")
        print(f"rpc_responsive={str(rpc_ok)}")
        if not rpc_ok:
            print("   (Ping did not echo expected bytes; check UART/firmware/Flipper state.)")
            return 1
        return 0
    finally:
        try:
            await transport.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
