import os, sys

print("=" * 50)
print("  StockMarket-Brain Health Check")
print("=" * 50)

results = []

# Load .env
env = {}
with open(".env") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

# --- CHECK 1: ENV VARIABLES ---
print("\n[1/5] Checking ENV variables...")
required = [
    "ANTHROPIC_API_KEY", "UPSTOX_API_KEY", "UPSTOX_API_SECRET",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_MOVERS_CHANNEL",
    "TELEGRAM_LT_CHANNEL", "TELEGRAM_SWING_CHANNEL",
    "SUPABASE_URL", "SUPABASE_ANON_KEY",
    "PINECONE_API_KEY", "PINECONE_INDEX_NAME"
]
missing = [k for k in required if k not in env or not env[k]]
if missing:
    print(f"  [FAIL] Missing: {missing}")
    results.append(False)
else:
    print(f"  [PASS] All 11 keys present")
    results.append(True)

# --- CHECK 2: ANTHROPIC ---
print("\n[2/5] Checking Anthropic API (Haiku 4.5)...")
try:
    import anthropic
    client = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=20,
        messages=[{"role": "user", "content": "Say OK"}]
    )
    reply = msg.content[0].text.strip()
    print(f"  [PASS] Haiku responded: {reply}")
    results.append(True)
except Exception as e:
    print(f"  [FAIL] {e}")
    results.append(False)

# --- CHECK 3: NSE DATA (nsetools) ---
print("\n[3/5] Checking NSE Data (nsetools)...")
try:
    from nsetools import Nse
    nse = Nse()
    quote = nse.get_quote("sbin")
    if quote:
        print(f"  [PASS] SBIN fetched — LTP: {quote.get('lastPrice', 'N/A')}")
        results.append(True)
    else:
        print(f"  [FAIL] No data returned")
        results.append(False)
except Exception as e:
    print(f"  [FAIL] {e}")
    results.append(False)

# --- CHECK 4: TELEGRAM ---
print("\n[4/5] Checking Telegram (3 channels)...")
try:
    import urllib.request, urllib.parse, json
    bot_token = env["TELEGRAM_BOT_TOKEN"]
    channels = {
        "MOVERS":  env["TELEGRAM_MOVERS_CHANNEL"],
        "LT_PICK": env["TELEGRAM_LT_CHANNEL"],
        "SWING":   env["TELEGRAM_SWING_CHANNEL"],
    }
    all_ok = True
    for name, chat_id in channels.items():
        msg_text = f"StockMarket-Brain Health Check OK — {name} channel active"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": msg_text
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=data
        )
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read())
            if res.get("ok"):
                print(f"  [PASS] {name} — message sent")
            else:
                print(f"  [FAIL] {name} — {res}")
                all_ok = False
    results.append(all_ok)
except Exception as e:
    print(f"  [FAIL] {e}")
    results.append(False)

# --- CHECK 5: SUPABASE ---
print("\n[5/5] Checking Supabase...")
try:
    from supabase import create_client
    sb = create_client(env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"])
    # Simple connectivity test
    res = sb.table("filings_log").select("*").limit(1).execute()
    print(f"  [PASS] Supabase connected")
    results.append(True)
except Exception as e:
    err = str(e)
    if "relation" in err or "does not exist" in err or "42P01" in err:
        print(f"  [PASS] Supabase connected (table not created yet — OK)")
        results.append(True)
    else:
        print(f"  [FAIL] {e}")
        results.append(False)

# --- SUMMARY ---
print("\n" + "=" * 50)
passed = sum(results)
total  = len(results)
if passed == total:
    print(f"  ALL SYSTEMS OPERATIONAL ({passed}/{total} checks passed)")
    print("  Ready to build Tier-0 Agent!")
else:
    print(f"  {passed}/{total} checks passed — fix failures above")
print("=" * 50)
