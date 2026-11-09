# Claude settings guard

This dependency-free Python 3.10+ check reduces accidental credential disclosure
through Claude Code permission files. The checker and tests share one implementation
across the repositories adopting this guard; repository formatting and narrow
lint annotations may differ. Changes should be rolled out with the same tests.

## What is checked

- Tracked `.claude/settings.local.json` files are rejected at every nesting depth,
  even when empty or symlinks. The repository ignore rule helps prevent ordinary
  additions; the guard also catches force-added files.
- Shared `.claude/settings.json` files and the root `settings.json` template are
  checked for known credential formats, private keys, credential-valued JSON keys,
  URLs containing passwords, and common command-line passwords/auth headers.
- Unreadable or oversized settings, malformed/duplicate-key JSON, unresolved
  index entries and shared-settings symlinks fail closed. Symlinks are not followed.
- Diagnostics contain paths and reason categories, never settings values. The
  guard does not connect to services or test credentials.

## Run locally

```sh
python3 -m unittest discover -s .github/security -p test_claude_settings.py
python3 .github/security/check_claude_settings.py --staged
python3 .github/security/check_claude_settings.py --head "$(git rev-parse HEAD)"
```

The default mode reads the **Git index**, not working-tree content, so partially
staged files are checked as they would be committed. Untracked personal settings
are deliberately not read. Existing pre-commit configurations invoke this mode;
the hook runs only on machines where those configurations are installed.

CI passes full head/base commit hashes and fetches complete history. The target
tree and both sides of changes in `base..head` are checked. A credential added and
then removed in the incoming history still fails. Missing, zero or unavailable
base hashes fall back to all history reachable from the head; shallow clones fail
rather than claim a complete scan. These are ordinary CI checks, not newly enabled
branch-protection requirements.

## If the guard fails

Review the named file privately. If a credential was published, rotate/revoke it
before removing it and coordinating any necessary history/fork cleanup. Never
paste its value into an issue or CI log. Stop tracking local settings and keep the
ignore rule. Shared settings should refer to secrets with simple environment
variables such as `$API_TOKEN` or `${API_TOKEN}` rather than literal values.

The scanner is deliberately focused and heuristic. It cannot recognize every
custom credential, encoding, shell-language construction or copied/exported log.
It complements general secret scanning and review; a pass is not proof that a
repository, all external forks, or package/image artifacts contain no secrets.
