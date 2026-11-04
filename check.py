# Irish Ferries Ireland/France sailing updates: extract sailings, diff with the
# previous run (state.json next to this script), print changes.
import html, json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

URL = "https://www.irishferries.com/ie-en/sailing-updates/ireland-france/"
STATE = Path(__file__).with_name("state.json")
WATCH = "Dublin - Cherbourg 05/11/26 16:30"  # the only sailing that triggers alerts
TOPIC = Path(__file__).with_name("topic").read_text().strip()


# Points along the Dublin → Cherbourg route, with the UTC hour the ship should
# be there (dep. 16:30 GMT on 5/11, arr. 12:30 CET on 6/11).
ROUTE = [
    ("Mare d'Irlanda", 53.0, -5.8, "2026-11-05T18:00"),
    ("Canale di San Giorgio", 51.8, -6.0, "2026-11-05T21:00"),
    ("Largo della Cornovaglia", 50.3, -5.8, "2026-11-06T02:00"),
    ("Manica", 49.9, -3.0, "2026-11-06T07:00"),
]
COMPASS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def fetch(url, data=None, headers=None, tries=3):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers or {}), timeout=30).read()
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def sea_state(h):
    for limit, name in ((0.5, "calmo"), (1.25, "poco mosso"), (2.5, "mosso"), (4, "molto mosso"), (6, "agitato")):
        if h < limit:
            return name
    return "molto agitato"


def sea():
    """Forecast waves + wind at each route point (Open-Meteo, no key)."""
    q = {
        "latitude": ",".join(str(p[1]) for p in ROUTE),
        "longitude": ",".join(str(p[2]) for p in ROUTE),
        "timezone": "UTC",
        "start_date": "2026-11-05",
        "end_date": "2026-11-06",
    }
    enc = lambda extra: urllib.parse.urlencode({**q, **extra})
    marine = json.loads(fetch("https://marine-api.open-meteo.com/v1/marine?" + enc({"hourly": "wave_height,wave_period"})))
    wind = json.loads(fetch("https://api.open-meteo.com/v1/forecast?" + enc({"hourly": "wind_speed_10m,wind_gusts_10m,wind_direction_10m", "wind_speed_unit": "kn"})))
    out = []
    for (name, _, _, t), m, w in zip(ROUTE, marine, wind):
        i = m["hourly"]["time"].index(t)
        hw, per = m["hourly"]["wave_height"][i], m["hourly"]["wave_period"][i]
        ws, wg, wd = (w["hourly"][k][w["hourly"]["time"].index(t)] for k in ("wind_speed_10m", "wind_gusts_10m", "wind_direction_10m"))
        out.append(f"• {name} ({t[8:10]}/11 {t[11:]} UTC): onde {hw:.1f} m ({sea_state(hw)}, {per:.0f}s), vento {ws:.0f} kn da {COMPASS[round(wd / 45) % 8]}, raffiche {wg:.0f}")
    return "Meteo mare sulla rotta:\n" + "\n".join(out)


def push(title, body):
    try:
        body += "\n\n" + sea()
    except Exception as e:  # the ferry alert matters more than the forecast
        body += f"\n\n(meteo mare non disponibile: {e})"
    # Telegram (Mnemo's bot) when TG_TOKEN/TG_CHAT are set, else ntfy.sh.
    token, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
    if token and chat:
        data = urllib.parse.urlencode({"chat_id": chat, "text": f"⛴ {title}\n{body}", "disable_web_page_preview": "true"})
        fetch(f"https://api.telegram.org/bot{token}/sendMessage", data.encode())
        return
    fetch(f"https://ntfy.sh/{TOPIC}", body.encode(), {"Title": title, "Priority": "high", "Tags": "ferry"})


raw = fetch(URL, headers={"User-Agent": "Mozilla/5.0"}).decode("utf-8", "ignore")
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

# Tell the workflow loop to stop once the sailing has left.
w = sailings.get(WATCH)
if (w and w["status"] == "Departed") or (not w and time.time() > 1793986200):  # 2026-11-05 17:30 UTC
    print("PARTITO")

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
