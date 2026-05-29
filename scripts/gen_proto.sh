#!/usr/bin/env bash
set -euo pipefail
# Regenerate protobuf bindings. WARNING: the protoc used here MUST emit a runtime
# version assertion matching the `protobuf` runtime pin major.minor (6.33 in pyproject),
# or the generated *_pb2.py will raise RuntimeVersionError at import. grpcio-tools
# bundles its own protoc whose version may NOT match — verify before relying on this.
OUT="src/flipperzero_mcp/rpc/protobuf_gen"
mkdir -p "$OUT"
uv run python -m grpc_tools.protoc -Iproto --python_out="$OUT" proto/*.proto
touch "$OUT/__init__.py"
uv run python - <<'PY'
import pathlib, re
out = pathlib.Path("src/flipperzero_mcp/rpc/protobuf_gen")
for f in out.glob("*_pb2.py"):
    text = f.read_text()
    f.write_text(re.sub(r'^import (\w+_pb2) as', r'from . import \1 as', text, flags=re.M))
PY
echo "Regenerated bindings in $OUT — verify import before committing."
