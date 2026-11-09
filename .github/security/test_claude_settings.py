# Copyright 2026 Andrew Mills
# Standalone stdlib tests: no package or pytest dependency is required.
# Git argv and fixture Python paths are explicit; shell execution is never used.
# ruff: noqa: S603, S607, PT009
"""Hermetic regression tests. All credential-looking values are synthetic."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FAKE = "fixture-not-a-real-credential"
SCRIPT = Path(__file__).resolve().with_name("check_claude_settings.py")
SPEC = importlib.util.spec_from_file_location("claude_settings_guard", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load sibling guard module")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class DetectorTests(unittest.TestCase):
    """Exercise literal credentials, variable references and invalid documents."""

    def test_command_credentials(self) -> None:
        """Verify command credentials."""
        commands = [
            f"PGPASSWORD={FAKE} psql -h database.example.invalid",
            f"MYSQL_PWD='{FAKE}' mysql",
            f"AWS_SECRET_ACCESS_KEY={FAKE} aws sts get-caller-identity",
            f"sshpass -p '{FAKE}' ssh host.example.invalid",
            f"mysql -h db.example.invalid -p{FAKE}",
            f"mysql --password={FAKE}",
            f"curl --token {FAKE} https://api.example.invalid",
            f"curl -u user:{FAKE} https://api.example.invalid",
            f'curl --user "user:{FAKE}" https://api.example.invalid',
            f'curl -H "Authorization: Bearer {FAKE}" https://api.example.invalid',
            f"curl -H 'Authorization: token {FAKE}' https://api.example.invalid",
            f"curl -H 'Authorization: {FAKE}' https://api.example.invalid",
            f"curl -H 'X-Api-Key: {FAKE}' https://api.example.invalid",
            f"psql postgres://user:{FAKE}@db.example.invalid/db",
            f"PGPASSWORD=''{FAKE} psql",
            f'PGPASSWORD="$TOKEN"{FAKE} psql',
            f"curl --token ''{FAKE} https://api.example.invalid",
        ]
        for command in commands:
            with self.subTest(command=command):
                content = json.dumps({"permissions": {"allow": [f"Bash({command})"]}})
                self.assertTrue(guard.settings_findings(content.encode()))

    def test_variable_references(self) -> None:
        """Verify variable references."""
        commands = [
            'PGPASSWORD="$DB_PASSWORD" psql',
            "PGPASSWORD=${DB_PASSWORD} psql",
            'sshpass -p "$SSH_PASSWORD" ssh host.example.invalid',
            'curl -H "Authorization: Bearer $API_TOKEN" https://api.example.invalid',
            "curl -H 'X-Api-Key: ${API_KEY}' https://api.example.invalid",
            "curl -u user:$PASSWORD https://api.example.invalid",
            "psql postgres://user:${PASSWORD}@db.example.invalid/db",
            "npm run test:*",
        ]
        for command in commands:
            with self.subTest(command=command):
                content = json.dumps({"permissions": {"allow": [f"Bash({command})"]}})
                self.assertFalse(guard.settings_findings(content.encode()))

    def test_only_simple_references_are_exempt(self) -> None:
        """Verify only simple references are exempt."""
        for value in [f"${{TOKEN:-{FAKE}}}", f"$TOKEN{FAKE}", f"$(echo {FAKE})"]:
            with self.subTest(value=value):
                self.assertFalse(guard.is_reference(value))

    def test_credential_env_and_camelcase_keys(self) -> None:
        """Verify credential env and camelcase keys."""
        for name in ["API_KEY", "GANDI_API_KEY", "accessToken", "db_password", "MYSQL_PWD"]:
            with self.subTest(name=name):
                self.assertTrue(guard.settings_findings(json.dumps({"env": {name: FAKE}}).encode()))
                self.assertFalse(
                    guard.settings_findings(json.dumps({"env": {name: "$VARIABLE"}}).encode())
                )

    def test_numeric_password(self) -> None:
        """Verify numeric password."""
        self.assertTrue(guard.settings_findings(b'{"env":{"PASSWORD":123456}}'))

    def test_nonsecret_settings(self) -> None:
        """Verify nonsecret settings."""
        document = {
            "env": {
                "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
                "DISABLE_TELEMETRY": "1",
                "API_KEY_FILE": "fixtures/key",
                "TOKEN_COUNT": "2048",
            },
            "permissions": {"allow": ["Bash(npm run test:*)", "Read(~/.aws/**)"]},
            "hooks": {"PreToolUse": [{"command": "$HOME/.claude/hooks/check.sh"}]},
        }
        self.assertFalse(guard.settings_findings(json.dumps(document).encode()))

    def test_known_formats_and_private_keys(self) -> None:
        """Verify known formats and private keys."""
        examples = [
            "AK" + "IA" + "A" * 16,
            "gh" + "p_" + "a" * 36,
            "github_" + "pat_" + "a" * 50,
            "sk-" + "ant-" + "a" * 40,
            "npm" + "_" + "a" * 36,
            "-----BEGIN " + "RSA PRIVATE KEY-----",
        ]
        for value in examples:
            with self.subTest(value=value):
                self.assertTrue(guard.settings_findings(json.dumps({"unrelated": value}).encode()))

    def test_invalid_documents_fail_closed(self) -> None:
        """Verify invalid documents fail closed."""
        for content in [
            b"{",
            b"[]",
            b"null",
            b"\xff",
            b'{"x":1,"x":2}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
        ]:
            with self.subTest(content=content):
                self.assertTrue(guard.settings_findings(content))

    def test_oversized_document_fails_closed(self) -> None:
        """Verify oversized document fails closed."""
        self.assertTrue(guard.settings_findings(b" " * (guard.MAX_SETTINGS_BYTES + 1)))

    def test_json_escaped_credentials(self) -> None:
        """Verify json escaped credentials."""
        content = json.dumps({"env": {"API_KEY": FAKE}}).replace("API_KEY", "\\u0041PI_KEY")
        self.assertTrue(guard.settings_findings(content.encode()))

    def test_target_paths(self) -> None:
        """Verify target paths."""
        for prefix in ["", "nested/", "two/levels/"]:
            self.assertEqual(guard.target_kind(prefix + ".claude/settings.local.json"), "local")
            self.assertEqual(guard.target_kind(prefix + ".claude/settings.json"), "shared")
        self.assertEqual(guard.target_kind("settings.json"), "shared")
        self.assertIsNone(guard.target_kind(".vscode/settings.json"))
        self.assertIsNone(guard.target_kind(".claude/skills/example.md"))


class GitIntegrationTests(unittest.TestCase):
    """Verify real index/history behavior without network or user configuration."""

    def setUp(self) -> None:
        """Create an isolated repository and deterministic local identity."""
        self.temp = tempfile.TemporaryDirectory(prefix="claude-settings-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
        self.git("init", "-q")
        self.write("README.md", "Synthetic guard test repository.\n")
        self.git("add", "README.md")
        self.base = self.commit()

    def git(self, *args: str) -> str:
        """Run a local fixture Git command without hooks or signing."""
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", *args],
            cwd=self.root,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def write(self, path: str, content: str) -> None:
        """Write a fixture within the temporary repository."""
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self) -> str:
        """Create a fixture commit and return its full SHA."""
        self.git("commit", "-qm", "Synthetic fixture")
        return self.git("rev-parse", "HEAD")

    def run_guard(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the actual CLI and assert that no synthetic secret is printed."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotIn(FAKE, result.stdout + result.stderr)
        return result

    def test_clean_index(self) -> None:
        """Verify clean index."""
        self.assertEqual(self.run_guard().returncode, 0)

    def test_subdirectory_invocation_scans_whole_index(self) -> None:
        """Verify subdirectory invocation scans whole index."""
        self.write(".claude/settings.local.json", "{}")
        self.git("add", ".claude/settings.local.json")
        nested = self.root / "nested"
        nested.mkdir()
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=nested,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)

    def test_untracked_local_settings_are_not_read(self) -> None:
        """Verify untracked local settings are not read."""
        self.write(".claude/settings.local.json", json.dumps({"env": {"TOKEN": FAKE}}))
        self.assertEqual(self.run_guard().returncode, 0)

    def test_tracked_nested_local_settings_fail(self) -> None:
        """Verify tracked nested local settings fail."""
        self.write("nested/.claude/settings.local.json", "{}")
        self.git("add", "nested/.claude/settings.local.json")
        self.assertEqual(self.run_guard("--staged").returncode, 1)

    def test_partially_staged_shared_secret_is_detected(self) -> None:
        """Verify partially staged shared secret is detected."""
        path = ".claude/settings.json"
        self.write(path, json.dumps({"env": {"API_KEY": FAKE}}))
        self.git("add", path)
        self.write(path, "{}")
        self.assertEqual(self.run_guard().returncode, 1)

    def test_root_template_is_scanned(self) -> None:
        """Verify root template is scanned."""
        self.write("settings.json", json.dumps({"env": {"API_KEY": FAKE}}))
        self.git("add", "settings.json")
        self.assertEqual(self.run_guard().returncode, 1)

    def test_symlink_settings_fail_without_following_target(self) -> None:
        """Verify symlink settings fail without following target."""
        path = self.root / ".claude/settings.json"
        path.parent.mkdir()
        path.symlink_to("../../outside.json")
        self.git("add", ".claude/settings.json")
        self.assertEqual(self.run_guard().returncode, 1)

    def test_add_then_delete_local_file_still_fails_history(self) -> None:
        """Verify add then delete local file still fails history."""
        path = "nested/.claude/settings.local.json"
        self.write(path, "{}")
        self.git("add", path)
        self.commit()
        self.git("rm", path)
        head = self.commit()
        self.assertEqual(self.run_guard("--head", head, "--base", self.base).returncode, 1)

    def test_add_then_remove_secret_still_fails_history(self) -> None:
        """Verify add then remove secret still fails history."""
        path = ".claude/settings.json"
        self.write(path, json.dumps({"env": {"API_KEY": FAKE}}))
        self.git("add", path)
        self.commit()
        self.write(path, "{}")
        self.git("add", path)
        head = self.commit()
        self.assertEqual(self.run_guard("--head", head, "--base", self.base).returncode, 1)

    def test_new_branch_and_missing_base_scan_full_history(self) -> None:
        """Verify new branch and missing base scan full history."""
        self.write(".claude/settings.local.json", "{}")
        self.git("add", ".claude/settings.local.json")
        self.commit()
        self.git("rm", ".claude/settings.local.json")
        head = self.commit()
        for base in ["", "0" * 40, "f" * 40]:
            with self.subTest(base=base):
                self.assertEqual(self.run_guard("--head", head, "--base", base).returncode, 1)

    def test_clean_history(self) -> None:
        """Verify clean history."""
        self.assertEqual(self.run_guard("--head", self.base).returncode, 0)

    def test_invalid_head_fails_closed(self) -> None:
        """Verify invalid head fails closed."""
        self.assertEqual(self.run_guard("--head", "--help").returncode, 2)
        self.assertEqual(self.run_guard("--head", "not-a-sha").returncode, 2)

    def test_shallow_history_fails_closed(self) -> None:
        """Verify shallow history fails closed."""
        (self.root / ".git/shallow").write_text(self.base + "\n", encoding="ascii")
        self.assertEqual(self.run_guard("--head", self.base).returncode, 2)


if __name__ == "__main__":
    unittest.main()
