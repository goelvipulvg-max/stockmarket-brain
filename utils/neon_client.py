import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv(override=True)


def get_neon_connection():
    conn_string = os.getenv("NEON_CONNECTION_STRING", "").strip()
    if not conn_string:
        raise ValueError("NEON_CONNECTION_STRING missing from env")
    conn = psycopg2.connect(conn_string)
    conn.autocommit = True
    return conn


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
