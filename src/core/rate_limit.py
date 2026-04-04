import logging
from datetime import datetime, timezone

from src.config import RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_MINUTE
from src.db.connection import DB_BACKEND, get_connection, return_pg_connection

logger = logging.getLogger("rate_limit")


class RateLimitExceeded(Exception):
    pass


def check_rate_limit(user_id: int):
    """
    Controlla i limiti di rate_limit (minuto e ora) per l'utente.
    Usa INSERT ... ON CONFLICT DO UPDATE per garantire l'atomicità ed evitare race conditions.
    """
    if not RATE_LIMIT_PER_HOUR and not RATE_LIMIT_PER_MINUTE:
        return

    now = datetime.now(timezone.utc)
    # Troncatura timestamp: "YYYY-MM-DDTHH:MM" per minuto, "YYYY-MM-DDTHH:00" per ora
    minute_window = now.strftime("%Y-%m-%dT%H:%M:00Z")
    hour_window = now.strftime("%Y-%m-%dT%H:00:00Z")

    conn = get_connection()
    try:
        # Inline cleanup: purge expired windows (> 2 hours old) at zero extra cost
        if DB_BACKEND == "postgres":
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM tg_rate_limits WHERE window_start::timestamp < (NOW() - INTERVAL '2 hours')"
                )
        else:
            conn.execute(
                "DELETE FROM tg_rate_limits WHERE window_start < datetime('now', '-2 hours')"
            )

        if DB_BACKEND == "postgres":
            with conn.cursor() as cur:
                # Controlla limite orario
                if RATE_LIMIT_PER_HOUR > 0:
                    cur.execute(
                        """
                        INSERT INTO tg_rate_limits (user_id, window_start, hit_count)
                        VALUES (%s, %s, 1)
                        ON CONFLICT (user_id, window_start)
                        DO UPDATE SET hit_count = tg_rate_limits.hit_count + 1
                        RETURNING hit_count
                        """,
                        (user_id, hour_window),
                    )
                    row = cur.fetchone()
                    hour_hits = row.get("hit_count") if isinstance(row, dict) else (row[0] if row else 0)
                    if hour_hits > RATE_LIMIT_PER_HOUR:
                        raise RateLimitExceeded(
                            f"Rate limit orario superato ({RATE_LIMIT_PER_HOUR})"
                        )

                # Controlla limite al minuto
                if RATE_LIMIT_PER_MINUTE > 0:
                    cur.execute(
                        """
                        INSERT INTO tg_rate_limits (user_id, window_start, hit_count)
                        VALUES (%s, %s, 1)
                        ON CONFLICT (user_id, window_start)
                        DO UPDATE SET hit_count = tg_rate_limits.hit_count + 1
                        RETURNING hit_count
                        """,
                        (user_id, minute_window),
                    )
                    row = cur.fetchone()
                    minute_hits = row.get("hit_count") if isinstance(row, dict) else (row[0] if row else 0)
                    if minute_hits > RATE_LIMIT_PER_MINUTE:
                        raise RateLimitExceeded(
                            f"Rate limit al minuto superato ({RATE_LIMIT_PER_MINUTE})"
                        )
            conn.commit()

        else:
            # Backend SQLite
            if RATE_LIMIT_PER_HOUR > 0:
                res = conn.execute(
                    """
                    INSERT INTO tg_rate_limits (user_id, window_start, hit_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT (user_id, window_start)
                    DO UPDATE SET hit_count = tg_rate_limits.hit_count + 1
                    RETURNING hit_count
                    """,
                    (user_id, hour_window),
                ).fetchone()
                hour_hits = res["hit_count"] if res else 1
                if hour_hits > RATE_LIMIT_PER_HOUR:
                    raise RateLimitExceeded(
                        f"Rate limit orario superato ({RATE_LIMIT_PER_HOUR})"
                    )

            if RATE_LIMIT_PER_MINUTE > 0:
                res = conn.execute(
                    """
                    INSERT INTO tg_rate_limits (user_id, window_start, hit_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT (user_id, window_start)
                    DO UPDATE SET hit_count = tg_rate_limits.hit_count + 1
                    RETURNING hit_count
                    """,
                    (user_id, minute_window),
                ).fetchone()
                minute_hits = res["hit_count"] if res else 1
                if minute_hits > RATE_LIMIT_PER_MINUTE:
                    raise RateLimitExceeded(
                        f"Rate limit al minuto superato ({RATE_LIMIT_PER_MINUTE})"
                    )
            conn.commit()

    finally:
        if DB_BACKEND == "postgres":
            return_pg_connection(conn)
