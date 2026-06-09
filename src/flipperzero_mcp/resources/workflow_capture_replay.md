# Workflow: Capture and replay (SubGHz / NFC / RFID / IR)

Capture commands are streaming: `subghz rx`, `ir rx`, and friends never return to the `>:` prompt and so are NOT usable via `flipperzero_cli_exec` (it will time out with partial output). Use the Flipper UI or saved files for capture in this release.

Replaying or transmitting (`subghz tx`, `ir tx`, `rfid write`, `ikey write`) is gated behind two independent controls: the server operator must set `FLIPPER_ENABLE_TX_TOOLS=true` **and** the call must pass `i_accept_responsibility=true`. With either missing, `flipperzero_cli_exec` refuses the command. Transmitting outside permitted frequencies/power is illegal in most regions and is the operator's responsibility.

**Region default: US (FCC ISM, 902–928 MHz).** Runbook examples assume the US 902–928 MHz band. This is documentation only — the server does not enforce a region or restrict frequencies. Confirm your local regulations before transmitting; EU operators typically use 433.05–434.79 / 863–870 MHz, and other regions differ. Pass the frequency explicitly on every `subghz tx`.

Typed capture/replay tools with a cancellation-aware streaming model and per-tool region/legality confirmation are future work.
