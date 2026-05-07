import requests


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
) -> None:
    if not bot_token or not chat_id:
        print("  Telegram config missing -- skipping")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        timeout=10,
    )
    if not r.ok:
        print(f"  Telegram error: {r.status_code} -- {r.text[:100]}")


if __name__ == "__main__":
    print("Import OK")
