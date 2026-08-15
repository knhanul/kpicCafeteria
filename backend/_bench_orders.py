import http.cookiejar
import json
import time
import urllib.request

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/auth/login",
    data=json.dumps({"username": "admin", "password": "change-me"}).encode(),
    headers={"Content-Type": "application/json"},
)
op.open(req)

for start, end in [("2026-08-03", "2026-08-04"), ("2026-07-27", "2026-08-07"), ("2026-06-01", "2026-08-04")]:
    t = time.time()
    data = json.loads(op.open(f"http://127.0.0.1:8000/api/orders?start_date={start}&end_date={end}").read())
    dt = time.time() - t
    total_menus = sum(len(i["menus"]) for i in data["items"])
    payload = len(json.dumps(data, ensure_ascii=False).encode())
    print(f"{start}~{end}: elapsed={dt:.2f}s items={len(data['items'])} menus={total_menus} payload={payload/1024:.0f}KB")
