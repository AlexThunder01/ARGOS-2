import os

os.environ["DB_BACKEND"] = "sqlite"

import pytest

from src.core.rate_limit import RateLimitExceeded, check_rate_limit


def test_rate_limit_exceeded(patch_db, monkeypatch):
    # Setup test limit
    import src.core.rate_limit as rl

    monkeypatch.setattr(rl, "RATE_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(rl, "RATE_LIMIT_PER_HOUR", 2)

    conn = patch_db
    conn.execute("DELETE FROM tg_rate_limits")
    conn.commit()

    user_id = 999

    # Primi 2 accessi devono passare
    check_rate_limit(user_id)
    check_rate_limit(user_id)

    # Il 3o deve fallire
    with pytest.raises(RateLimitExceeded) as exc:
        check_rate_limit(user_id)
    assert "Rate limit" in str(exc.value)


def test_rate_limit_disabled(patch_db, monkeypatch):
    import src.core.rate_limit as rl

    monkeypatch.setattr(rl, "RATE_LIMIT_PER_MINUTE", 0)
    monkeypatch.setattr(rl, "RATE_LIMIT_PER_HOUR", 0)

    conn = patch_db
    conn.execute("DELETE FROM tg_rate_limits")
    conn.commit()

    user_id = 888
    # 10 accessi consecutivi con limit=0
    for _ in range(10):
        check_rate_limit(user_id)


def test_different_users_independent_limits(patch_db, monkeypatch):
    """Different user_ids should have independent rate limit counters."""
    import src.core.rate_limit as rl

    monkeypatch.setattr(rl, "RATE_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(rl, "RATE_LIMIT_PER_HOUR", 100)

    conn = patch_db
    conn.execute("DELETE FROM tg_rate_limits")
    conn.commit()

    user_a, user_b = 1001, 1002

    # user_a consumes 2 slots
    check_rate_limit(user_a)
    check_rate_limit(user_a)

    # user_b should still be able to use their own slots
    check_rate_limit(user_b)  # Should not raise
    check_rate_limit(user_b)  # Should not raise

    # user_a's 3rd call should fail
    with pytest.raises(RateLimitExceeded):
        check_rate_limit(user_a)


def test_rate_limit_error_message_contains_detail(patch_db, monkeypatch):
    """The RateLimitExceeded error message should contain 'Rate limit'."""
    import src.core.rate_limit as rl

    monkeypatch.setattr(rl, "RATE_LIMIT_PER_MINUTE", 1)
    monkeypatch.setattr(rl, "RATE_LIMIT_PER_HOUR", 1)

    conn = patch_db
    conn.execute("DELETE FROM tg_rate_limits")
    conn.commit()

    check_rate_limit(777)

    with pytest.raises(RateLimitExceeded) as exc:
        check_rate_limit(777)
    msg = str(exc.value)
    assert "Rate limit" in msg or "superato" in msg


def test_only_minute_limit_without_hour(patch_db, monkeypatch):
    """When RATE_LIMIT_PER_HOUR=0, only minute limit should be enforced."""
    import src.core.rate_limit as rl

    monkeypatch.setattr(rl, "RATE_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(rl, "RATE_LIMIT_PER_HOUR", 0)

    conn = patch_db
    conn.execute("DELETE FROM tg_rate_limits")
    conn.commit()

    user_id = 555
    check_rate_limit(user_id)
    check_rate_limit(user_id)

    with pytest.raises(RateLimitExceeded):
        check_rate_limit(user_id)


def test_only_hour_limit_without_minute(patch_db, monkeypatch):
    """When RATE_LIMIT_PER_MINUTE=0, only hour limit should be enforced."""
    import src.core.rate_limit as rl

    monkeypatch.setattr(rl, "RATE_LIMIT_PER_MINUTE", 0)
    monkeypatch.setattr(rl, "RATE_LIMIT_PER_HOUR", 3)

    conn = patch_db
    conn.execute("DELETE FROM tg_rate_limits")
    conn.commit()

    user_id = 666
    check_rate_limit(user_id)
    check_rate_limit(user_id)
    check_rate_limit(user_id)

    with pytest.raises(RateLimitExceeded):
        check_rate_limit(user_id)
