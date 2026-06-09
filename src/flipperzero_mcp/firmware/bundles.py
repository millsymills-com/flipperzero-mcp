"""Resolve firmware update bundles from local files or upstream downloads."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from dataclasses import dataclass
from typing import Any

import httpx

from flipperzero_mcp.firmware.flavor import FirmwareFlavor

_MANIFEST = "update.fuf"
_TARGET_RE = re.compile(r"flipper-z-(f\w+)-update", re.IGNORECASE)


class BundleError(RuntimeError):
    """Raised when a bundle cannot be resolved or is malformed."""


@dataclass(frozen=True)
class LocalBundle:
    """An extracted update bundle ready to push to the device."""

    manifest_name: str
    target: str
    files: list[tuple[str, bytes]]


def _target_from_name(name: str) -> str:
    match = _TARGET_RE.search(name)
    if not match:
        raise BundleError(f"cannot determine hardware target from bundle name {name!r}")
    return match.group(1).lower()


def _members_from_tar(tar: tarfile.TarFile) -> list[tuple[str, bytes]]:
    members = [m for m in tar.getmembers() if m.isfile()]
    if not members:
        raise BundleError("bundle archive is empty")
    prefix = members[0].name.split("/", 1)[0] + "/"
    files: list[tuple[str, bytes]] = []
    for member in members:
        rel = member.name.removeprefix(prefix)
        if rel.startswith("/") or ".." in rel.split("/"):
            raise BundleError(f"unsafe path in bundle: {member.name!r}")
        extracted = tar.extractfile(member)
        if extracted is None:
            continue
        files.append((rel, extracted.read()))
    return files


def _build_bundle(files: list[tuple[str, bytes]], target: str) -> LocalBundle:
    if not any(rel == _MANIFEST for rel, _ in files):
        raise BundleError(f"bundle has no {_MANIFEST} manifest")
    return LocalBundle(manifest_name=_MANIFEST, target=target, files=files)


def load_local_bundle(tgz_path: str) -> LocalBundle:
    """Load and validate a local update ``.tgz`` bundle.

    Args:
        tgz_path: Host path to a ``flipper-z-<target>-update-*.tgz`` file.

    Returns:
        A LocalBundle with the manifest name, hardware target, and member files.

    Raises:
        BundleError: If the target is unknown, the archive is empty, or it has
            no ``update.fuf`` manifest.
    """
    target = _target_from_name(tgz_path)
    with tarfile.open(tgz_path, "r:gz") as tar:
        files = _members_from_tar(tar)
    return _build_bundle(files, target)


_OFFICIAL_DIRECTORY = "https://update.flipperzero.one/firmware/directory.json"
_MOMENTUM_RELEASES = "https://api.github.com/repos/Next-Flip/Momentum-Firmware/releases"


def _select_official_file(
    directory: dict[str, Any], channel: str, version: str, target: str
) -> dict[str, Any]:
    channels = {c["id"]: c for c in directory.get("channels", [])}
    if channel not in channels:
        raise BundleError(f"unknown official channel {channel!r}")
    versions = channels[channel].get("versions", [])
    if not versions:
        raise BundleError(f"no versions in official channel {channel!r}")
    picked = (
        versions[0]
        if version == "latest"
        else next((v for v in versions if v.get("version") == version), None)
    )
    if picked is None:
        raise BundleError(f"official version {version!r} not found in {channel!r}")
    for entry in picked.get("files", []):
        if entry.get("target") == target and entry.get("type") == "update_tgz":
            return entry
    raise BundleError(f"no install bundle for target {target} in official {channel}/{version}")


async def _fetch(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    return response.content


def _verify_sha256(data: bytes, expected: str) -> None:
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected.lower():
        raise BundleError(f"sha256 mismatch: expected {expected}, got {actual}")


def _bundle_from_tgz_bytes(data: bytes, target: str) -> LocalBundle:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        files = _members_from_tar(tar)
    return _build_bundle(files, target)


async def _download_official(channel: str, version: str, target: str) -> LocalBundle:
    async with httpx.AsyncClient() as client:
        directory = json.loads(await _fetch(client, _OFFICIAL_DIRECTORY))
        entry = _select_official_file(directory, channel, version, target)
        data = await _fetch(client, str(entry["url"]))
    _verify_sha256(data, str(entry["sha256"]))
    return _bundle_from_tgz_bytes(data, target)


async def _download_momentum(version: str, target: str) -> LocalBundle:
    async with httpx.AsyncClient() as client:
        releases = json.loads(await _fetch(client, _MOMENTUM_RELEASES))
        if not releases:
            raise BundleError("no Momentum releases found")
        release = (
            releases[0]
            if version == "latest"
            else next((r for r in releases if r.get("tag_name") == version), None)
        )
        if release is None:
            raise BundleError(f"Momentum release {version!r} not found")
        tag = release["tag_name"]
        asset = next(
            (
                a
                for a in release.get("assets", [])
                if a["name"] == f"flipper-z-{target}-update-{tag}.tgz"
            ),
            None,
        )
        if asset is None:
            raise BundleError(f"no {target} firmware bundle in Momentum release {tag}")
        data = await _fetch(client, asset["browser_download_url"])
    digest = asset.get("digest", "")
    if not digest.startswith("sha256:"):
        raise BundleError("Momentum asset is missing a sha256 digest")
    _verify_sha256(data, digest.split(":", 1)[1])
    return _bundle_from_tgz_bytes(data, target)


async def download_bundle(
    flavor: FirmwareFlavor, *, channel: str, version: str, target: str
) -> LocalBundle:
    """Download and verify an update bundle for ``flavor``.

    Args:
        flavor: OFFICIAL or MOMENTUM (others are local-path only).
        channel: Official channel id (ignored for Momentum).
        version: ``latest`` or an exact version/tag.
        target: Hardware target such as ``f7``.

    Returns:
        A verified LocalBundle.

    Raises:
        BundleError: On unsupported flavor, missing file, or sha256 mismatch.
    """
    if flavor is FirmwareFlavor.OFFICIAL:
        return await _download_official(channel, version, target)
    if flavor is FirmwareFlavor.MOMENTUM:
        return await _download_momentum(version, target)
    raise BundleError(f"auto-download unsupported for {flavor.value}; supply a local .tgz path")
