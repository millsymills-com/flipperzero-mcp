# Workflow: Capture and replay (SubGHz / NFC / RFID / IR)

Capture commands are streaming: `subghz rx`, `ir rx`, and friends never return to the `>:` prompt and so are NOT usable via `flipperzero_cli_exec` (it will time out with partial output). Use the Flipper UI or saved files for capture in this release.

Replaying or transmitting (`subghz tx`, `ir tx`, `rfid write`, `ikey write`) is gated behind two independent controls: the server operator must set `FLIPPER_ENABLE_TX_TOOLS=true` **and** the call must pass `i_accept_responsibility=true`. With either missing, `flipperzero_cli_exec` refuses the command. Transmitting outside permitted frequencies/power is illegal in most regions and is the operator's responsibility.

Typed capture/replay tools with a cancellation-aware streaming model and per-tool region/legality confirmation are future work.
