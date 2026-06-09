.PHONY: test verify-fixtures record-fixtures

# Default offline suite (what CI runs).
test:
	uv run pytest -m "not integration"

# Drift guard: replay the committed golden fixtures through the real client code
# and assert the recorded behavior still holds. Mirrors `verify-cassettes`.
verify-fixtures:
	uv run pytest tests/golden/test_golden_fixtures.py

# Re-capture golden fixtures from a USB-connected Flipper, then verify the
# replay still passes. Local only; commit the updated tests/golden/fixtures/.
record-fixtures:
	uv run python -m tests.golden.record
	$(MAKE) verify-fixtures
