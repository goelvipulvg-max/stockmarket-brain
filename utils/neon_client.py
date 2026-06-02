import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv(override=True)

NEON_CONNECT_TIMEOUT = 10
NEON_MAX_ATTEMPTS = 3
NEON_BACKOFF = [2, 4]


def get_neon_connection():
    conn_string = os.getenv("NEON_CONNECTION_STRING", "").strip()
    if not conn_string:
        raise ValueError("NEON_CONNECTION_STRING missing from env")
    last = None
    for attempt in range(1, NEON_MAX_ATTEMPTS + 1):
        try:
            conn = psycopg2.connect(conn_string, connect_timeout=NEON_CONNECT_TIMEOUT)
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as e:
            last = e
            msg = str(e).lower()
            if any(k in msg for k in ["authentication", "password", "does not exist", "role"]):
                raise  # config/auth error -> no retry
            if attempt < NEON_MAX_ATTEMPTS:
                wait = NEON_BACKOFF[attempt - 1]
                print(
                    f"[neon_client] connect attempt {attempt}/{NEON_MAX_ATTEMPTS} failed: "
                    f"{str(e).splitlines()[0]}; retry in {wait}s"
                )
                time.sleep(wait)
    raise last


def execute(sql: str) -> None:
    conn = get_neon_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
    finally:
        conn.close()


def query(sql: str) -> list[dict]:
    conn = get_neon_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


if __name__ == "__main__":
    print("Pinging Neon...")
    rows = query("SELECT 1 AS ping")
    print(f"Ping OK: {rows}")
