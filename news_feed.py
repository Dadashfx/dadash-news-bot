#!/usr/bin/env python3
"""
Dadash Nyhedsfeed – poster markedsrelevante nyheder i en egen Discord-kanal.

Kilder (gratis, ingen nøgler):
  • Store nyhedsmedier via RSS (Al Jazeera, BBC, Times of Israel, Tehran Times, CNBC ...)
  • Google News-søgninger (fanger Reuters, AP, Bloomberg, CNN, NBC ... og politikeres udtalelser)
  • Trumps Truth Social-opslag (via trumpstruth.org)
  • Offentlige Telegram-kanaler (fx WarRoom)

Køres hvert 5. minut. Husker i feed_state.json hvad der er postet.
"""
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DK = ZoneInfo("Europe/Copenhagen")
STATE_FILE = Path(__file__).with_name("feed_state.json")
MAX_AGE_H = 3            # ignorer nyheder ældre end 3 timer
MAX_POSTS_PER_RUN = 25   # bremse mod spam

# ------------------------------------------------------------------ kilder
RSS = [
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("BBC Mellemøsten", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Times of Israel", "https://www.timesofisrael.com/feed/"),
    ("Jerusalem Post", "https://www.jpost.com/rss/rssfeedsheadlines.aspx"),
    ("Tehran Times", "https://www.tehrantimes.com/rss"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
]

# Google News-søgninger (kun sidste 2 timer). Fanger Reuters/AP/Bloomberg/NBC osv.
GNEWS = [
    "(Iran OR Tehran OR Hormuz OR IRGC) when:2h",
    "(Israel OR Netanyahu OR Hezbollah OR Houthi) (strike OR attack OR missile OR ceasefire) when:2h",
    "(Araghchi OR Khamenei OR Pezeshkian OR Ghalibaf OR Larijani) when:2h",
    "Trump (Iran OR tariff OR sanctions OR Fed) when:2h",
    "(\"Federal Reserve\" OR Warsh OR \"rate hike\" OR \"rate cut\") when:2h",
    "(\"oil prices\" OR Brent OR OPEC OR tanker) when:2h",
    "(Hegseth OR Vance OR Rubio OR Pentagon) Iran when:2h",
]

TRUMP_FEED = "https://trumpstruth.org/feed"          # Trumps Truth Social-opslag
TELEGRAM = ["WarRoom"]                               # offentlige kanaler (t.me/s/<navn>)
TRANSLATE_TELEGRAM = True                            # oversæt Telegram-opslag til dansk
TARGET_LANG = "da"

# Kun nyheder med mindst ét af disse ord (Trump og Telegram poster alt)
KEYWORDS = [
    "iran", "tehran", "hormuz", "irgc", "khamenei", "araghchi", "pezeshkian", "ghalibaf", "larijani",
    "israel", "idf", "netanyahu", "hezbollah", "houthi", "gaza", "lebanon", "syria", "iraq", "yemen",
    "saudi", "qatar", "doha", "uae", "gulf", "jordan", "strike", "missile", "drone", "attack", "explosion",
    "ceasefire", "nuclear", "uranium", "sanction", "oil", "brent", "crude", "opec", "tanker", "lng",
    "federal reserve", " fed ", "warsh", "rate hike", "rate cut", "interest rate", "inflation", "cpi",
    "tariff", "pentagon", "hegseth", "carrier", "warship", "navy",
]
URGENT = ["strike", "attack", "missile", "explosion", "killed", "war ", "hormuz", "nuclear", "invasion",
          "breaking", "drone", "retaliat", "mine"]


# ------------------------------------------------------------------ hjælpere
def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (dadash-news-feed)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def clean(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>", "\n", s or "", flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


def when(s: str):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None


def key_of(title: str) -> str:
    t = re.sub(r"\s+[-–|]\s+[^-–|]{2,40}$", "", title.lower())   # fjern " - Reuters"
    return re.sub(r"[^a-z0-9؀-ۿ]", "", t)[:70]


def relevant(text: str) -> bool:
    t = f" {text.lower()} "
    return any(k in t for k in KEYWORDS)


def urgent(text: str) -> bool:
    t = f" {text.lower()} "
    return any(k in t for k in URGENT)


def pick(f: dict, *names) -> str:
    for n in names:
        if n in f and f[n] is not None and (f[n].text or "").strip():
            return f[n].text
    return ""


def parse_rss(xml_text: str, source: str):
    items = []
    root = ET.fromstring(xml_text)
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        f = {c.tag.split("}")[-1]: c for c in it}
        title = clean(f["title"].text if "title" in f else "")
        link = ""
        if "link" in f:
            link = (f["link"].text or f["link"].get("href") or "").strip()
        desc = clean(pick(f, "description", "summary", "content", "encoded"))
        dt = when(pick(f, "pubDate", "published", "updated", "date"))
        src = source
        if "source" in f and (f["source"].text or "").strip():
            src = f["source"].text.strip()                       # Google News: rigtig kilde
            title = re.sub(rf"\s+-\s+{re.escape(src)}$", "", title)
        items.append({"title": title, "link": link, "desc": desc, "dt": dt, "src": src})
    return items


def parse_telegram(page: str, channel: str):
    items = []
    for m in re.finditer(r'data-post="([^"]+)".*?(?=data-post="|$)', page, flags=re.S):
        block = m.group(0)
        txt = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, flags=re.S)
        tm = re.search(r'<time[^>]+datetime="([^"]+)"', block)
        if not txt:
            continue
        items.append({"title": "", "desc": clean(txt.group(1)), "link": f"https://t.me/{m.group(1)}",
                      "dt": when(tm.group(1)) if tm else None, "src": f"{channel} (Telegram)"})
    return items


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"seen": {}}


def short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


# ------------------------------------------------------------------ indsamling
def collect():
    """-> liste af (kind, item)"""
    out = []

    def fetch(name, url):
        try:
            if os.environ.get("FIXTURES"):                       # til test
                p = Path(os.environ["FIXTURES"]) / (re.sub(r"\W+", "_", name) + ".xml")
                return p.read_text() if p.exists() else None
            return get(url)
        except Exception as e:
            print(f"[{name}] fejl: {e}", file=sys.stderr)
            return None

    for name, url in RSS:
        x = fetch(name, url)
        if x:
            try:
                out += [("news", i) for i in parse_rss(x, name)]
            except ET.ParseError as e:
                print(f"[{name}] kunne ikke læses: {e}", file=sys.stderr)
    for q in GNEWS:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        x = fetch("gnews_" + q[:20], url)
        if x:
            try:
                out += [("news", i) for i in parse_rss(x, "Google News")]
            except ET.ParseError:
                pass
    x = fetch("trump", TRUMP_FEED)
    if x:
        try:
            out += [("trump", i) for i in parse_rss(x, "Trump (Truth Social)")]
        except ET.ParseError:
            pass
    for ch in TELEGRAM:
        x = fetch("tg_" + ch, f"https://t.me/s/{ch}")
        if x:
            out += [("telegram", i) for i in parse_telegram(x, ch)]
    return out


# ------------------------------------------------------------------ oversættelse
def _google(text: str, tl: str) -> str:
    """Google Translate (gratis web-endpoint, ingen nøgle)."""
    q = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": tl, "dt": "t", "q": text})
    data = json.loads(get("https://translate.googleapis.com/translate_a/single?" + q))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


def _mymemory(text: str, tl: str) -> str:
    """MyMemory (gratis API, max ca. 450 tegn pr. kald, derfor deles teksten)."""
    out, chunk = [], ""
    pieces = re.split(r"(?<=[.!?؟\n])", text)
    chunks = []
    for p in pieces:
        if len((chunk + p).encode()) > 480 and chunk:
            chunks.append(chunk)
            chunk = ""
        chunk += p
    if chunk:
        chunks.append(chunk)
    for c in chunks:
        params = {"q": c[:240] if len(c.encode()) > 500 else c, "langpair": f"fa|{tl}"}
        if os.environ.get("MYMEMORY_EMAIL"):
            params["de"] = os.environ["MYMEMORY_EMAIL"]     # højere dagsgrænse
        data = json.loads(get("https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(params)))
        t = (data.get("responseData") or {}).get("translatedText") or ""
        if not t or data.get("responseStatus") not in (200, "200"):
            raise RuntimeError(data.get("responseDetails") or "MyMemory fejl")
        out.append(t)
    return " ".join(out).strip()


def translate(text: str) -> str:
    """Prøver Google, derefter MyMemory. Returnerer '' hvis begge fejler."""
    if os.environ.get("TRANSLATE_MOCK"):                   # til test
        return "[DA] " + text
    for fn in (_google, _mymemory):
        try:
            t = fn(text, TARGET_LANG)
            if t:
                return html.unescape(t)
        except Exception as e:
            print(f"Oversættelse via {fn.__name__} fejlede: {e}", file=sys.stderr)
    return ""


def fmt(kind, i) -> str:
    t = i["dt"].astimezone(DK).strftime("%H:%M") if i["dt"] else ""
    link = f"<{i['link']}>" if i["link"] else ""
    if kind == "trump":
        body = i["desc"] or i["title"]
        return f"🇺🇸 **Trump (Truth Social)** · {t}\n{short(body, 900)}\n{link}"
    if kind == "telegram":
        body = short(i["desc"], 900)
        if TRANSLATE_TELEGRAM:
            da = translate(body)
            body = f"🇩🇰 {short(da, 1200)}" if da else f"{body}\n*(kunne ikke oversættes lige nu)*"
        return f"📢 **{i['src']}** · {t}\n{body}\n{link}"
    flag = "🚨" if urgent(i["title"]) else "📰"
    return f"{flag} **{i['src']}** · {t}\n**{i['title']}**\n{link}"


def post(text: str):
    url = os.environ.get("DISCORD_FEED_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")
    if not url or os.environ.get("DRY_RUN"):
        print("---- (ikke sendt) ----\n" + text + "\n")
        return
    body = json.dumps({"content": text[:1990], "username": "Dadash Nyheder",
                       "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "dadash-news-feed"})
    urllib.request.urlopen(req, timeout=20).read()


def main():
    now = datetime.now(timezone.utc)
    if os.environ.get("NOW"):
        now = datetime.fromisoformat(os.environ["NOW"]).astimezone(timezone.utc)
    state = load_state()
    seen = state.setdefault("seen", {})
    first_run = not seen
    fresh = []
    for kind, i in collect():
        k = key_of(i["title"] or i["desc"][:120]) or i["link"]
        if not k or k in seen or i["link"] in seen:
            continue
        if i["dt"] and now - i["dt"] > timedelta(hours=MAX_AGE_H):
            continue
        if kind == "news" and not relevant(f"{i['title']} {i['desc']}"):
            continue
        seen[k] = now.isoformat()
        if i["link"]:
            seen[i["link"]] = now.isoformat()
        fresh.append((kind, i))

    if first_run:   # første gang: gem alt som "set", så kanalen ikke bliver oversvømmet
        print(f"Første kørsel: {len(fresh)} nyheder markeret som set, intet postet.")
        if fresh:
            post(f"✅ **Dadash Nyheder er startet.** Fra nu poster jeg nye markedsrelevante nyheder, "
                 f"Trumps opslag og {', '.join(TELEGRAM)} her.")
    else:
        fresh.sort(key=lambda x: x[1]["dt"] or now)
        # Trump og 🚨 først, hvis der er mange
        if len(fresh) > MAX_POSTS_PER_RUN:
            fresh.sort(key=lambda x: (x[0] != "trump", not urgent(x[1]["title"] or x[1]["desc"])))
            fresh = sorted(fresh[:MAX_POSTS_PER_RUN], key=lambda x: x[1]["dt"] or now)
        for kind, i in fresh:
            try:
                post(fmt(kind, i))
            except Exception as e:
                print(f"Discord-fejl: {e}", file=sys.stderr)

    cutoff = now - timedelta(days=3)
    state["seen"] = {k: v for k, v in seen.items() if datetime.fromisoformat(v) > cutoff}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
