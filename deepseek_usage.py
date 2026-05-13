#!/usr/bin/env python3
"""DeepSeek API Usage Monitor"""
import json, os, re, sys, time, uuid
from pathlib import Path
from datetime import datetime

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

CFG = Path(__file__).parent / ".deepseek_config.json"
TOKEN_FILE = Path(__file__).parent / ".deepseek_token.json"
PLATFORM = "https://platform.deepseek.com"
LOGIN_URL = PLATFORM + "/auth-api/v0/users/login"

def load_config():
    if not CFG.exists():
        print(f"[Error] Config file {CFG} not found")
        sys.exit(1)
    raw = CFG.read_text(encoding="utf-8").strip()
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
            return d.get("username",""), d.get("password",""), d.get("area_code","+86")
        except: pass
    m = re.search(r"username\s*[=:]\s*(\S+)", raw, re.IGNORECASE)
    p = re.search(r"password\s*[=:]\s*(\S+)", raw, re.IGNORECASE)
    u = m.group(1) if m else ""
    pw = p.group(1) if p else ""
    if u and pw: return u, pw, "+86"
    print("[Error] Cant parse config")
    sys.exit(1)

USERNAME, PASSWORD, AREA_CODE = load_config()
hdr = {"User-Agent":"DeepSeekUsage/1.0","Content-Type":"application/json","x-app-version":"1.0.0","Origin":PLATFORM}

def http_post(url, jd):
    if HAS_REQUESTS:
        r = requests.post(url, json=jd, headers=hdr, timeout=15)
        return r.status_code, r.text
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    try:
        with urlopen(Request(url, data=json.dumps(jd).encode(), headers=dict(hdr), method="POST"), timeout=15) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")

def http_get(url, token):
    h = {"User-Agent":"DeepSeekUsage/1.0","x-app-version":"1.0.0","Authorization":"Bearer "+token}
    if HAS_REQUESTS:
        r = requests.get(url, headers=h, timeout=15)
        return r.status_code, r.text
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    try:
        with urlopen(Request(url, headers=h), timeout=15) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")

def login():
    payload = {"email":"","mobile":USERNAME,"password":PASSWORD,"area_code":AREA_CODE,"device_id":uuid.uuid4().hex,"os":"web"}
    code, text = http_post(LOGIN_URL, payload)
    if code != 200: return None
    try:
        j = json.loads(text)
        if j.get("code") == 0 and "data" in j:
            token = j["data"].get("biz_data",{}).get("user",{}).get("token","")
            if token:
                TOKEN_FILE.write_text(json.dumps({"token":token,"time":time.time()}), encoding="utf-8")
                return token
    except: pass
    return None

def load_token():
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("token","")
        except: pass
    return None

def fetch_all(token):
    now = datetime.now()
    out = {}
    for name, url in [
        ("summary", PLATFORM+"/api/v0/users/get_user_summary"),
        ("amount", f"{PLATFORM}/api/v0/usage/amount?month={now.month}&year={now.year}"),
        ("cost", f"{PLATFORM}/api/v0/usage/cost?month={now.month}&year={now.year}"),
    ]:
        code, text = http_get(url, token)
        if code == 401: return None
        if code == 200:
            try: out[name] = json.loads(text)
            except: pass
    return out if out else None

def run():
    token = load_token()
    if token:
        data = fetch_all(token)
        if data is None:
            token = None
    if not token:
        token = login()
        if not token: return None
        data = fetch_all(token)
        if data is None: return None
    return data

# ── Display helpers ────────────────────────────────────────────────

def _fmt(n):
    """Format number with commas"""
    try: return f"{int(float(n)):,}"
    except: return str(n)

def _fmt_money(n):
    try: return f"\u00a5{float(n):.2f}"
    except: return str(n)

def _safe(d, *keys, default=""):
    for k in keys:
        if isinstance(d, dict): d = d.get(k, default)
        else: return default
    return d if d is not None else default

def display_detailed(data):
    'Full detailed display for single-run mode'
    try:
        bd = _safe(data,"summary","data","biz_data", default={})
        amounts = _safe(data,"amount","data","biz_data", default={})
        cr = _safe(data,"cost","data","biz_data", default=[])
        costs = cr[0] if isinstance(cr, list) and cr else {}
    except:
        print("Parse error")
        return
    mt = _safe(bd,"monthly_token_usage", default="0")
    cl = _safe(bd,"current_token", default=0)
    try:
        pct = int(float(mt)) / int(cl) * 100 if int(cl) > 0 else 0
    except:
        pct = 0
    bal = _safe(bd.get("normal_wallets",[{}])[0] if bd.get("normal_wallets") else {},"balance", default="0")
    mc = _safe(bd.get("monthly_costs",[{}])[0] if bd.get("monthly_costs") else {},"amount", default="0")
    te = _safe(bd.get("normal_wallets",[{}])[0] if bd.get("normal_wallets") else {},"token_estimation", default="0")
    print()
    print("  " + "-" * 50)
    print("  Account Overview")
    print("  " + "-" * 50)
    print(f"  Monthly Tokens Used:   {_fmt(mt):>15}")
    print(f"  Monthly Token Limit:  {_fmt(cl):>15}")
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "#" * min(filled, bar_len) + "." * max(bar_len - filled, 0)
    print(f"  Usage: [{bar}] {pct:.1f}%")
    print()
    print(f"  Balance:                {_fmt_money(bal):>15}")
    print(f"  Monthly Cost:           {_fmt_money(mc):>15}")
    print(f"  Est. Remaining Tokens:  {_fmt(te):>15}")
    print("  " + "-" * 50)
    print()
    tl = amounts.get("total", [])
    if tl:
        print("  " + "-" * 72)
        print("  Model Usage - This Month")
        print("  " + "-" * 72)
        print(f"  {'Model':<30} {'Cache Hit':>10} {'Cache Miss':>10} {'Output':>8} {'Calls':>6}")
        print("  " + "-" * 72)
        for m in tl:
            nm = m.get("model","")
            um = {u['type']: u['amount'] for u in m.get("usage",[])}
            h = _fmt(um.get("PROMPT_CACHE_HIT_TOKEN","0"))
            ms = _fmt(um.get("PROMPT_CACHE_MISS_TOKEN","0"))
            o = _fmt(um.get("RESPONSE_TOKEN","0"))
            r = _fmt(um.get("REQUEST","0"))
            print(f"  {nm:<30} {h:>10} {ms:>10} {o:>8} {r:>6}")
        print("  " + "-" * 72)
        print()
    cd = costs.get("days", []) if isinstance(costs, dict) else []
    if cd:
        cur = costs.get("currency","CNY") if isinstance(costs, dict) else "CNY"
        print("  " + "-" * 72)
        print("  Daily Cost - Last 3 Days")
        print("  " + "-" * 72)
        print(f"  {'Date':<12} {'Model':<28} {'Cost':>14} {'Curr':>8}")
        print("  " + "-" * 72)
        for d in cd[-3:]:
            dt = d.get("date","")
            for item in d.get("data",[]):
                tc = sum(float(u.get("amount","0")) for u in item.get("usage",[]))
                print(f"  {dt:<12} {item.get('model',''):<28} {_fmt_money(str(tc)):>14} {cur:>8}")
        print("  " + "-" * 72)
        print()
def display_compact(data):
    """One-line summary for loop mode"""
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        bd = _safe(data,"summary","data","biz_data", default={})
        tokens = _safe(bd,"monthly_token_usage", default="?")
        cost = _safe(bd.get("monthly_costs",[{}])[0] if bd.get("monthly_costs") else {},"amount",default="?")
        bal = _safe(bd.get("normal_wallets",[{}])[0] if bd.get("normal_wallets") else {},"balance",default="?")
        print(f"  [{ts}] Tokens:{_fmt(tokens):>10}  Cost:{_fmt_money(cost):>8}  Balance:{_fmt_money(bal):>8}")
    except:
        print(f"  [{ts}] Parse error")

def save_output(data):
    out = Path(__file__).parent / "output"
    out.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (out / f"usage_{ts}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    import sys as _sys
    loop = "--loop" in _sys.argv or "-l" in _sys.argv
    interval = 60
    for a in _sys.argv[1:]:
        if a.startswith("--interval="): interval = int(a.split("=")[1])
        if a.startswith("-i="): interval = int(a.split("=")[1])

    print(f"\n{"="*60}")
    print("  DeepSeek API Usage Monitor")
    print(f"  Mode: {'loop every ' + str(interval) + 's' if loop else 'once'}")
    print(f"{"="*60}")

    if loop:
        print(f"  Ctrl+C to stop\n")
        while True:
            data = run()
            if data:
                display_compact(data)
                save_output(data)
            else:
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] Failed")
            time.sleep(interval)
    else:
        data = run()
        if data:
            display_detailed(data)
            save_output(data)
            print(f"  \U0001f4be Saved to output/")
        else:
            print("  Failed to fetch data")
            _sys.exit(1)