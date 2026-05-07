import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv(override=True)


def get_client() -> Client:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url:
        raise ValueError("SUPABASE_URL missing from env")
    if not key:
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY missing from env")
    return create_client(url, key)


if __name__ == "__main__":
    c = get_client()
    print(f"Supabase client OK: {type(c).__name__}")
