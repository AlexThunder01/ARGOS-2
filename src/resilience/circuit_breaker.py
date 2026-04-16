"""
Circuit Breaker Pattern for Resilience

Implements the circuit breaker state machine (closed → open → half-open) to prevent
cascading failures when external APIs (LLM, embeddings) experience prolonged outages.

State machine:
- CLOSED: Normal operation. Calls pass through; failures are counted.
- OPEN: Circuit opened after failure_threshold is reached. Calls rejected immediately.
- HALF-OPEN: Testing recovery. After timeout_seconds, allow one test call.
  - Success: Transition to CLOSED, reset failure_count.
  - Failure: Transition back to OPEN, restart timeout.
"""

import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("argos")


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open and calls are rejected."""

    pass


class CircuitBreaker:
    """State machine for circuit breaker pattern.

    Tracks failures in a time window and transitions between states.
    Prevents infinite retry loops by failing fast when service is down.
    """

    def __init__(self, failure_threshold: int = 5, timeout_seconds: int = 60):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit (default 5)
            timeout_seconds: Seconds to wait before entering half-open state (default 60)
        """
        self.state: str = "closed"
        self.failure_count: int = 0
        self.failure_threshold: int = failure_threshold
        self.timeout_seconds: int = timeout_seconds
        self.last_failure_time: Optional[float] = None
        self.half_open_time: Optional[float] = None

    def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute function with circuit breaker protection.

        Args:
            fn: Callable to execute
            *args: Positional arguments to pass to fn
            **kwargs: Keyword arguments to pass to fn

        Returns:
            Result from fn

        Raises:
            CircuitBreakerOpen: If circuit is open and timeout hasn't expired
            Exception: Any exception raised by fn (unless circuit is open)
        """
        # Check if failure window has expired
        self._is_failure_window_expired()

        if self.state == "open":
            # Check if timeout has expired (recovery window)
            if self.half_open_time is None:
                self.half_open_time = time.time()

            elapsed = time.time() - self.half_open_time
            if elapsed > self.timeout_seconds:
                # Timeout expired: transition to half-open for test call
                old_state = self.state
                self.state = "half-open"
                logger.warning(
                    f"[CircuitBreaker] State transition: {old_state} → {self.state}"
                )
            else:
                # Still in cooldown: reject call
                raise CircuitBreakerOpen(
                    f"Circuit breaker is open (cooldown: {self.timeout_seconds - elapsed:.1f}s remaining)"
                )

        # Execute the call
        try:
            result = fn(*args, **kwargs)

            # Success: if in half-open, transition to closed
            if self.state == "half-open":
                old_state = self.state
                self.state = "closed"
                self.failure_count = 0
                self.last_failure_time = None
                self.half_open_time = None
                logger.info(
                    f"[CircuitBreaker] State transition: {old_state} → {self.state}"
                )

            return result

        except Exception:
            # Failure: increment counter and check threshold
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                old_state = self.state
                self.state = "open"
                self.half_open_time = time.time()
                logger.error(
                    f"[CircuitBreaker] Circuit open after {self.failure_count} failures"
                )
                logger.warning(
                    f"[CircuitBreaker] State transition: {old_state} → {self.state}"
                )

            # Re-raise the exception to caller
            raise

    def _is_failure_window_expired(self) -> None:
        """Check if failure window has expired and reset count if so.

        If more than timeout_seconds have passed since last failure,
        reset failure_count to allow fresh start.
        """
        if self.last_failure_time is None:
            return

        elapsed = time.time() - self.last_failure_time
        if elapsed > self.timeout_seconds:
            self.failure_count = 0
            self.last_failure_time = None

    async def async_call(self, fn, *args, **kwargs):
        """Execute an async coroutine function with circuit breaker protection.

        Same semantics as call(), but awaits fn(*args, **kwargs).
        """
        import asyncio

        self._is_failure_window_expired()

        if self.state == "open":
            if self.half_open_time is None:
                self.half_open_time = time.time()
            elapsed = time.time() - self.half_open_time
            if elapsed > self.timeout_seconds:
                old_state = self.state
                self.state = "half-open"
                logger.warning(
                    f"[CircuitBreaker] State transition: {old_state} → {self.state}"
                )
            else:
                raise CircuitBreakerOpen(
                    f"Circuit breaker is open (cooldown: {self.timeout_seconds - elapsed:.1f}s remaining)"
                )

        try:
            result = await fn(*args, **kwargs)

            if self.state == "half-open":
                old_state = self.state
                self.state = "closed"
                self.failure_count = 0
                self.last_failure_time = None
                self.half_open_time = None
                logger.info(
                    f"[CircuitBreaker] State transition: {old_state} → {self.state}"
                )

            return result

        except Exception:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                old_state = self.state
                self.state = "open"
                self.half_open_time = time.time()
                logger.error(
                    f"[CircuitBreaker] Circuit open after {self.failure_count} failures"
                )
                logger.warning(
                    f"[CircuitBreaker] State transition: {old_state} → {self.state}"
                )

            raise

    def reset(self) -> None:
        """Manually reset circuit breaker to closed state.

        Used for testing or explicit recovery.
        """
        old_state = self.state
        self.state = "closed"
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_time = None
        if old_state != "closed":
            logger.info(
                f"[CircuitBreaker] State transition: {old_state} → {self.state}"
            )
