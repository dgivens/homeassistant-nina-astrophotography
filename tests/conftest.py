"""Root conftest.

Deliberately empty of fixtures. The two suites are independent: tests/unit runs
without Home Assistant, tests/ha runs under pytest-homeassistant-custom-component.
Shared *data* helpers live in tests/helpers.py, which imports neither.
"""
