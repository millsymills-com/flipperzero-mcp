"""Human-readable messages for SystemUpdate result codes."""

from __future__ import annotations

from flipperzero_mcp.rpc.protobuf_gen import system_pb2

_MESSAGES = {
    system_pb2.UpdateResponse.ManifestPathInvalid: "update manifest path is invalid",
    system_pb2.UpdateResponse.ManifestFolderNotFound: "update folder not found on device",
    system_pb2.UpdateResponse.ManifestInvalid: "update manifest is invalid or corrupt",
    system_pb2.UpdateResponse.StageMissing: "an update stage file is missing from the bundle",
    system_pb2.UpdateResponse.StageIntegrityError: "an update stage failed its integrity check",
    system_pb2.UpdateResponse.ManifestPointerError: "update manifest pointer error",
    system_pb2.UpdateResponse.TargetMismatch: "bundle hardware target does not match the device",
    system_pb2.UpdateResponse.OutdatedManifestVersion: "update manifest version is outdated",
    system_pb2.UpdateResponse.IntFull: "device internal storage is full",
    system_pb2.UpdateResponse.UnspecifiedError: "unspecified update error",
}


def update_code_message(code: int) -> str | None:
    """Return an actionable message for a non-OK update code, or None for OK.

    Args:
        code: An ``UpdateResponse.UpdateResultCode`` integer.

    Returns:
        None when ``code`` is OK; otherwise a human-readable explanation.
    """
    if code == system_pb2.UpdateResponse.OK:
        return None
    return _MESSAGES.get(code, f"update failed (code {code})")
