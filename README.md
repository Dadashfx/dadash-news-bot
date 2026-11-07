# Dadash News Bot

Poster automatisk i Dadash Community på Discord (dansk tid, sommer- og vintertid klares automatisk):

- 📅 **Morgenoversigt** kl. 07:30 man–fre: dagens røde 🔴 og orange 🟠 news, "ingen trades"-vinduer, bank holidays og sessionstider
- ⚠️ **1 time før** news: "Ingen trades fra nu"
- ⏰ **15 min før** news: "Luk eller sæt på BE"
- ✅ **15 min efter** news: "News er ude" (+ advarsel hvis næste news er tæt på)
- 📊 **Resultater 1–6 min efter news**: actual vs. forventning, 🟢 bedre / 🔴 dårligere, "Stærkt/Svagt for USD" og forventet retning for USDCHF, USDJPY, AUDUSD, GBPUSD, AUDCHF, AUDJPY og guld
- 🔔 **Sessionsåbninger**: Asia 01:00, Frankfurt 08:00, London 09:00, NY 15:30

Alle valutaer med rød/orange impact. Dine valutaer (USD, AUD, CHF, JPY, GBP) får ⭐.
Data: ForexFactory-kalenderen (tider) + JBlanked News API (faktiske tal, gratis). Koster 0 kr. og kører i skyen, også når din PC er slukket.

### 📰 Nyhedsfeed (egen kanal)
Poster nye, markedsrelevante nyheder i en **separat kanal** (fx `#mellemøsten-news`):
- **Store medier:** Al Jazeera, BBC, Times of Israel, Jerusalem Post, Tehran Times, CNBC
- **Google News-søgninger**, der fanger **Reuters, AP, Bloomberg, CNN, NBC** osv. om Iran, Israel, Hormuz, olie, Fed, told og sanktioner
- **Politikeres udtalelser** (Araghchi, Khamenei, Pezeshkian, Ghalibaf, Larijani, Hegseth, Vance, Rubio …), sådan som medierne citerer dem
- **Alle Trumps opslag på Truth Social**
- **Telegram-kanaler**, fx WarRoom, **oversat til dansk** 🇩🇰 (link til originalen)
- 🚨 = haster (angreb, missiler, eksplosioner, Hormuz, atom). Sport og andet ikke-relevant filtreres fra. Dubletter fjernes.

⚠️ **X (Twitter) kan ikke læses gratis** (X kræver mindst $200/md). Derfor kommer politikeres X-opslag med, når nyhedsmedierne eller Telegram-kanalerne skriver om dem.

---

## Opsætning (ca. 10 min)

### 1. Lav et webhook i Discord
1. Højreklik på din server → **Serverindstillinger** → **Integrationer** → **Webhooks** → **Nyt webhook**.
2. Giv den navnet `Dadash News` og vælg kanalen (fx `#news`).
3. Tryk **Kopiér webhook-URL**. Gem den, du skal bruge den i trin 3.
   ⚠️ Del aldrig den URL med andre. Den giver adgang til at skrive i kanalen.

### 2. Læg botten på GitHub
1. Lav en gratis konto på **github.com**.
2. Tryk **+** øverst til højre → **New repository**.
   - Navn: `dadash-news-bot`
   - Vælg **Public** (så er det gratis at køre hvert 5. minut. Dit webhook er stadig hemmeligt.)
   - Tryk **Create repository**.
3. Tryk **uploading an existing file** og træk filerne ind: `bot.py`, `news_feed.py`, `state.json`, `feed_state.json`, `README.md`.
4. Workflow-filerne skal ligge i en mappe: tryk **Add file → Create new file**, skriv navnet
   `.github/workflows/news-bot.yml`, og indsæt indholdet af filen `news-bot.yml`. Tryk **Commit changes**.
   Gør det samme for `.github/workflows/news-feed.yml` med indholdet af `news-feed.yml`.

### 3. Gem webhook-URL'en som hemmelighed
1. I dit repo: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
2. Name: `DISCORD_WEBHOOK_URL`  ·  Secret: din URL fra trin 1. Tryk **Add secret**.

### 3a. Webhook til nyhedsfeedet
1. Lav en ny kanal i Discord, fx `#mellemøsten-news`, og lav et webhook til den (som i trin 1).
2. På GitHub: **New repository secret** → Name: `DISCORD_FEED_WEBHOOK_URL` · Secret: den nye URL.

### 3b. Gratis nøgle til de faktiske tal (JBlanked)
1. Lav en gratis konto på **jblanked.com** og gå til din profil: **jblanked.com/profile**. Kopiér din **API key**.
2. I dit GitHub-repo: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
3. Name: `JBLANKED_API_KEY`  ·  Secret: din nøgle. Tryk **Add secret**.
   Uden nøglen virker alt andet stadig, men der kommer ingen resultat-beskeder.

### 4. Giv botten lov til at gemme
**Settings** → **Actions** → **General** → under *Workflow permissions* vælg **Read and write permissions** → **Save**.

### 5. Test
1. Gå til fanen **Actions** → vælg **Dadash News Bot** → **Run workflow** (test = ✔) → **Run workflow**.
2. Efter ca. 30 sek. kommer der en testbesked i din Discord-kanal. ✅
3. Herefter kører den selv hvert 5. minut.
4. Kør også **Dadash Nyhedsfeed** én gang manuelt. Første gang poster den kun "Dadash Nyheder er startet" (så kanalen ikke bliver oversvømmet med gamle nyheder). Derefter kommer kun nye.

---

## Ændre indstillinger
**Nyhedsfeedet** (`news_feed.py`, øverst):
- `RSS`: tilføj/fjern medier (navn + RSS-link)
- `GNEWS`: søgninger i Google News
- `TELEGRAM = ["WarRoom"]`: tilføj flere offentlige Telegram-kanaler, fx `["WarRoom", "kanalnavn"]`
- `KEYWORDS`: ord en nyhed skal indeholde for at blive postet

**News-botten** (`bot.py`, øverst):
Øverst i `bot.py` (tryk på filen på GitHub → blyanten ✏️):
- `MY_CURRENCIES`: hvilke valutaer der får ⭐
- `CURRENCIES = None`: alle valutaer. Fx `{"USD","AUD","CHF","JPY","GBP"}` for kun dine.
- `MORNING_AT = (7, 30)`: tidspunkt for morgenoversigten
- `NO_TRADE_BEFORE` / `NO_TRADE_AFTER`: dit "ingen trades"-vindue (60 / 15 min)

## Godt at vide
- **Oversættelse af Telegram (farsi → dansk):** bruger Google Translate (gratis, ingen nøgle) og MyMemory som reserve. Det er maskinoversættelse, så navne og udtryk kan blive lidt skæve. Fejler begge, postes originalen med "(kunne ikke oversættes lige nu)". Valgfrit: tilføj din e-mail som secret `MYMEMORY_EMAIL` for en højere dagsgrænse hos MyMemory.
- **Resultaterne:** Den gratis JBlanked-nøgle må kun spørge én gang hvert 5. minut. Botten spørger ca. 1 min efter nyheden, og igen efter 6 og 11 min, hvis tallet ikke er kommet. Typisk kommer resultatet 1–6 min efter. Vil du have det på sekunder, kræver det en betalt datakilde.
- **Tolkningen er automatisk** (actual vs. forventning, vægtet efter hvor vigtigt tallet er). Den siger, hvad tallet *normalt* betyder, ikke hvad prisen *vil* gøre. Første spike kan altid gå begge veje.
- GitHub kan forsinke kørslerne nogle minutter. Påmindelserne har indbygget tolerance, så de kommer stadig, bare evt. 1–5 min senere.
- Ved ingen aktivitet i et public repo i 60 dage kan GitHub pause planlagte kørsler. Botten gemmer selv `state.json`, så det sker normalt ikke. Står den stille: **Actions** → **Enable workflow**.
