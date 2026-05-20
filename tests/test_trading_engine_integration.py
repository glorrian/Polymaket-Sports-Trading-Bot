"""Integration smoke test for one paper trading cycle.

NOTE: This test is skipped because AutoTraderEngine.run_cycle() is now async.
Use tests/trading/test_engine_db_integration.py for async integration testing.
"""

import pytest

pytest.skip("run_cycle is now async — use tests/trading/test_engine_db_integration.py", allow_module_level=True)
