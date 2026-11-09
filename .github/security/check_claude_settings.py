# Copyright 2026 Andrew Mills
# Standalone CLI, deliberately not an import package; redacted diagnostics use print.
# Git argv and fixture Python paths are explicit; shell execution is never used.
# ruff: noqa: S603, S607, T201
"""Reject committed local Claude settings and likely credentials in shared settings.

Default/--staged reads the Git index, including partially staged files. CI uses
--head SHA --base SHA to inspect the target tree and both sides of changed blobs.
A new branch or unavailable base is scanned through its full reachable history.
This focused, offline heuristic is not a replacement for a general secret scanner.
Diagnostics never include settings values. No commands found in settings run.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

MAX_SETTINGS_BYTES = 2 * 1024 * 1024
SHA = re.compile(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?\Z")
REFERENCE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})\Z")
SECRET_NAME = re.compile(
    r"(?:password|passwd|passphrase|token|secret|credential|api[_.-]?key|"
    r"private[_.-]?key|access[_.-]?key|database[_.-]?url|db[_.-]?url|(?:^|_)pwd)"
    r"(?:$|[_.-])",
    re.IGNORECASE,
)
NONSECRET_SUFFIX = re.compile(
    r"(?:[_.-](?:file|path|count|length|ttl|enabled|disabled))$", re.IGNORECASE
)
VALUE = r"""((?:"[^"\n]*"|'[^'\n]*'|[^\s;'\"])+)"""
ASSIGNMENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*" + VALUE)
VALUE_PATTERNS = (
    (
        "credential-bearing URL",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:([^@\s]+)@", re.IGNORECASE),
    ),
    ("authorization header", re.compile(r"\b(?:Bearer|Basic)\s+" + VALUE, re.IGNORECASE)),
    (
        "authorization header",
        re.compile(r"\bauthorization\s*:\s*(?:(?:bearer|basic|token)\s+)?" + VALUE, re.IGNORECASE),
    ),
    (
        "API-key header",
        re.compile(r"\b(?:x-api-key|api-key|apikey|x-auth-token)\s*:\s*" + VALUE, re.IGNORECASE),
    ),
    (
        "credential argument",
        re.compile(
            r"--(?:password|passwd|token|api-key|secret|client-secret)(?:=|\s+)" + VALUE,
            re.IGNORECASE,
        ),
    ),
    ("sshpass password", re.compile(r"\bsshpass\s+-p\s*" + VALUE)),
    (
        "database password argument",
        re.compile(r"\b(?:mysql|mariadb)\b[^\n;|]*?\s-p([^\s;]+)", re.IGNORECASE),
    ),
    (
        "HTTP basic-auth argument",
        re.compile(r"(?:\s-u\s*|--user(?:=|\s+))[^\s:]+:([^\s]+)"),
    ),
)
KEY_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-(?:ant-[A-Za-z0-9_-]{20,}|[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
)


class GuardError(Exception):
    """Represent an operational failure that must not pass the guard."""


def git(*args: str) -> bytes:
    """Read Git output without exposing stderr or running shell text."""
    try:
        return subprocess.run(["git", *args], check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise GuardError(
            "Git read failed; run from a repository with the requested objects."
        ) from error


def target_kind(path: str) -> str | None:
    """Classify root/nested local settings and shared settings templates."""
    parts = path.split("/")
    if len(parts) >= 2 and parts[-2:] == [".claude", "settings.local.json"]:
        return "local"
    if path == "settings.json" or parts[-2:] == [".claude", "settings.json"]:
        return "shared"
    return None


def is_reference(value: str) -> bool:
    """Accept only empty values, explicit redaction markers or simple variables."""
    value = value.strip().rstrip(")").strip("\"'")
    return value in {"", "REDACTED", "<redacted>"} or REFERENCE.fullmatch(value) is not None


def string_findings(value: str) -> set[str]:
    """Find common literal command credentials without returning their values."""
    findings = set()
    if any(pattern.search(value) for pattern in KEY_PATTERNS):
        findings.add("known credential/private-key format")
    for category, pattern in VALUE_PATTERNS:
        if any(not is_reference(match.group(1)) for match in pattern.finditer(value)):
            findings.add(category)
    for match in ASSIGNMENT.finditer(value):
        if credential_name(match.group(1)) and not is_reference(match.group(2)):
            findings.add("credential environment assignment")
    return findings


def credential_name(name: str) -> bool:
    """Distinguish credential values from paths, counts and feature switches."""
    return SECRET_NAME.search(name) is not None and NONSECRET_SUFFIX.search(name) is None


def leaves(value: object, key: str = "") -> Iterator[tuple[str, object]]:
    """Visit JSON scalar values without executing settings or following paths."""
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from leaves(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from leaves(child, key)
    else:
        yield key, value


def settings_findings(content: bytes) -> set[str]:
    """Inspect settings JSON and fail closed for invalid or oversized input."""
    if len(content) > MAX_SETTINGS_BYTES:
        return {"settings exceed the safe scan size"}
    try:
        document = json.loads(
            content.decode("utf-8"), object_pairs_hook=unique_keys, parse_constant=reject_nonfinite
        )
    except (UnicodeError, ValueError, RecursionError):
        return {"invalid UTF-8 or JSON settings"}
    if not isinstance(document, dict):
        return {"settings must be a JSON object"}
    findings: set[str] = set()
    try:
        for key, value in leaves(document):
            findings.update(scalar_findings(key, value))
    except RecursionError:
        findings.add("settings nesting exceeds the safe scan depth")
    return findings


def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys rather than hide an earlier credential value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_nonfinite(_constant: str) -> object:
    """Reject NaN/Infinity extensions that are not valid JSON settings."""
    raise ValueError("Nonfinite JSON constant")


def scalar_findings(key: str, value: object) -> set[str]:
    """Check a scalar value, including credentials assigned in env objects."""
    if value is None or isinstance(value, bool):
        return set()
    text = str(value)
    findings = string_findings(text)
    if credential_name(key) and not is_reference(text):
        findings.add("literal value under a credential key")
    return findings


def tree_entries(revision: str | None) -> set[tuple[str, str, str]]:
    """Read relevant index or committed entries as (path, mode, object ID)."""
    command = (
        ("ls-tree", "--full-tree", "-r", "-z", revision)
        if revision
        else ("ls-files", "--stage", "--full-name", "-z", "--", ":/")
    )
    entries = set()
    for record in git(*command).split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        path = raw_path.decode("utf-8", errors="surrogateescape")
        fields = metadata.decode("ascii").split()
        if target_kind(path):
            mode, oid = (fields[0], fields[2]) if revision else (fields[0], fields[1])
            if not revision and fields[2] != "0":
                mode = "unmerged"
            entries.add((path, mode, oid))
    return entries


def history_entries(revision_range: str) -> set[tuple[str, str, str]]:
    """Include old and new blobs, so add-then-delete changes remain detectable."""
    records = iter(
        git(
            "log",
            "--format=",
            "--raw",
            "-z",
            "--no-abbrev",
            "--no-renames",
            "--root",
            "-m",
            revision_range,
            "--",
        ).split(b"\0")
    )
    entries = set()
    for record in records:
        header = record.strip()
        if not header:
            continue
        if not header.startswith(b":"):
            raise GuardError("Unexpected Git history output; scan stopped.")
        path = next(records).decode("utf-8", errors="surrogateescape")
        fields = header[1:].decode("ascii").split()
        if target_kind(path):
            for mode, oid in ((fields[0], fields[2]), (fields[1], fields[3])):
                if set(oid) != {"0"}:
                    entries.add((path, mode, oid))
    return entries


def commit_exists(revision: str) -> bool:
    """Check a full commit hash, rejecting option/ref injection."""
    if not SHA.fullmatch(revision):
        return False
    try:
        git("cat-file", "-e", revision + "^{commit}")
    except GuardError:
        return False
    return True


def scan_range(head: str, base: str) -> str:
    """Validate CI input and choose complete history when no usable base exists."""
    if not commit_exists(head):
        raise GuardError("The head must name an available full commit SHA.")
    if git("rev-parse", "--is-shallow-repository").strip() != b"false":
        raise GuardError("History scanning needs a complete clone (fetch-depth: 0).")
    if base and commit_exists(base):
        return base + ".." + head
    print("No available base commit; scanning all history reachable from the head.")
    return head


def inspect_entries(entries: set[tuple[str, str, str]]) -> set[tuple[str, str]]:
    """Inspect unique blobs and return redacted path/reason diagnostics."""
    findings = set()
    cache: dict[str, set[str]] = {}
    for path, mode, oid in sorted(entries):
        if target_kind(path) == "local":
            findings.add((path, "local settings must not be tracked (including in new history)"))
            continue
        if mode not in {"100644", "100755"}:
            findings.add((path, "shared settings must be a regular, resolved file"))
            continue
        if oid not in cache:
            cache[oid] = inspect_blob(oid)
        findings.update((path, reason) for reason in cache[oid])
    return findings


def inspect_blob(oid: str) -> set[str]:
    """Bound memory before reading a settings blob."""
    if int(git("cat-file", "-s", oid)) > MAX_SETTINGS_BYTES:
        return {"settings exceed the safe scan size"}
    return settings_findings(git("cat-file", "blob", oid))


def main() -> int:
    """Run the staged or historical guard; nonzero means unsafe or incomplete."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="scan index blobs (the default)")
    mode.add_argument("--head", help="full CI head commit SHA")
    parser.add_argument("--base", default="", help="full CI base SHA; absent means full history")
    args = parser.parse_args()
    if args.base and not args.head:
        parser.error("--base requires --head")
    try:
        revision_range = scan_range(args.head, args.base) if args.head else None
        entries = tree_entries(args.head)
        if revision_range is not None:
            entries.update(history_entries(revision_range))
        findings = inspect_entries(entries)
    except (GuardError, ValueError, StopIteration) as error:
        print(f"Claude settings guard could not complete: {error}", file=sys.stderr)
        return 2
    for path, reason in sorted(findings):
        print(f"{path!r}: {reason}", file=sys.stderr)
    if findings:
        print("No settings values were printed. Rotate any exposed credentials before cleanup.")
        return 1
    print("Claude settings guard passed (focused offline checks, not a general secrets audit).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
