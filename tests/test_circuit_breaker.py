"""
Test suite for circuit breaker state machine.

Verifies state transitions: closed → open → half-open → closed
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DB_BACKEND"] = "sqlite"

import pytest

from src.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpen


class TestCircuitBreaker:
    def test_circuit_breaker_closed_allows_calls(self):
        """Closed circuit passes calls through normally."""
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)
        assert cb.state == "closed"

        result = cb.call(lambda: "success")
        assert result == "success"
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_circuit_breaker_opens_after_threshold(self):
        """Circuit opens after failure_threshold failures."""
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        def failing():
            raise ValueError("api error")

        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(failing)

        assert cb.state == "open"

        # Next call must be rejected immediately (not execute failing fn)
        calls = []

        def should_not_run():
            calls.append(1)
            return "ran"

        with pytest.raises(CircuitBreakerOpen):
            cb.call(should_not_run)

        assert calls == [], "Function must not be executed when circuit is open"

    def test_circuit_breaker_half_open_after_cooldown(self):
        """Circuit transitions to half-open after timeout expires."""
        cb = CircuitBreaker(failure_threshold=1, timeout_seconds=1)

        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))

        assert cb.state == "open"

        time.sleep(1.1)

        # Next call should be attempted (half-open test call)
        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == "closed"

    def test_circuit_breaker_reset(self):
        """Manual reset returns circuit to closed state."""
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60)

        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("err")))

        assert cb.state == "open"

        cb.reset()
        assert cb.state == "closed"
        assert cb.failure_count == 0
        assert cb.last_failure_time is None
        assert cb.half_open_time is None

    def test_circuit_breaker_half_open_success_closes_circuit(self):
        """Successful call in half-open state closes the circuit."""
        cb = CircuitBreaker(failure_threshold=1, timeout_seconds=1)

        with pytest.raises(IOError):
            cb.call(lambda: (_ for _ in ()).throw(OSError("down")))

        assert cb.state == "open"
        time.sleep(1.1)

        cb.call(lambda: "ok")
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_circuit_breaker_half_open_failure_reopens_circuit(self):
        """Failing call in half-open state reopens the circuit."""
        cb = CircuitBreaker(failure_threshold=1, timeout_seconds=1)

        with pytest.raises(ConnectionError):
            cb.call(lambda: (_ for _ in ()).throw(ConnectionError("down")))

        assert cb.state == "open"
        time.sleep(1.1)

        # Test call in half-open fails → back to open
        with pytest.raises(ConnectionError):
            cb.call(lambda: (_ for _ in ()).throw(ConnectionError("still down")))

        assert cb.state == "open"

    def test_circuit_breaker_failure_window_expires(self):
        """After timeout, failure count resets and circuit stays closed."""
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=1)

        # One failure — not enough to open
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("transient")))

        assert cb.failure_count == 1
        assert cb.state == "closed"

        time.sleep(1.1)

        # Window expired — success should reset counter fully
        cb.call(lambda: "ok")
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_circuit_breaker_threshold_configurable(self):
        """Threshold and timeout are respected from constructor args."""
        cb = CircuitBreaker(failure_threshold=5, timeout_seconds=120)
        assert cb.failure_threshold == 5
        assert cb.timeout_seconds == 120

        # 4 failures should NOT open
        for _ in range(4):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("err")))

        assert cb.state == "closed"
        assert cb.failure_count == 4

        # 5th failure opens
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("err")))

        assert cb.state == "open"
