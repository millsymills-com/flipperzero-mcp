from flipperzero_mcp.transport.base import FlipperTransport


class ChunkTransport(FlipperTransport):
    """Concrete transport that yields canned chunks from a list."""

    def __init__(self, chunks):
        super().__init__({})
        self._chunks = list(chunks)

    async def connect(self):
        return True

    async def disconnect(self):
        self.connected = False

    async def send(self, data):
        pass

    async def receive(self, timeout=None):  # noqa: ARG002
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    async def is_connected(self):
        return self.connected


async def test_receive_exact_assembles_across_chunks_and_buffers_remainder():
    t = ChunkTransport([b"ab", b"cd", b"efgh"])
    assert await t.receive_exact(5) == b"abcde"
    # The leftover "fgh" was buffered and is returned without another receive.
    assert await t.receive_exact(3) == b"fgh"


async def test_receive_exact_times_out_returns_empty():
    t = ChunkTransport([])  # receive() always yields b""
    assert await t.receive_exact(4, timeout=0.01) == b""


async def test_receive_exact_zero_returns_empty():
    t = ChunkTransport([b"abc"])
    assert await t.receive_exact(0) == b""


async def test_clear_receive_buffer_empties_buffer():
    t = ChunkTransport([b"abcdef"])
    assert await t.receive_exact(2) == b"ab"
    t.clear_receive_buffer()
    assert len(t._rx_buffer) == 0


def test_get_name_strips_transport_suffix():
    t = ChunkTransport([])
    assert t.get_name() == "Chunk"
