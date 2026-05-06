import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv(override=True)


def get_conn():
    conn = psycopg2.connect(
        host=os.getenv("QUESTDB_HOST", "localhost"),
        port=int(os.getenv("QUESTDB_PORT", "8812")),
        user=os.getenv("QUESTDB_USER", "admin"),
        password=os.getenv("QUESTDB_PASSWORD", "quest"),
        dbname=os.getenv("QUESTDB_DB", "qdb"),
    )
    conn.autocommit = True
    return conn


def execute(sql: str) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
    finally:
        conn.close()


def query(sql: str) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def executemany(sql: str, rows: list) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    finally:
        conn.close()


if __name__ == "__main__":
    print("Pinging QuestDB...")
    ping = query("SELECT 1")
    print(f"Ping OK: {ping}")
    version = query("SELECT build()")
    print(f"Version: {version[0] if version else 'unknown'}")
