# Irish Ferries Ireland/France sailing updates: extract sailings, diff with the
# previous run (state.json next to this script), print changes.
import html, json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path

URL = "https://www.irishferries.com/ie-en/sailing-updates/ireland-france/"
STATE = Path(__file__).with_name("state.json")
WATCH = "Dublin - Cherbourg 05/11/26 16:30"  # the only sailing that triggers alerts
TOPIC = Path(__file__).with_name("topic").read_text().strip()


def push(title, body):
    # Telegram (Mnemo's bot) when TG_TOKEN/TG_CHAT are set, else ntfy.sh.
    token, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
    if token and chat:
        data = urllib.parse.urlencode({"chat_id": chat, "text": f"⛴ {title}\n{body}", "disable_web_page_preview": "true"})
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data.encode(), timeout=20)
        return
    r = urllib.request.Request(f"https://ntfy.sh/{TOPIC}", data=body.encode(), headers={"Title": title, "Priority": "high", "Tags": "ferry"})
    urllib.request.urlopen(r, timeout=20)


req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
raw = re.sub(r"(?s)<(script|style|noscript)[^>]*>.*?</\1>", "", raw)
lines = [l.strip() for l in html.unescape(re.sub(r"<[^>]+>", "\n", raw)).splitlines() if l.strip()]

sailings = {}
for i, l in enumerate(lines):
    if re.fullmatch(r"(Dublin|Rosslare|Cherbourg) - (Dublin|Rosslare|Cherbourg)", l) and i + 6 < len(lines):
        dd, dt, ad, at, ship, status = lines[i + 1 : i + 7]
        if re.fullmatch(r"\d\d/\d\d/\d\d", dd):
            sailings[f"{l} {dd} {dt}"] = {"arrival": f"{ad} {at}", "ship": ship, "status": status}

if not sailings:
    print("ERRORE: nessuna partenza trovata, la pagina potrebbe essere cambiata")
    push("Irish Ferries: controllo non riuscito", "Nessuna partenza trovata, la pagina potrebbe essere cambiata.\n" + URL)
    sys.exit(1)

# Proof the page was really read: page size, sailings found, the 16:30 ones.
print(f"pagina letta: {len(raw)} caratteri, {len(sailings)} partenze")
for k, v in sailings.items():
    if k.endswith(" 16:30"):
        print(f"  16:30 → {k}: {v['status']}, {v['ship']}, arrivo {v['arrival']}")

old = json.loads(STATE.read_text()) if STATE.exists() else None
STATE.write_text(json.dumps(sailings, indent=1))

if old is None:
    print("PRIMO CONTROLLO")
    for k, v in sailings.items():
        print(f"  {k} → arrivo {v['arrival']}, {v['ship']}, {v['status']}")
    sys.exit(0)

changes = []
for k, v in sailings.items():
    o = old.get(k)
    if o is None:
        if v["status"] not in ("On Time", "Departed"):
            changes.append(f"NUOVA {k}: {v['status']} ({v['ship']})")
        continue
    for f in ("status", "arrival", "ship"):
        if o[f] != v[f] and not (f == "status" and v[f] == "Departed"):
            changes.append(f"{k}: {f} {o[f]} → {v[f]}")
# A sailing that vanished while its date is still shown = likely cancelled.
shown_dates = {k.split()[3] for k in sailings}
for k in old:
    if k not in sailings and k.split()[3] in shown_dates:
        changes.append(f"SPARITA {k} (era {old[k]['status']})")

changes = [c for c in changes if WATCH in c]
if WATCH in sailings and "--test" in sys.argv:
    v = sailings[WATCH]
    push("Irish Ferries: controllo attivo", f"{WATCH} → {v['status']}, {v['ship']}, arrivo {v['arrival']}\n{URL}")

if changes:
    print("CAMBIAMENTI:\n  " + "\n  ".join(changes))
    push("Irish Ferries: cambiamento", "\n".join(changes) + "\n" + URL)
else:
    print("NESSUN CAMBIAMENTO")
    # Requested: a "tutto ok" on every check too, until the sailing has left.
    v = sailings.get(WATCH)
    if v and v["status"] != "Departed":
        push("Irish Ferries: tutto ok", f"{WATCH} → {v['status']}, {v['ship']}, arrivo {v['arrival']}")
