#!/usr/bin/env python3
"""
Dadash News Bot – poster news og sessionsåbninger i Discord.

Køres hvert 5. minut (GitHub Actions). Hver kørsel tjekker, om der er noget,
der skal postes lige nu, og husker i state.json hvad der allerede er sendt,
så intet bliver postet to gange.

Datakilde: ForexFactory-kalenderens offentlige JSON (denne uge).
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------- indstillinger
DK = ZoneInfo("Europe/Copenhagen")
FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
STATE_FILE = Path(__file__).with_name("state.json")

IMPACTS = {"High": "🔴", "Medium": "🟠"}          # røde + orange
MY_CURRENCIES = {"USD", "AUD", "CHF", "JPY", "GBP"}  # markeres med ⭐
CURRENCIES = None   # None = alle valutaer. Fx {"USD","AUD"} for kun nogle.

MORNING_AT = (7, 30)       # morgenoversigt kl. 07:30 dansk tid (man–fre)
NO_TRADE_BEFORE = 60       # min før news: ingen trades
NO_TRADE_AFTER = 15        # min efter news: ingen trades
FEED_REFRESH_MIN = 60      # hent kalenderen max én gang i timen

# Sessionsåbninger i børsens egen tidszone -> omregnes automatisk til dansk tid
SESSIONS = [
    ("asia", "🌏 **Asia (Tokyo) åbner kl. {t}**\nIngen trades de første 3 timer (til kl. {t3}).", "Asia/Tokyo", 9, 0),
    ("frankfurt", "🇩🇪 **Frankfurt åbner kl. {t}**", "Europe/Berlin", 8, 0),
    ("london", "🇬🇧 **London åbner kl. {t}**\nVent 15 min før entry (til kl. {t15}).", "Europe/London", 8, 0),
    ("ny", "🇺🇸 **New York åbner kl. {t}**\nVent 15 min før entry (til kl. {t15}). Husk: ingen trades efter 20:00.", "America/New_York", 9, 30),
]

NAMES = {"frankfurt": "Frankfurt", "london": "London", "ny": "NY"}
DAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]


# ---------------------------------------------------------------- hjælpere
def now_utc() -> datetime:
    """Nu (kan overstyres med NOW=2026-11-06T13:31+01:00 til test)."""
    if os.environ.get("NOW"):
        return datetime.fromisoformat(os.environ["NOW"]).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def hm(dt: datetime) -> str:
    return dt.astimezone(DK).strftime("%H:%M")


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"sent": {}, "cache": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def fetch_events(state: dict, now: datetime) -> list:
    cache = state.setdefault("cache", {})
    fetched = cache.get("fetched")
    fresh = fetched and now - datetime.fromisoformat(fetched) < timedelta(minutes=FEED_REFRESH_MIN)
    if not fresh or os.environ.get("FEED_FILE"):
        try:
            if os.environ.get("FEED_FILE"):           # til test
                data = json.loads(Path(os.environ["FEED_FILE"]).read_text())
            else:
                req = urllib.request.Request(FEED_URL, headers={"User-Agent": "dadash-news-bot"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = json.loads(r.read().decode("utf-8"))
            if isinstance(data, list) and data:
                cache["events"] = data
                cache["fetched"] = now.isoformat()
        except Exception as e:  # brug gemt kalender hvis hentning fejler
            print(f"Kunne ikke hente kalenderen: {e}", file=sys.stderr)
    return cache.get("events", [])


def parse(events: list):
    """-> (news, holidays). news: liste af dicts med 'dt' (UTC)."""
    news, holidays = [], []
    for e in events:
        try:
            dt = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
        except Exception:
            continue
        cur = (e.get("country") or "").upper()
        if CURRENCIES and cur not in CURRENCIES:
            continue
        item = {"dt": dt, "cur": cur, "title": e.get("title", ""), "impact": e.get("impact", ""),
                "forecast": e.get("forecast") or "", "previous": e.get("previous") or ""}
        if item["impact"] == "Holiday":
            holidays.append(item)
        elif item["impact"] in IMPACTS:
            news.append(item)
    news.sort(key=lambda x: (x["dt"], x["impact"] != "High", x["cur"]))
    return news, holidays


def line(n: dict, with_time=True) -> str:
    star = " ⭐" if n["cur"] in MY_CURRENCIES else ""
    fp = []
    if n["forecast"]:
        fp.append(f"forv. {n['forecast']}")
    if n["previous"]:
        fp.append(f"før {n['previous']}")
    extra = f" ({' | '.join(fp)})" if fp else ""
    t = f"{hm(n['dt'])} " if with_time else ""
    return f"{IMPACTS[n['impact']]} {t}**{n['cur']}** – {n['title']}{extra}{star}"


def group_by_time(news: list) -> dict:
    groups = {}
    for n in news:
        groups.setdefault(n["dt"], []).append(n)
    return groups


def no_trade_windows(times: list) -> list:
    """Slår overlappende 'ingen trades'-vinduer sammen."""
    wins = []
    for t in sorted(times):
        s, e = t - timedelta(minutes=NO_TRADE_BEFORE), t + timedelta(minutes=NO_TRADE_AFTER)
        if wins and s <= wins[-1][1]:
            wins[-1][1] = max(wins[-1][1], e)
        else:
            wins.append([s, e])
    return wins


def curs(group: list) -> str:
    return "/".join(sorted({n["cur"] for n in group}))


# ---------------------------------------------------------------- beskeder
def morning(now, news, holidays):
    today = now.astimezone(DK).date()
    todays = [n for n in news if n["dt"].astimezone(DK).date() == today]
    hols = [h for h in holidays if h["dt"].astimezone(DK).date() == today]
    d = now.astimezone(DK)
    out = [f"📅 **Dagens news – {DAYS[d.weekday()]} {d.day}/{d.month}**", ""]
    if todays:
        out += [line(n) for n in todays]
        out.append("")
        wins = no_trade_windows(list({n["dt"] for n in todays}))
        out.append("⛔ **Ingen trades:** " + ", ".join(f"{hm(s)}–{hm(e)}" for s, e in wins))
    else:
        out.append("✅ Ingen røde eller orange news i dag.")
    for h in hols:
        out.append(f"🏖️ **{h['cur']}** – {h['title']} (lav likviditet i {h['cur']}-par)")
    sess = []
    for key, _, tz, H, M in SESSIONS:
        if key == "asia":
            continue
        sdt = session_time(d.replace(hour=12), tz, H, M)
        sess.append(f"{NAMES[key]} {hm(sdt)}")
    out += ["", "🕐 " + " · ".join(sess), "⚠️ Ingen trades efter 20:00. ⭐ = dine valutaer"]
    return "\n".join(out)


def session_time(dk_day: datetime, tz: str, H: int, M: int) -> datetime:
    """Åbningstid for sessionen på den børs-dato der svarer til dk_day."""
    z = ZoneInfo(tz)
    local_date = dk_day.astimezone(z).date()
    return datetime(local_date.year, local_date.month, local_date.day, H, M, tzinfo=z)


def run(now: datetime, state: dict) -> list:
    sent = state.setdefault("sent", {})
    msgs = []

    def once(key, text):
        if key not in sent:
            msgs.append(text)
            sent[key] = now.isoformat()

    news, holidays = parse(fetch_events(state, now))
    dk_now = now.astimezone(DK)
    weekday = dk_now.weekday() < 5

    # 1) Morgenoversigt
    mh, mm = MORNING_AT
    start = dk_now.replace(hour=mh, minute=mm, second=0, microsecond=0)
    if weekday and start <= dk_now < start + timedelta(hours=4):
        once(f"morning:{dk_now.date()}", morning(now, news, holidays))

    # 2) News-påmindelser (grupperet pr. tidspunkt)
    for t, group in group_by_time(news).items():
        mins = (t - now).total_seconds() / 60
        k = t.isoformat()
        body = "\n".join(line(n, with_time=False) for n in group)
        end = hm(t + timedelta(minutes=NO_TRADE_AFTER))
        if 16 <= mins <= 65:
            once(f"1h:{k}", f"⚠️ **{curs(group)} news kl. {hm(t)}** (om ca. {round(mins)} min)\n{body}\n\n"
                            f"⛔ **Ingen trades fra nu til kl. {end}.**")
        elif -1 <= mins < 16:
            sent.setdefault(f"1h:{k}", now.isoformat())  # spring 1-times beskeden over hvis vi er for sent på den
            once(f"15m:{k}", f"⏰ **Om {max(0, round(mins))} min: {curs(group)} news kl. {hm(t)}**\n{body}\n\n"
                             f"Luk eller sæt dine trades på BE nu. Spreads bliver brede.")
        elif -60 <= mins <= -NO_TRADE_AFTER:
            nxt = [u for u in group_by_time(news) if now < u <= now + timedelta(minutes=120)]
            tail = (f"\n⚠️ Næste news kl. {hm(min(nxt))}: ingen trades fra kl. "
                    f"{hm(min(nxt) - timedelta(minutes=NO_TRADE_BEFORE))}." if nxt else "")
            once(f"done:{k}", f"✅ **{curs(group)} news fra kl. {hm(t)} er ude.**\n"
                              f"Lad støvet lægge sig og tjek strukturen før du trader.{tail}")

    # 3) Sessionsåbninger
    for key, text, tz, H, M in SESSIONS:
        for day_shift in (0, 1):
            dk_day = (dk_now + timedelta(days=day_shift)).replace(hour=12)
            sdt = session_time(dk_day, tz, H, M)
            if sdt.astimezone(ZoneInfo(tz)).weekday() >= 5:
                continue
            mins = (sdt - now).total_seconds() / 60
            if -20 <= mins <= 6:
                fmt = dict(t=hm(sdt), t3=hm(sdt + timedelta(hours=3)), t15=hm(sdt + timedelta(minutes=15)))
                once(f"sess:{key}:{sdt.date()}", text.format(**fmt))

    # ryd gamle nøgler (ældre end 10 dage)
    cutoff = now - timedelta(days=10)
    state["sent"] = {k: v for k, v in sent.items() if datetime.fromisoformat(v) > cutoff}
    return msgs


def post(text: str) -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url or os.environ.get("DRY_RUN"):
        print("---- (ikke sendt) ----\n" + text + "\n")
        return
    for i in range(0, len(text), 1900):  # Discord max 2000 tegn
        body = json.dumps({"content": text[i:i + 1900], "username": "Dadash News"}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "dadash-news-bot"})
        urllib.request.urlopen(req, timeout=20).read()


# ---------------------------------------------------------------- resultater (actual)
JB_URL = "https://www.jblanked.com/news/api/forex-factory/calendar/week/"
JB_MIN_GAP = 300           # gratis nøgle: max 1 kald pr. 5 min
RESULT_TRIES = 3           # prøv ved ca. +1, +6 og +11 min

# Hvor lavere tal = godt for valutaen
INVERSE = ("unemployment rate", "unemployment claims", "jobless", "claimant count", "unemployment change")
EFFECTS = {   # hvis valutaen er STÆRK
    "USD": [("USDCHF", 1), ("USDJPY", 1), ("AUDUSD", -1), ("GBPUSD", -1), ("Guld", -1)],
    "AUD": [("AUDUSD", 1), ("AUDCHF", 1), ("AUDJPY", 1)],
    "GBP": [("GBPUSD", 1)],
    "CHF": [("USDCHF", -1), ("AUDCHF", -1)],
    "JPY": [("USDJPY", -1), ("AUDJPY", -1)],
    "EUR": [("EURUSD", 1)],
    "CAD": [("USDCAD", -1)],
    "NZD": [("NZDUSD", 1)],
}

_sim = {"t": None}


def clock() -> datetime:
    return _sim["t"] if _sim["t"] else datetime.now(timezone.utc)


def sleep(sec: float) -> None:
    if _sim["t"]:
        _sim["t"] += timedelta(seconds=sec)
    else:
        import time
        time.sleep(sec)


def num(v):
    """'165K' -> 165000, '0.4%' -> 0.4, '-4.7K' -> -4700, '7.523M' -> 7.523e6"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("<", "").replace(">", "")
    if not s:
        return None
    mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
    try:
        if s[-1] == "%":
            return float(s[:-1])
        if s[-1].upper() in mult:
            return float(s[:-1]) * mult[s[-1].upper()]
        return float(s)
    except ValueError:
        return None


def norm(t: str) -> str:
    return "".join(c for c in t.lower() if c.isalnum())


def fetch_actuals(state: dict, now: datetime) -> list:
    key = os.environ.get("JBLANKED_API_KEY")
    if os.environ.get("JB_FILE"):                         # til test
        return json.loads(Path(os.environ["JB_FILE"]).read_text())
    if not key:
        return []
    state["jb_last"] = now.isoformat()
    req = urllib.request.Request(JB_URL, headers={"Authorization": f"Api-Key {key}",
                                                  "Content-Type": "application/json",
                                                  "User-Agent": "dadash-news-bot"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data if isinstance(data, list) else data.get("data", data.get("results", []))
    except Exception as e:
        print(f"Kunne ikke hente actuals: {e}", file=sys.stderr)
        return []


def match_actual(n: dict, rows: list):
    want = norm(n["title"])
    day = n["dt"].date()

    def row_day(r):
        try:
            return datetime.strptime(str(r.get("Date") or r.get("date"))[:10].replace("-", "."), "%Y.%m.%d").date()
        except Exception:
            return None

    exact, loose = [], []
    for r in rows:
        cur = (r.get("Currency") or r.get("currency") or "").upper()
        name = norm(r.get("Name") or r.get("name") or "")
        if cur != n["cur"] or not name:
            continue
        d = row_day(r)
        if d and abs((d - day).days) > 1:      # samme dag (± tidszone)
            continue
        if name == want:
            exact.append(r)
        elif name in want or want in name:
            loose.append(r)
    for r in exact + loose:
        a = r.get("Actual", r.get("actual"))
        if a not in (None, "", "None") and num(a) is not None:
            return str(a)
    return None


def fmt_actual(a: str, like: str) -> str:
    """Viser actual med samme enhed som forecast/previous, fx 165000 eller 165 -> 165K."""
    if not a or any(a.endswith(u) for u in "%KMBT"):
        return a
    import math
    v = num(a)
    like = (like or "").strip()
    unit = next((u for u in "%KMBT" if like.endswith(u)), "")
    if unit and unit != "%":
        div = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[unit]
        ref = abs(num(like[:-1]) or 0)
        if v and ref:   # vælg den skala, der ligger tættest på forventningen
            v = min((v, v / div), key=lambda x: abs(math.log10(abs(x)) - math.log10(ref)))
        elif abs(v) >= div:
            v = v / div
    return f"{round(v, 3):g}{unit}"


def verdict(group: list, actuals: dict) -> str:
    lines, scores = [], {}
    for n in group:
        a = actuals.get(id(n))
        if a is None:
            lines.append(f"{IMPACTS[n['impact']]} {n['title']}: *ikke ude endnu*")
            continue
        shown = fmt_actual(a, n["forecast"] or n["previous"])
        base = num(n["forecast"]) if num(n["forecast"]) is not None else num(n["previous"])
        av = num(shown)
        inv = any(w in n["title"].lower() for w in INVERSE)
        mark, sign = "⚪ som ventet", 0
        if base is not None and av is not None and av != base:
            better = (av > base) != inv
            sign = 1 if better else -1
            mark = "🟢 bedre" if better else "🔴 dårligere"
        tag = " (lavere = bedre)" if inv and sign else ""
        fp = " | ".join(x for x in [f"forv. {n['forecast']}" if n["forecast"] else "",
                                    f"før {n['previous']}" if n["previous"] else ""] if x)
        lines.append(f"{IMPACTS[n['impact']]} **{n['cur']}** {n['title']}: **{shown}** ({fp}) {mark}{tag}")
        w = 3 if any(k in n["title"].lower() for k in ("non-farm", "cpi", "rate statement", "cash rate",
                                                       "interest rate", "gdp", "employment change")) else \
            (2 if n["impact"] == "High" else 1)
        big = False
        if base not in (None, 0) and av is not None:
            big = (abs(av - base) >= 0.2) if "%" in (n["forecast"] or "") else abs(av - base) / abs(base) >= 0.5
        scores.setdefault(n["cur"], []).append(sign * w * (1.5 if big else 1))
    out = list(lines)
    for cur, sc in scores.items():
        total = sum(sc)
        out.append("")
        if total > 0:
            head = f"💪 **Stærkt for {cur}**" + (" – stor overraskelse" if total >= 4 else "")
            d = 1
        elif total < 0:
            head = f"📉 **Svagt for {cur}**" + (" – stor overraskelse" if total <= -4 else "")
            d = -1
        else:
            out.append(f"➖ **{cur}: blandet / som ventet** – ingen klar retning.")
            continue
        out.append(head)
        eff = EFFECTS.get(cur, [])
        if eff:
            out.append("Forventet retning: " + " · ".join(f"{p} {'⬆️' if s * d > 0 else '⬇️'}" for p, s in eff))
    return "\n".join(out)


def results_loop(state: dict) -> None:
    """Hvis røde/orange news kommer inden for 12 min: bliv kørende, hent actuals og post dem."""
    has_key = os.environ.get("JBLANKED_API_KEY") or os.environ.get("JB_FILE")
    if not has_key:
        return
    news, _ = parse(state.get("cache", {}).get("events", []))
    now = clock()
    pending = {t: g for t, g in group_by_time(news).items()
               if timedelta(minutes=-2) <= t - now <= timedelta(minutes=12)
               and f"res:{t.isoformat()}" not in state["sent"]}
    if not pending:
        return
    deadline = max(pending) + timedelta(minutes=13)
    tries = {t: 0 for t in pending}
    while pending and clock() < deadline:
        now = clock()
        for m in run(now, state):                 # påmindelser kører videre imens
            post(m)
        last = state.get("jb_last")
        can_call = not last or (now - datetime.fromisoformat(last)).total_seconds() >= JB_MIN_GAP
        due = [t for t in pending if now >= t + timedelta(seconds=60)]
        if due and can_call:
            rows = fetch_actuals(state, now)
            for t in due:
                g = pending[t]
                tries[t] += 1
                acts = {id(n): match_actual(n, rows) for n in g}
                acts = {k: v for k, v in acts.items() if v is not None}
                if len(acts) == len(g) or (acts and tries[t] >= RESULT_TRIES):
                    post(f"📊 **{curs(g)} news kl. {hm(t)} – resultater**\n" + verdict(g, acts) +
                         "\n\n⚠️ Første spike kan gå begge veje – vent til kl. "
                         f"{hm(t + timedelta(minutes=NO_TRADE_AFTER))} og tjek strukturen.")
                    state["sent"][f"res:{t.isoformat()}"] = now.isoformat()
                    del pending[t]
                elif tries[t] >= RESULT_TRIES:
                    state["sent"][f"res:{t.isoformat()}"] = now.isoformat()
                    del pending[t]
        sleep(20)
    save_state(state)


def main():
    if os.environ.get("NOW"):
        _sim["t"] = now_utc()
    now = clock()
    state = load_state()
    if os.environ.get("TEST_MESSAGE", "").lower() == "true":
        news, holidays = parse(fetch_events(state, now))
        post("🧪 **Test fra Dadash News Bot** – botten virker!\n\n" + morning(now, news, holidays))
    for m in run(now, state):
        post(m)
    save_state(state)
    results_loop(state)


if __name__ == "__main__":
    main()
