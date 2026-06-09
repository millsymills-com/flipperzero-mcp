"""Unit tests for verified bundle downloads."""

import hashlib
import io
import json
import tarfile

import pytest

from flipperzero_mcp.firmware.bundles import BundleError, download_bundle
from flipperzero_mcp.firmware.flavor import FirmwareFlavor


def _tgz_bytes():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in {"upd/update.fuf": b"manifest", "upd/firmware.dfu": b"DFU"}.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_official_download_verifies_sha256(httpx_mock, tmp_path):
    tgz = _tgz_bytes()
    sha = hashlib.sha256(tgz).hexdigest()
    directory = {
        "channels": [
            {
                "id": "release",
                "versions": [
                    {
                        "version": "1.4.3",
                        "files": [
                            {
                                "url": "https://up.example/flipper-z-f7-update-1.4.3.tgz",
                                "target": "f7",
                                "type": "update_tgz",
                                "sha256": sha,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    httpx_mock.add_response(
        url="https://update.flipperzero.one/firmware/directory.json", text=json.dumps(directory)
    )
    httpx_mock.add_response(url="https://up.example/flipper-z-f7-update-1.4.3.tgz", content=tgz)
    bundle = await download_bundle(
        FirmwareFlavor.OFFICIAL, channel="release", version="latest", target="f7"
    )
    assert bundle.target == "f7"


@pytest.mark.asyncio
async def test_official_download_aborts_on_sha256_mismatch(httpx_mock):
    tgz = _tgz_bytes()
    directory = {
        "channels": [
            {
                "id": "release",
                "versions": [
                    {
                        "version": "1.4.3",
                        "files": [
                            {
                                "url": "https://up.example/x.tgz",
                                "target": "f7",
                                "type": "update_tgz",
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    httpx_mock.add_response(
        url="https://update.flipperzero.one/firmware/directory.json", text=json.dumps(directory)
    )
    httpx_mock.add_response(url="https://up.example/x.tgz", content=tgz)
    with pytest.raises(BundleError, match="sha256"):
        await download_bundle(
            FirmwareFlavor.OFFICIAL, channel="release", version="latest", target="f7"
        )
