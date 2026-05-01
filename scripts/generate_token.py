import json, re, webbrowser, urllib.parse, urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

env = {}
with open(".env") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

API_KEY    = env["UPSTOX_API_KEY"]
API_SECRET = env["UPSTOX_API_SECRET"]
REDIRECT   = "http://127.0.0.1:5000/callback"

params = urllib.parse.urlencode({
    "client_id": API_KEY,
    "redirect_uri": REDIRECT,
    "response_type": "code",
})
auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?{params}"
print(f"Opening Upstox login in browser...")
webbrowser.open(auth_url)

captured = {}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            captured["code"] = qs["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Login successful! Return to PowerShell.</h2>")
            print("Auth code captured!")
        else:
            self.send_response(400)
            self.end_headers()
    def log_message(self, *args): pass

print("Waiting for Upstox login...")
server = HTTPServer(("127.0.0.1", 5000), Handler)
server.handle_request()

if "code" not in captured:
    print("No auth code received.")
    exit(1)

data = urllib.parse.urlencode({
    "code":          captured["code"],
    "client_id":     API_KEY,
    "client_secret": API_SECRET,
    "redirect_uri":  REDIRECT,
    "grant_type":    "authorization_code",
}).encode()

req = urllib.request.Request(
    "https://api.upstox.com/v2/login/authorization/token",
    data=data,
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Api-Version": "2.0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Origin": "https://api.upstox.com",
        "Referer": "https://api.upstox.com/"
    }
)

try:
    with urllib.request.urlopen(req) as resp:
        token_data = json.loads(resp.read())
except urllib.error.HTTPError as e:
    print(f"Error {e.code}: {e.read().decode()}")
    exit(1)

access_token = token_data.get("access_token")
if not access_token:
    print(f"Token error: {token_data}")
    exit(1)

print(f"Token received! ({len(access_token)} chars)")

with open(".env", "r") as f:
    content = f.read()

content = re.sub(r"UPSTOX_ACCESS_TOKEN=.*", f"UPSTOX_ACCESS_TOKEN={access_token}", content)

with open(".env", "w") as f:
    f.write(content)

print(".env updated! Ready for Health Check!")
