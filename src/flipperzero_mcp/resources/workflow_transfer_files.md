# Workflow: Transfer files

Use typed storage RPC tools when possible:

1. List a directory with `flipperzero_fs_list`.
2. Create a directory with `flipperzero_fs_mkdir` when `FLIPPER_ENABLE_WRITE_TOOLS=true`.
3. Upload a file with `flipperzero_fs_push`; it verifies local MD5 against device MD5.
4. Download a file with `flipperzero_fs_pull`; it verifies written host bytes against device MD5.

CLI equivalents are available over USB with `flipperzero_cli_exec` (`storage list`, `storage read`, `storage mkdir`, `storage md5`) but typed tools provide clearer errors and integrity checks.
