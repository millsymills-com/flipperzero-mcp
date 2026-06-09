"""Resolve firmware update bundles from local files or upstream downloads."""

from __future__ import annotations

import logging
import re
import tarfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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


def _extract_members(tgz_path: str) -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    with tarfile.open(tgz_path, "r:gz") as tar:  # nosec B202 — extractfile reads into memory, no disk write
        members = [m for m in tar.getmembers() if m.isfile()]
        if not members:
            raise BundleError("bundle archive is empty")
        prefix = members[0].name.split("/", 1)[0] + "/"
        for member in members:
            rel = member.name.removeprefix(prefix)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            files.append((rel, extracted.read()))
    return files


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
    files = _extract_members(tgz_path)
    if not any(rel == _MANIFEST for rel, _ in files):
        raise BundleError(f"bundle has no {_MANIFEST} manifest")
    return LocalBundle(manifest_name=_MANIFEST, target=target, files=files)
