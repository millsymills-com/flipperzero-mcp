# Protobuf RPC

This project includes a protobuf-based RPC implementation for Flipper Zero in `flipperzero_mcp.rpc.protobuf_rpc.ProtobufRPC`.

## Generated protobuf code

The generated Python protobuf modules are committed under:

- `src/flipperzero_mcp/rpc/protobuf_gen/`

The `.proto` sources are in:

- `proto/`

## Framing

Flipper firmware uses nanopb delimited framing for RPC messages:

- each message is encoded as `[varint length][protobuf bytes]`

This is different from a fixed 4-byte length prefix.

The transport abstraction provides `receive_exact()` and buffering (`FlipperTransport._rx_buffer`) so protobuf decoding can reliably read framed messages.

## Entering RPC session mode (USB CDC)

On typical firmware, the USB CDC port starts in CLI mode. The protobuf RPC implementation switches the same connection to RPC mode by sending:

- `start_rpc_session\r`

Important details implemented in `ProtobufRPC`:

- the command is terminated with `\r` (CR-only), not `\r\n`
- the host drains any CLI banner/echo output before reading RPC frames
- there is a best-effort probe to detect whether the device is already in RPC mode

## Debugging controls

- `FLIPPER_DEBUG`: print protobuf send/receive debug logs
- `FLIPPER_FORCE_START_RPC_SESSION`: force sending `start_rpc_session` even if probing suggests RPC mode is already active
