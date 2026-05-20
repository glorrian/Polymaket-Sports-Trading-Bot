"""Tests for ApiKeyPool round-robin rotation and usage tracking."""
import os
import threading
import pytest
from poly_sports.utils.api_key_pool import ApiKeyPool


class TestApiKeyPoolInit:
    def test_from_comma_separated_list(self):
        pool = ApiKeyPool(["key_a", "key_b", "key_c"])
        assert pool.keys == ["key_a", "key_b", "key_c"]

    def test_strips_whitespace(self):
        pool = ApiKeyPool(["  key_a  ", " key_b "])
        assert pool.keys == ["key_a", "key_b"]

    def test_ignores_empty_entries(self):
        pool = ApiKeyPool(["key_a", "", "  ", "key_b"])
        assert pool.keys == ["key_a", "key_b"]

    def test_empty_pool_raises(self):
        pool = ApiKeyPool([])
        with pytest.raises(ValueError, match="No Odds API keys"):
            pool.next_key()

    def test_single_key(self):
        pool = ApiKeyPool(["only_key"])
        assert pool.next_key() == "only_key"


class TestApiKeyPoolRotation:
    def test_round_robin(self):
        pool = ApiKeyPool(["a", "b", "c"])
        assert pool.next_key() == "a"
        assert pool.next_key() == "b"
        assert pool.next_key() == "c"
        assert pool.next_key() == "a"

    def test_wraps_correctly(self):
        pool = ApiKeyPool(["x", "y"])
        keys = [pool.next_key() for _ in range(6)]
        assert keys == ["x", "y", "x", "y", "x", "y"]


class TestApiKeyPoolUsage:
    def test_usage_tracking(self):
        pool = ApiKeyPool(["a", "b"])
        pool.next_key()
        pool.next_key()
        pool.next_key()
        assert pool.usage_summary() == {"a": 2, "b": 1}

    def test_total_requests(self):
        pool = ApiKeyPool(["k1", "k2"])
        for _ in range(5):
            pool.next_key()
        assert pool.total_requests() == 5

    def test_usage_starts_at_zero(self):
        pool = ApiKeyPool(["a", "b"])
        assert pool.total_requests() == 0
        assert pool.usage_summary() == {"a": 0, "b": 0}


class TestApiKeyPoolShared:
    def test_shared_singleton(self):
        ApiKeyPool.reset()
        os.environ["ODDS_API_KEYS"] = "sk1,sk2"
        try:
            pool1 = ApiKeyPool.shared()
            pool2 = ApiKeyPool.shared()
            assert pool1 is pool2
            assert pool1.keys == ["sk1", "sk2"]
        finally:
            ApiKeyPool.reset()
            os.environ.pop("ODDS_API_KEYS", None)

    def test_fallback_to_single_key(self):
        ApiKeyPool.reset()
        old = os.environ.pop("ODDS_API_KEYS", None)
        os.environ["ODDS_API_KEY"] = "single"
        try:
            pool = ApiKeyPool.shared()
            assert pool.keys == ["single"]
        finally:
            ApiKeyPool.reset()
            os.environ.pop("ODDS_API_KEY", None)
            if old:
                os.environ["ODDS_API_KEYS"] = old

    def test_reset_creates_new_instance(self):
        ApiKeyPool.reset()
        pool_a = ApiKeyPool(["x"])
        ApiKeyPool._instance = pool_a
        assert ApiKeyPool.shared() is pool_a
        ApiKeyPool.reset()
        assert ApiKeyPool._instance is None


class TestApiKeyPoolThreadSafety:
    def test_concurrent_access(self):
        pool = ApiKeyPool(["a", "b", "c"])
        results = []
        errors = []

        def worker():
            try:
                for _ in range(100):
                    results.append(pool.next_key())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 500
        assert pool.total_requests() == 500
