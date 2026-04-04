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
