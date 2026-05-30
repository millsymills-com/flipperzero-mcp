import pytest

from flipperzero_mcp.errors import FlipperNotConnectedError
from flipperzero_mcp.tools import _common


class FakeCtx:
    def __init__(self, context):
        self.lifespan_context = context


class FakeContextObj:
    def __init__(self, client):
        self.client = client


class FakeClient:
    def __init__(self, *, up, reconnects_to, is_connected_raises=None):
        self._up = up
        self._reconnects_to = reconnects_to
        self.disconnect_calls = 0
        self.connect_calls = 0
        self.last_connection_error: str | None = None

        class _T:
            async def is_connected(self):
                if is_connected_raises is not None:
                    raise is_connected_raises
                return up

        self.transport = _T()

    async def disconnect(self):
        self.disconnect_calls += 1

    async def connect(self):
        self.connect_calls += 1
        return self._reconnects_to


async def test_ensure_connected_passes_when_up():
    client = FakeClient(up=True, reconnects_to=True)
    ctx = FakeCtx(FakeContextObj(client))
    await _common.ensure_connected(ctx)
    assert client.connect_calls == 0


async def test_ensure_connected_reconnects_once_then_ok():
    client = FakeClient(up=False, reconnects_to=True)
    ctx = FakeCtx(FakeContextObj(client))
    await _common.ensure_connected(ctx)
    assert client.disconnect_calls == 1
    assert client.connect_calls == 1


async def test_ensure_connected_raises_when_reconnect_fails():
    client = FakeClient(up=False, reconnects_to=False)
    ctx = FakeCtx(FakeContextObj(client))
    with pytest.raises(FlipperNotConnectedError):
        await _common.ensure_connected(ctx)


@pytest.mark.parametrize("exc", [OSError("io"), RuntimeError("loop")])
async def test_ensure_connected_reconnects_when_is_connected_raises(exc):
    client = FakeClient(up=True, reconnects_to=True, is_connected_raises=exc)
    ctx = FakeCtx(FakeContextObj(client))
    await _common.ensure_connected(ctx)
    assert client.disconnect_calls == 1
    assert client.connect_calls == 1
