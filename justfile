set shell := ["bash", "-euo", "pipefail", "-c"]

# Override with `HA_HOST=user@host HA_CONFIG=/config just deploy`.
ha_host := env_var_or_default("HA_HOST", "root@homeassistant")
ha_config := env_var_or_default("HA_CONFIG", "/config")

default:
    @just --list

# Full local dev environment: both test groups, dev tooling, and the
# fixture-redaction pre-commit hook (a bare `uv sync` only gets the test group).
setup:
    uv sync --group dev --group test-ha
    uv run --group dev pre-commit install

# Fast suite: no Home Assistant import.
test:
    uv run pytest tests/unit -p no:homeassistant -q

# The Home Assistant suite. Never add -n auto or -p no:logging (breaks caplog).
test-ha:
    uv run --group test-ha pytest tests/ha -q

test-all: test test-ha

# Pyright, as CI runs it: the paths and rules are [tool.pyright] in
# pyproject.toml. Pass paths to check others, e.g. `just typecheck tests/ha`
# (tests/ is not gated yet).
typecheck *paths:
    uv run --group dev --group test-ha pyright {{ paths }}

# Ruff, as CI runs it.
lint:
    uv run --group dev ruff check .

# Apply ruff's fixes.
fmt:
    uv run --group dev ruff check --fix .

# The coverage floors, exactly as CI computes them.
coverage:
    uv run coverage run -m pytest tests/unit -p no:homeassistant -q
    uv run --group test-ha coverage run -m pytest tests/ha -q
    uv run coverage combine
    uv run coverage json
    uv run python scripts/coverage_floors.py

# The fixture redaction guard.
fixtures-check:
    uv run python scripts/check_fixtures.py tests/fixtures/*.json

# Everything CI checks, run locally.
ci: lint typecheck test-all coverage fixtures-check

# Remove caches and coverage output.
clean:
    find . -type d -name __pycache__ -not -path './.venv/*' -not -path './.worktrees/*' -exec rm -rf {} +
    rm -rf .pytest_cache .hypothesis
    rm -f .coverage .coverage.* coverage.json

# Rsync the integration, including its Lovelace cards, to a running Home
# Assistant instance for manual testing.
deploy:
    # --delete is safe here: the target directory belongs entirely to this integration.
    rsync -rv --delete \
        --exclude '__pycache__' --exclude '*.pyc' \
        custom_components/nina_astrophotography/ \
        {{ ha_host }}:{{ ha_config }}/custom_components/nina_astrophotography/
    @echo "Deployed. Restart Home Assistant (or reload the integration) to pick it up."

# Sync the automation blueprints.
deploy-blueprints:
    # HA filed these under the importing GitHub user's folder, not the repo name.
    rsync -v blueprints/automation/nina_astrophotography/*.yaml \
        {{ ha_host }}:{{ ha_config }}/blueprints/automation/dgivens/

deploy-all: deploy deploy-blueprints
