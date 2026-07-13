import time

import requests


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
    retries: int = 1,
) -> bool:
    """Fail-open by contract: NEVER raises (callers are alert paths that must
    not break trades/batches). Returns True only on confirmed delivery.
    Transient failures (transport, 429, 5xx) get one retry; permanent HTTP
    errors (bad chat id, parse error) return False immediately."""
    if not bot_token or not chat_id:
        print("  Telegram config missing -- skipping")
        return False
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
                timeout=10,
            )
            if r.ok:
                return True
            print(f"  Telegram error: {r.status_code} -- {r.text[:100]}")
            if r.status_code != 429 and r.status_code < 500:
                return False  # permanent -- retry cannot help
        except requests.RequestException as e:
            print(f"  Telegram transport error: {type(e).__name__}: {e}")
        if attempt < retries:
            time.sleep(2)
    return False


if __name__ == "__main__":
    print("Import OK")
