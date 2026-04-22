import requests
import time
import os
import json
import re
import base64
from statistics import median

# ─────────────────────────────────────────
#  🔑 USTAWIENIA — Railway Variables
#  Dodaj w Railway:
#    TOKEN          = token z BotFather
#    CHAT_ID        = Twój chat id
#    ANTHROPIC_KEY  = klucz z console.anthropic.com
# ─────────────────────────────────────────
TOKEN         = os.getenv("TOKEN")
CHAT_ID       = os.getenv("CHAT_ID")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
}

# ─────────────────────────────────────────
#  ⚙️ PROGI OKAZJI
# ─────────────────────────────────────────
MIN_DISCOUNT_PCT = 40      # % poniżej mediany → okazja
MIN_AI_CONFIDENCE = 60     # % pewności AI że to ukryta okazja

STEAL_PRICES = {
    "sneakers": 120,
    "clothing":  30,
    "lego":      60,
    "funko":     25,
    "football":  50,
    "lego_sw":   80,
    "carhartt": 250,
}

# ─────────────────────────────────────────
#  🧥 CARHARTT — konfiguracja modeli
# ─────────────────────────────────────────

# Modele z niższym progiem (Trucker cap/hat)
CARHARTT_TRUCKER_MODELS = [
    "trucker", "trucker cap", "trucker hat", "czapka trucker",
]
CARHARTT_TRUCKER_MAX = 150   # alert gdy cena ≤ 150 zł

# Modele z wyższym progiem (kurtki)
CARHARTT_PREMIUM_MODELS = [
    "santa fe", "detroit", "active jacket",
    "kurtka santa fe", "kurtka detroit", "kurtka active",
]
CARHARTT_PREMIUM_MAX = 250   # alert gdy cena ≤ 250 zł

# ─────────────────────────────────────────
#  🧱 LEGO STAR WARS — konfiguracja
# ─────────────────────────────────────────

# Numery kultowych setów Star Wars (wartościowe)
SW_SET_NUMBERS = [
    # UCS / Ultimate Collector Series
    "75192", "75309", "75313", "75252", "75274", "75144",
    "10179", "10221", "10240", "10143",
    # Popularne zestawy
    "75257", "75243", "75218", "75212", "75179",
    "75190", "75189", "75188", "75187", "75186",
    "75159", "75098", "75060", "75059",
    "75153", "75154", "75155", "75156",
    "75105", "75103", "75104", "75102", "75101", "75100",
    "75082", "75083", "75084", "75085", "75086",
    # Klasyki
    "7965", "7964", "7962", "7961", "7959",
    "9516", "9515", "9514", "9512", "9511",
    "4504", "4480", "4481", "4482", "4483", "4484",
    "6211", "6212",
    # Mandalorian / nowe popularne
    "75292", "75299", "75316", "75317", "75318",
    "75319", "75320", "75321", "75325", "75326",
]

# Pojazdy i miejsca — szukamy tych nazw w tytule
SW_VEHICLES = [
    "millennium falcon", "millenium falcon", "sokół milenium",
    "x-wing", "xwing", "x wing",
    "tie fighter", "tie-fighter",
    "death star", "gwiazda śmierci", "gwiazda smierci",
    "star destroyer", "niszczyciel gwiezdny",
    "at-at", "atat", "at at",
    "at-st", "atst",
    "slave i", "slave 1",
    "y-wing", "ywing",
    "a-wing", "awing",
    "republic gunship", "venator",
    "razor crest",
    "naboo", "podracer", "pod racer",
    "imperial shuttle", "prom imperialny",
    "b-wing", "bwing",
    "sandcrawler", "sand crawler",
    "cloud city",
    "jabba", "sarlacc",
    "ewok village", "wioska ewoków",
]

# Postacie których szukamy
SW_CHARACTERS = [
    "darth vader", "vader",
    "yoda", "master yoda",
    "luke skywalker", "luke",
    "han solo",
    "darth maul",
    "obi-wan", "obi wan", "kenobi",
    "mandalorian", "mando", "din djarin",
    "grogu", "baby yoda",
    "boba fett",
    "stormtrooper", "szturmowiec",
    "clone trooper", "klony",
    "jango fett",
    "emperor palpatine", "palpatine", "sidious",
    "kylo ren",
    "rey",
    "r2-d2", "r2d2",
    "c-3po", "c3po",
    "chewbacca", "chewie",
    "leia", "princess leia",
    "anakin skywalker", "anakin",
    "count dooku",
    "grievous", "general grievous",
    "ahsoka",
    "mace windu",
]

# Słowa które MUSZĄ być w ofercie żeby uznać ją za kompletną
SW_COMPLETE_KEYWORDS = [
    "kompletny", "komplet", "complete", "wszystkie części",
    "z figurkami", "z minifigurkami", "minifigurki w zestawie",
    "pudełko", "instrukcja", "100%", "idealny stan",
    "używany", "używane", "second hand",   # używane są OK
]

# Słowa które dyskwalifikują ofertę (niekompletna)
SW_INCOMPLETE_KEYWORDS = [
    "niekompletny", "brakuje", "bez figurek", "bez minifigurek",
    "niepełny", "części", "uszkodzony", "incomplete",
    "only parts", "spare parts", "zamienię",
]

# ─────────────────────────────────────────
#  ⚽ KOSZULKI RETRO — konfiguracja
# ─────────────────────────────────────────

# Lata które uznajemy za "retro"
RETRO_DECADES = ["70", "80", "90", "1970", "1980", "1990",
                 "1991", "1992", "1993", "1994", "1995",
                 "1996", "1997", "1998", "1999", "2000",
                 "2001", "2002", "2003", "vintage", "retro",
                 "stara", "klasyk", "klasyczna", "kolekcjonerska"]

# Marki oryginałów (repliki odrzucamy)
FOOTBALL_ORIGINAL_BRANDS = [
    "adidas", "nike", "umbro", "lotto", "kappa", "puma",
    "reebok", "diadora", "le coq sportif", "hummel",
    "errea", "patrick", "uhlsport",
]

# Słowa sugerujące replikę → odrzucamy
REPLICA_KEYWORDS = [
    "replika", "replica", "kopia", "podróbka", "nieoryginalna",
    "chiński", "chińska", "fakes", "fake", "inspired",
]

# Kluby i reprezentacje których szukamy
FOOTBALL_CLUBS = [
    # Serie A
    "ac milan", "milan", "inter milan", "inter", "juventus", "juve",
    "as roma", "roma", "napoli", "lazio", "fiorentina", "parma",
    # La Liga
    "real madryt", "real madrid", "barcelona", "barca", "atletico",
    "sevilla", "valencia", "deportivo",
    # Premier League
    "manchester united", "man utd", "liverpool", "arsenal",
    "chelsea", "tottenham", "spurs", "newcastle", "leeds",
    "aston villa", "everton", "blackburn",
    # Bundesliga
    "borussia", "dortmund", "bvb", "bayern", "schalke",
    # Francja
    "paris saint germain", "psg", "marseille", "om",
    # Polska
    "legia", "lech", "wisla", "wisła", "górnik", "gornik",
    # Reprezentacje
    "polska", "poland", "niemcy", "niemiec", "germany",
    "włochy", "wlochy", "italia", "italy",
    "francja", "france", "brazylia", "brazil", "brasil",
    "argentyna", "argentina", "anglia", "england",
    "hiszpania", "spain", "holandia", "netherlands",
    "portugalia", "portugal", "chorwacja", "croatia",
]

# ─────────────────────────────────────────
#  🔤 SŁOWNIK BŁĘDNYCH PISOWNI
#  bot szuka tych słów i rozpoznaje markę
# ─────────────────────────────────────────
BRAND_TYPOS = {
    "nike":         ["niike", "nikee", "nik3", "n1ke", "nke", "nike'"],
    "adidas":       ["addidas", "adidass", "adidaas", "adi das", "adidasi"],
    "supreme":      ["suprime", "supream", "supreem", "supremme", "supr3me"],
    "jordan":       ["jordon", "jordann", "joradan", "ajordan", "jodan"],
    "yeezy":        ["yezi", "yezy", "yeeezi", "yeezi", "ye3zy"],
    "off-white":    ["offwhite", "off white", "of white", "offwite"],
    "stone island": ["stone isl", "stoneisland", "stone ilsand"],
    "lego":         ["leg0", "leg o", "legi", "lego's"],
    "funko":        ["funk0", "funco", "funko's", "funkopop"],
    "balenciaga":   ["balenciag", "balenciga", "balenciaga's", "balanciaga"],
    "gucci":        ["guci", "guchi", "gucci's"],
    "louis vuitton":["louis viton", "luis vuitton", "louiss vuitton", "lv"],
    "carhartt":     ["carhatt", "carhart", "carhарт", "cahartt", "carharrt", "charhartt"],
}

# ─────────────────────────────────────────
#  🔍 WYSZUKIWANIA
# ─────────────────────────────────────────
SEARCHES = [
    {
        "name":     "Nike Dunk / Air Force",
        "url":      "https://www.vinted.pl/catalog?catalog[]=1206&brand_ids[]=14&brand_ids[]=362&order=newest_first&currency=PLN",
        "category": "sneakers",
        "keywords": ["dunk", "air force", "jordan", "nike"],
        "brands":   ["nike", "jordan", "air force"],
        "min_price": 30,
    },
    {
        "name":     "Adidas Yeezy / Samba",
        "url":      "https://www.vinted.pl/catalog?catalog[]=1206&brand_ids[]=7&order=newest_first&currency=PLN",
        "category": "sneakers",
        "keywords": ["yeezy", "samba", "gazelle", "stan smith"],
        "brands":   ["adidas", "yeezy"],
        "min_price": 30,
    },
    {
        "name":     "Supreme / Off-White",
        "url":      "https://www.vinted.pl/catalog?catalog[]=4&brand_ids[]=2161&brand_ids[]=3946&order=newest_first&currency=PLN",
        "category": "clothing",
        "keywords": ["supreme", "off-white", "hoodie", "tee"],
        "brands":   ["supreme", "off-white"],
        "min_price": 20,
    },
    {
        "name":     "Stone Island / CP Company",
        "url":      "https://www.vinted.pl/catalog?catalog[]=4&brand_ids[]=2163&brand_ids[]=2305&order=newest_first&currency=PLN",
        "category": "clothing",
        "keywords": ["stone island", "cp company", "kurtka", "bluza"],
        "brands":   ["stone island", "cp company"],
        "min_price": 40,
    },
    {
        "name":     "LEGO Star Wars — wszystkie zestawy",
        "url":      "https://www.vinted.pl/catalog?search_text=lego+star+wars&order=newest_first&currency=PLN&price_to=100",
        "category": "lego_sw",
        "keywords": ["lego", "star wars"],
        "min_price": 15,
        "lego_sw_mode": True,
    },
    {
        "name":     "LEGO Star Wars — numery setów",
        "url":      "https://www.vinted.pl/catalog?search_text=lego+75&order=newest_first&currency=PLN&price_to=100",
        "category": "lego_sw",
        "keywords": ["lego", "75"],
        "min_price": 15,
        "lego_sw_mode": True,
    },
    {
        "name":     "LEGO Star Wars — pojazdy",
        "url":      "https://www.vinted.pl/catalog?search_text=lego+x-wing+falcon+death+star&order=newest_first&currency=PLN&price_to=100",
        "category": "lego_sw",
        "keywords": ["lego"],
        "min_price": 15,
        "lego_sw_mode": True,
    },
    {
        "name":     "LEGO zestawy (ogólne)",
        "url":      "https://www.vinted.pl/catalog?search_text=lego&order=newest_first&currency=PLN",
        "category": "lego",
        "keywords": ["lego", "technic", "city", "ninjago", "harry potter", "creator"],
        "brands":   ["lego"],
        "min_price": 20,
    },
    {
        "name":     "Funko Pop",
        "url":      "https://www.vinted.pl/catalog?search_text=funko+pop&order=newest_first&currency=PLN",
        "category": "funko",
        "keywords": ["funko", "pop", "vinyl", "figurka"],
        "brands":   ["funko"],
        "min_price": 10,
    },
    # ── KOSZULKI PIŁKARSKIE RETRO ────────────
    {
        "name":     "Koszulki retro — kluby (Serie A / La Liga / PL)",
        "url":      "https://www.vinted.pl/catalog?search_text=koszulka+pilkarska+vintage&catalog[]=4&order=newest_first&currency=PLN&price_to=150",
        "category": "football",
        "keywords": ["koszulka", "jersey", "shirt"],
        "brands":   FOOTBALL_ORIGINAL_BRANDS,
        "min_price": 20,
        "football_mode": True,
    },
    {
        "name":     "Koszulki retro — reprezentacje",
        "url":      "https://www.vinted.pl/catalog?search_text=koszulka+reprezentacja+retro&catalog[]=4&order=newest_first&currency=PLN&price_to=150",
        "category": "football",
        "keywords": ["reprezentacja", "national", "koszulka"],
        "brands":   FOOTBALL_ORIGINAL_BRANDS,
        "min_price": 20,
        "football_mode": True,
    },
    {
        "name":     "Umbro / Lotto / Kappa retro",
        "url":      "https://www.vinted.pl/catalog?search_text=umbro+koszulka+pilkarska&catalog[]=4&order=newest_first&currency=PLN&price_to=150",
        "category": "football",
        "keywords": ["umbro", "lotto", "kappa", "koszulka"],
        "brands":   FOOTBALL_ORIGINAL_BRANDS,
        "min_price": 15,
        "football_mode": True,
    },
    # ── CARHARTT ─────────────────────────────
    {
        "name":     "Carhartt Trucker",
        "url":      "https://www.vinted.pl/catalog?search_text=carhartt+trucker&catalog[]=4&order=newest_first&currency=PLN&price_to=150",
        "category": "carhartt",
        "keywords": ["carhartt", "trucker"],
        "brands":   ["carhartt"],
        "min_price": 20,
        "carhartt_mode": True,
        "carhartt_models": CARHARTT_TRUCKER_MODELS,
        "carhartt_max_price": CARHARTT_TRUCKER_MAX,
    },
    {
        "name":     "Carhartt Santa Fe / Detroit / Active",
        "url":      "https://www.vinted.pl/catalog?search_text=carhartt+kurtka&catalog[]=4&order=newest_first&currency=PLN&price_to=250",
        "category": "carhartt",
        "keywords": ["carhartt"],
        "brands":   ["carhartt"],
        "min_price": 50,
        "carhartt_mode": True,
        "carhartt_models": CARHARTT_PREMIUM_MODELS,
        "carhartt_max_price": CARHARTT_PREMIUM_MAX,
    },
    # ── HIDDEN GEM — brak marki, niska cena ──
    {
        "name":     "Buty bez marki (hidden gem)",
        "url":      "https://www.vinted.pl/catalog?catalog[]=1206&order=newest_first&currency=PLN&price_to=80",
        "category": "sneakers",
        "keywords": [],        # celowo puste — bierzemy wszystko
        "brands":   [],
        "min_price": 10,
        "hidden_gem_mode": True,   # tryb AI scan
    },
    {
        "name":     "Ubrania bez marki (hidden gem)",
        "url":      "https://www.vinted.pl/catalog?catalog[]=4&order=newest_first&currency=PLN&price_to=30",
        "category": "clothing",
        "keywords": [],
        "brands":   [],
        "min_price": 5,
        "hidden_gem_mode": True,
    },
]

# ─────────────────────────────────────────
#  💾 PAMIĘĆ  (z automatycznym czyszczeniem)
# ─────────────────────────────────────────
SEEN_FILE      = "seen_items.json"
SEEN_MAX_DAYS  = 30   # po ilu dniach zapominamy ID

def load_seen():
    """
    Zwraca dict {item_id: timestamp_float}.
    Przy ładowaniu od razu usuwa wpisy starsze niż SEEN_MAX_DAYS.
    Obsługuje też stary format (lista stringów) — migruje automatycznie.
    """
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r") as f:
            data = json.load(f)

        now = time.time()
        cutoff = now - SEEN_MAX_DAYS * 86400

        # Migracja starego formatu (lista) → nowy (dict z timestampem)
        if isinstance(data, list):
            print(f"💾 Migruję seen_items: {len(data)} wpisów → format z datą")
            return {item_id: now for item_id in data}

        # Usuń stare wpisy
        fresh = {k: v for k, v in data.items() if v > cutoff}
        removed = len(data) - len(fresh)
        if removed:
            print(f"💾 Wyczyszczono {removed} starych wpisów z seen_items")
        return fresh

    except Exception as e:
        print(f"Błąd load_seen: {e} — zaczynam od pustego")
        return {}

def save_seen(seen):
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(seen, f)
    except Exception as e:
        print(f"Błąd save_seen: {e}")

# ─────────────────────────────────────────
#  📤 TELEGRAM
# ─────────────────────────────────────────
def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={
            "chat_id":                  CHAT_ID,
            "text":                     text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": False,
        }, timeout=10)
        if r.status_code != 200:
            print(f"Telegram error: {r.text}")
    except Exception as e:
        print(f"Błąd wysyłania: {e}")

# ─────────────────────────────────────────
#  💰 WYCIĄGANIE CENY
# ─────────────────────────────────────────
def extract_price(text):
    nums = re.findall(r"\d+[\.,]?\d*", text.replace("\xa0", "").replace(" ", ""))
    prices = []
    for n in nums:
        try:
            val = float(n.replace(",", "."))
            if 1 < val < 99999:
                prices.append(val)
        except:
            pass
    return prices[0] if prices else None

# ─────────────────────────────────────────
#  🔤 DETEKCJA BŁĘDNEJ PISOWNI MARKI
# ─────────────────────────────────────────
def detect_typo_brand(text):
    """
    Zwraca (prawdziwa_marka, znaleziony_typo) jeśli
    wykryto błędną pisownię, inaczej (None, None)
    """
    text_lower = text.lower()
    for brand, typos in BRAND_TYPOS.items():
        for typo in typos:
            if typo in text_lower:
                return brand, typo
    return None, None

# ─────────────────────────────────────────
#  🤖 AI — ANALIZA ZDJĘCIA + TEKSTU
#  Wysyła zdjęcie i opis do Claude Vision
#  i pyta: czy to ukryta okazja?
# ─────────────────────────────────────────
def analyze_with_ai(title, description, image_url):
    """
    Zwraca dict:
      {
        "is_hidden_gem": bool,
        "confidence":    int (0-100),
        "detected_brand": str lub None,
        "reason":         str,
        "mismatch":       bool  (zdjęcie ≠ opis)
      }
    """
    if not ANTHROPIC_KEY:
        return None

    # Pobierz zdjęcie i zakoduj do base64
    image_data = None
    image_type = "image/jpeg"
    if image_url:
        try:
            img_r = requests.get(image_url, timeout=10, headers=HEADERS)
            if img_r.status_code == 200:
                image_data = base64.standard_b64encode(img_r.content).decode("utf-8")
                ct = img_r.headers.get("content-type", "image/jpeg")
                image_type = ct.split(";")[0].strip()
        except:
            pass

    # Zbuduj prompt
    prompt = f"""Jesteś ekspertem od sneakersów, ubrań streetwear, LEGO i Funko Pop.
Przeanalizuj tę ofertę z Vinted i odpowiedz TYLKO w JSON.

Tytuł oferty: {title[:200]}
Opis: {description[:300] if description else 'brak'}

Odpowiedz w formacie JSON (bez żadnego innego tekstu):
{{
  "is_hidden_gem": true/false,
  "confidence": 0-100,
  "detected_brand": "nazwa marki lub null",
  "reason": "krótkie wyjaśnienie po polsku",
  "mismatch": true/false
}}

Kiedy is_hidden_gem = true:
- zdjęcie pokazuje markową rzecz ale tytuł jej nie wymienia
- tytuł ma błędną pisownię marki
- cena jest bardzo niska jak na daną markę
- tytuł jest ogólnikowy ale na zdjęciu widać logo premium marki
- mismatch = true gdy zdjęcie NIE pasuje do opisu tekstowego"""

    # Zbuduj wiadomość do API
    content = []
    if image_data:
        content.append({
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": image_type,
                "data":       image_data,
            }
        })
    content.append({"type": "text", "text": prompt})

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-opus-4-5",
                "max_tokens": 300,
                "messages":   [{"role": "user", "content": content}],
            },
            timeout=20,
        )

        if r.status_code != 200:
            print(f"AI error: {r.text[:200]}")
            return None

        raw = r.json()["content"][0]["text"].strip()
        # Wyczyść ewentualne backticki
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)

    except Exception as e:
        print(f"AI parse error: {e}")
        return None

# ─────────────────────────────────────────
#  🌐 POBIERANIE Z VINTED  (HTML scraping)
# ─────────────────────────────────────────
import random
from bs4 import BeautifulSoup

# Rotacja User-Agentów — zmniejsza ryzyko blokady
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

VINTED_MIN_DELAY = 2.0
VINTED_MAX_DELAY = 4.0
VINTED_429_WAIT  = 180

def get_headers():
    """Zwraca losowy zestaw nagłówków naśladujący przeglądarkę."""
    return {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT":             "1",
        "Connection":      "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":  "document",
        "Sec-Fetch-Mode":  "navigate",
        "Sec-Fetch-Site":  "none",
        "Cache-Control":   "max-age=0",
    }

def vinted_fetch(url, label=""):
    """
    Pobiera stronę Vinted (HTML).
    Zwraca obiekt requests.Response lub None.
    Obsługuje 429 z retry i losowy jitter.
    """
    for attempt in range(1, 4):
        try:
            time.sleep(random.uniform(VINTED_MIN_DELAY, VINTED_MAX_DELAY))
            r = requests.get(url, headers=get_headers(), timeout=10)

            if r.status_code == 200:
                return r

            if r.status_code == 429:
                wait = VINTED_429_WAIT * attempt
                print(f"  🚫 429 [{label}] — czekam {wait}s (próba {attempt})")
                time.sleep(wait)
                continue

            if r.status_code in (403, 401):
                print(f"  ⚠️ HTTP {r.status_code} [{label}] — próba {attempt}/3")
                time.sleep(5 * attempt)
                continue

            print(f"  ⚠️ HTTP {r.status_code} [{label}]")
            return None

        except Exception as e:
            print(f"  ⚠️ Request error [{label}]: {e}")
            time.sleep(10)

    return None

def refresh_session():
    """Stub dla kompatybilności — nie potrzebujemy już sesji API."""
    print("✅ Sesja Vinted odświeżona")

def parse_items_from_html(html):
    """
    Wyciąga linki do ofert z HTML strony katalogu Vinted.
    Zwraca listę dictów: {id, title, price, url}
    """
    soup  = BeautifulSoup(html, "html.parser")
    items = []
    seen_ids = set()

    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if "/items/" not in href:
            continue

        if not href.startswith("http"):
            href = "https://www.vinted.pl" + href

        # wyciągnij ID
        try:
            item_id = href.split("/items/")[1].split("-")[0].split("?")[0]
            if not item_id.isdigit():
                continue
        except:
            continue

        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        title = tag.get_text(" ", strip=True)
        price = extract_price(title)

        items.append({
            "id":    item_id,
            "title": title,
            "price": price,
            "url":   href,
        })

    return items


# ─────────────────────────────────────────
#  🖼️ POBIERANIE SZCZEGÓŁÓW OFERTY (HTML)
# ─────────────────────────────────────────
def get_item_details(item_url):
    """Zwraca (image_url, description) ze strony HTML oferty."""
    try:
        r = vinted_fetch(item_url, label="item_details")
        if not r:
            return None, None

        soup = BeautifulSoup(r.text, "html.parser")

        og_img    = soup.find("meta", property="og:image")
        image_url = og_img["content"] if og_img else None

        desc_tag    = soup.find("meta", attrs={"name": "description"})
        description = desc_tag["content"] if desc_tag else ""

        return image_url, description

    except Exception as e:
        print(f"Błąd get_item_details: {e}")
        return None, None

# ─────────────────────────────────────────
#  📊 MEDIANA RYNKOWA (HTML scraping)
# ─────────────────────────────────────────
def get_market_median(search):
    try:
        r = vinted_fetch(search["url"], label=search["name"])
        if not r:
            return None

        items  = parse_items_from_html(r.text)
        prices = [
            it["price"] for it in items
            if it["price"] and it["price"] > search.get("min_price", 1)
        ]

        if len(prices) >= 3:
            med = median(prices)
            print(f"  📊 Mediana [{search['name']}]: {med:.0f} zł ({len(prices)} ofert)")
            return med

    except Exception as e:
        print(f"Błąd mediany [{search['name']}]: {e}")
    return None

# ─────────────────────────────────────────
#  🧱 WALIDACJA LEGO STAR WARS
# ─────────────────────────────────────────
def validate_lego_sw(title, description, ai_result):
    """
    Zwraca (is_valid, score, reasons, set_info)
    score = 0-100 (im wyższy tym lepsza oferta)
    """
    text = (title + " " + (description or "")).lower()
    reasons = []
    score   = 0

    # 1. Dyskwalifikacja — niekompletny
    for kw in SW_INCOMPLETE_KEYWORDS:
        if kw in text:
            return False, 0, [f"⛔ niekompletny zestaw ({kw})"], {}

    # 2. Wykryj numer setu
    found_set = None
    for num in SW_SET_NUMBERS:
        if num in text:
            found_set = num
            score    += 40
            reasons.append(f"✅ kultowy set #{num}")
            break

    # Szukaj też dowolnego numeru 75xxx (nowsze sety SW)
    if not found_set:
        sw_num = re.search(r"75\d{3}", text)
        if sw_num:
            found_set = sw_num.group()
            score    += 25
            reasons.append(f"✅ numer setu SW: #{found_set}")

    # 3. Wykryj pojazd / miejsce
    found_vehicle = None
    for vehicle in SW_VEHICLES:
        if vehicle in text:
            found_vehicle = vehicle
            score        += 20
            reasons.append(f"✅ pojazd: {vehicle}")
            break

    # 4. Wykryj postać
    found_char = None
    for char in SW_CHARACTERS:
        if char in text:
            found_char = char
            score     += 15
            reasons.append(f"✅ postać: {char}")
            break

    # 5. Kompletność
    is_complete = any(kw in text for kw in SW_COMPLETE_KEYWORDS)
    if is_complete:
        score   += 20
        reasons.append("✅ opis sugeruje kompletny zestaw")
    else:
        # Brak słowa "kompletny" nie dyskwalifikuje, ale obniża score
        score -= 10

    # 6. Minifigurki w opisie
    has_minifigs = any(w in text for w in ["minifigur", "figurk", "figure", "minifig"])
    if has_minifigs:
        score   += 15
        reasons.append("✅ minifigurki wspomniane")

    # 7. AI potwierdzenie
    if ai_result:
        if ai_result.get("is_hidden_gem") or "star wars" in ai_result.get("reason", "").lower():
            score   += 15
            reasons.append("🤖 AI potwierdza: Star Wars LEGO")

    # Wymagamy: Star Wars w tekście + cokolwiek rozpoznane
    has_sw = "star wars" in text or "starwars" in text or "gwiezdne wojny" in text
    has_anything = found_set or found_vehicle or found_char

    if not has_sw and not has_anything:
        return False, 0, ["⛔ brak oznak Star Wars"], {}

    set_info = {
        "set_number": found_set,
        "vehicle":    found_vehicle,
        "character":  found_char,
        "complete":   is_complete,
        "minifigs":   has_minifigs,
    }

    # Minimalne score żeby wysłać alert
    is_valid = score >= 25
    return is_valid, score, reasons, set_info


# ─────────────────────────────────────────
#  ⚽ WALIDACJA KOSZULKI RETRO
# ─────────────────────────────────────────
def validate_football_jersey(title, description, ai_result):
    """
    Zwraca (is_valid, reasons) gdzie:
      is_valid = True jeśli koszulka spełnia kryteria retro + oryginał
      reasons  = lista powodów
    """
    text = (title + " " + (description or "")).lower()
    reasons = []

    # 1. Odrzuć repliki od razu
    for rep in REPLICA_KEYWORDS:
        if rep in text:
            return False, [f"replika/kopia — odrzucono ({rep})"]

    # 2. Sprawdź czy zawiera słowo sugerujące retro/vintage/rok
    is_retro = any(decade in text for decade in RETRO_DECADES)

    # 3. Sprawdź markę oryginału
    has_original_brand = any(brand in text for brand in FOOTBALL_ORIGINAL_BRANDS)

    # 4. Sprawdź klub lub reprezentację
    has_club = any(club in text for club in FOOTBALL_CLUBS)

    # 5. Weź pod uwagę wynik AI
    ai_confirms_retro = False
    ai_confirms_original = False
    if ai_result:
        ai_reason = ai_result.get("reason", "").lower()
        if any(w in ai_reason for w in ["retro", "vintage", "oryginał", "oryginal", "lata "]):
            ai_confirms_retro = True
        if ai_result.get("detected_brand") in FOOTBALL_ORIGINAL_BRANDS:
            ai_confirms_original = True

    # Zbierz powody
    if is_retro:
        reasons.append("✅ vintage/retro w opisie")
    if has_original_brand:
        reasons.append("✅ oryginalna marka")
    if has_club:
        reasons.append("✅ rozpoznany klub/reprezentacja")
    if ai_confirms_retro:
        reasons.append("🤖 AI potwierdza: retro")
    if ai_confirms_original:
        reasons.append(f"🤖 AI marka: {ai_result.get('detected_brand')}")

    # Warunek: retro (tekst LUB AI) + marka oryginału (tekst LUB AI)
    retro_ok    = is_retro or ai_confirms_retro
    original_ok = has_original_brand or ai_confirms_original

    if retro_ok and original_ok:
        return True, reasons
    elif retro_ok and not original_ok:
        return False, ["⚠️ brak oryginałowej marki w opisie"]
    elif not retro_ok and original_ok:
        # Jeśli jest oryginalna marka i klub — może być retro bez słowa "retro"
        if has_club:
            return True, reasons + ["ℹ️ brak słowa retro, ale marka+klub sugerują vintage"]
        return False, ["⚠️ brak oznaczenia retro/vintage/roku"]
    else:
        return False, ["⚠️ nie spełnia kryteriów retro + oryginał"]


# ─────────────────────────────────────────
#  🧥 WALIDACJA CARHARTT
# ─────────────────────────────────────────
def validate_carhartt(title, description, search):
    """
    Zwraca (is_valid, reasons)
    Sprawdza czy oferta zawiera właściwy model i mieści się w progu cenowym.
    """
    text = (title + " " + (description or "")).lower()
    reasons = []

    # Musi być marka Carhartt
    if "carhartt" not in text:
        return False, ["⛔ brak słowa 'carhartt' w ofercie"]

    # Sprawdź czy zawiera jeden z wymaganych modeli
    models = search.get("carhartt_models", [])
    found_model = next((m for m in models if m in text), None)
    if not found_model:
        model_names = ", ".join(dict.fromkeys(
            m.split()[-1].title() for m in models   # unikalne nazwy modeli
        ))
        return False, [f"⛔ brak wymaganego modelu ({model_names})"]

    reasons.append(f"✅ model: {found_model}")

    # Sprawdź próg cenowy (dodatkowe zabezpieczenie — URL już filtruje)
    max_price = search.get("carhartt_max_price", 9999)
    reasons.append(f"✅ cena ≤ {max_price} zł")

    return True, reasons


# ─────────────────────────────────────────
#  🕵️ SPRAWDZANIE OFERT (HTML scraping)
# ─────────────────────────────────────────
def check_search(search, seen, market_price):
    found = []
    try:
        r = vinted_fetch(search["url"], label=search["name"])
        if not r:
            return []

        items = parse_items_from_html(r.text)
        print(f"[{search['name']}] Ofert na stronie: {len(items)}")

        for item in items:
            try:
                item_id = item["id"]
                if not item_id or item_id in seen:
                    continue

                title = item["title"]
                if not title:
                    continue

                href  = item["url"]
                price = item["price"]

                if not price or price < search.get("min_price", 1):
                    continue

            except Exception as e:
                print(f"  ⚠️ Błąd parsowania itemu: {e}")
                continue

            hidden_gem_mode = search.get("hidden_gem_mode", False)
            football_mode   = search.get("football_mode", False)
            lego_sw_mode    = search.get("lego_sw_mode", False)
            carhartt_mode   = search.get("carhartt_mode", False)

            # ── Tryb normalny: filtr słów kluczowych ──
            if not hidden_gem_mode and not lego_sw_mode and not carhartt_mode:
                keywords = search.get("keywords", [])
                if keywords and not any(kw.lower() in title.lower() for kw in keywords):
                    continue

            football_mode = search.get("football_mode", False)

            # ── Tryb koszulek retro ──
            if football_mode:
                keywords = search.get("keywords", [])
                if keywords and not any(kw.lower() in title.lower() for kw in keywords):
                    continue
                if any(rep in title.lower() for rep in REPLICA_KEYWORDS):
                    continue

            # ── Ocena okazji cenowej ──
            steal_threshold = STEAL_PRICES.get(search["category"], 9999)
            is_steal_price  = price <= steal_threshold
            is_below_market = False
            discount_pct    = 0
            if market_price and market_price > 0:
                discount_pct    = (1 - price / market_price) * 100
                is_below_market = discount_pct >= MIN_DISCOUNT_PCT

            # ── Detekcja błędnej pisowni ──
            typo_brand, typo_found = detect_typo_brand(title)
            has_typo = typo_brand is not None

            # ── Decyzja czy potrzebujemy szczegółów oferty ──
            needs_details = (
                hidden_gem_mode or football_mode or lego_sw_mode
                or carhartt_mode or has_typo or is_steal_price or is_below_market
            )

            # ── Pobierz szczegóły oferty (zdjęcie + opis) ──
            item_image_url   = None
            item_description = None
            if needs_details and ANTHROPIC_KEY:
                item_image_url, item_description = get_item_details(href)

            # ── AI analiza ──
            ai_result     = None
            is_hidden_gem = False
            ai_reason     = ""
            ai_brand      = None
            mismatch      = False

            if needs_details and ANTHROPIC_KEY:
                print(f"  🤖 AI scan: {title[:50]}")
                ai_result = analyze_with_ai(title, item_description, item_image_url)
                time.sleep(1)

                if ai_result:
                    is_hidden_gem = ai_result.get("is_hidden_gem", False)
                    ai_confidence = ai_result.get("confidence", 0)
                    ai_reason     = ai_result.get("reason", "")
                    ai_brand      = ai_result.get("detected_brand")
                    mismatch      = ai_result.get("mismatch", False)

                    if is_hidden_gem and ai_confidence < MIN_AI_CONFIDENCE:
                        is_hidden_gem = False

            # ── Walidacja LEGO Star Wars ──
            lego_sw_valid   = False
            lego_sw_score   = 0
            lego_sw_reasons = []
            lego_set_info   = {}
            if lego_sw_mode:
                lego_sw_valid, lego_sw_score, lego_sw_reasons, lego_set_info = validate_lego_sw(
                    title, item_description, ai_result   # ← reużywa pobranego opisu
                )
                if not lego_sw_valid:
                    print(f"  ⛔ odrzucono LEGO SW: {lego_sw_reasons[0] if lego_sw_reasons else ''}")
                    continue

            # ── Walidacja koszulki retro ──
            football_valid   = False
            football_reasons = []
            if football_mode:
                football_valid, football_reasons = validate_football_jersey(
                    title, item_description, ai_result   # ← reużywa pobranego opisu
                )
                if not football_valid:
                    print(f"  ⛔ odrzucono retro: {football_reasons[0] if football_reasons else ''}")
                    continue

            # ── Walidacja Carhartt ──
            carhartt_valid   = False
            carhartt_reasons = []
            if carhartt_mode:
                carhartt_valid, carhartt_reasons = validate_carhartt(
                    title, item_description, search      # ← reużywa pobranego opisu
                )
                if not carhartt_valid:
                    print(f"  ⛔ odrzucono Carhartt: {carhartt_reasons[0] if carhartt_reasons else ''}")
                    continue

            qualifies = (
                is_steal_price
                or is_below_market
                or has_typo
                or is_hidden_gem
                or football_valid
                or lego_sw_valid
                or carhartt_valid
            )

            if not qualifies:
                continue

            # Ustal powód alertu
            reasons = []
            if lego_sw_valid:
                reasons += lego_sw_reasons[:4]
            if football_valid:
                reasons += football_reasons
            if carhartt_valid:
                reasons += carhartt_reasons
            if has_typo:
                reasons.append(f"błędna pisownia: '{typo_found}' → {typo_brand}")
            if mismatch:
                reasons.append("zdjęcie ≠ opis (AI)")
            if ai_brand and ai_brand.lower() not in title.lower():
                reasons.append(f"AI rozpoznało: {ai_brand}")
            if is_below_market:
                reasons.append(f"-{discount_pct:.0f}% od mediany")
            if is_steal_price:
                reasons.append(f"cena steal <{steal_threshold} zł")
            if ai_reason:
                reasons.append(ai_reason)

            found.append({
                "id":               item_id,
                "title":            title,
                "link":             href,
                "price":            price,
                "market_price":     market_price,
                "discount_pct":     discount_pct,
                "is_steal":         is_steal_price,
                "is_below":         is_below_market,
                "has_typo":         has_typo,
                "typo_brand":       typo_brand,
                "is_hidden_gem":    is_hidden_gem,
                "mismatch":         mismatch,
                "ai_brand":         ai_brand,
                "reasons":          reasons,
                "lego_sw_valid":    lego_sw_valid,
                "lego_sw_score":    lego_sw_score,
                "lego_set_info":    lego_set_info,
                "football_valid":   football_valid,
                "carhartt_valid":   carhartt_valid,
            })

    except Exception as e:
        print(f"Błąd check_search [{search['name']}]: {e}")

    return found

# ─────────────────────────────────────────
#  ✉️ FORMAT WIADOMOŚCI
# ─────────────────────────────────────────
CATEGORY_EMOJI = {
    "sneakers": "👟",
    "clothing": "👕",
    "lego":     "🧱",
    "funko":    "🎭",
    "football": "⚽",
    "carhartt": "🧥",
}

def format_message(search, item):
    emoji = CATEGORY_EMOJI.get(search["category"], "🛍")
    lines = []

    # Nagłówek — LEGO Star Wars
    if search.get("lego_sw_mode"):
        score = item.get("lego_sw_score", 0)
        info  = item.get("lego_set_info", {})
        if score >= 70:
            lines.append("🚀 <b>LEGO STAR WARS — KULTOWY SET!</b>")
        elif item["discount_pct"] >= 40:
            lines.append(f"🧱 <b>LEGO SW OKAZJA! -{item['discount_pct']:.0f}% poniżej rynku</b>")
        else:
            lines.append("🧱 <b>LEGO Star Wars — kompletny zestaw</b>")

        lines.append(f"⭐ <b>{search['name']}</b>")
        lines.append("")
        lines.append(f"📦 {item['title'][:120]}")
        lines.append("")
        lines.append(f"💰 Cena: <b>{item['price']:.0f} zł</b>")
        if item["market_price"]:
            lines.append(f"📊 Średnia: <i>{item['market_price']:.0f} zł</i>")
            if item["discount_pct"] > 0:
                lines.append(f"✂️ Oszczędzasz: <b>~{item['market_price'] - item['price']:.0f} zł</b>")
        if info.get("set_number"):
            lines.append(f"🔢 Set: <b>#{info['set_number']}</b>")
        if info.get("vehicle"):
            lines.append(f"🚀 Pojazd: <i>{info['vehicle']}</i>")
        if info.get("character"):
            lines.append(f"🧑‍🚀 Postać: <i>{info['character']}</i>")
        if info.get("minifigs"):
            lines.append("🟡 Minifigurki: <b>tak</b>")
        if info.get("complete"):
            lines.append("✅ Kompletność: <b>kompletny</b>")
        if item["reasons"]:
            lines.append("")
            for r in item["reasons"][:3]:
                lines.append(f"  • {r}")
        lines.append("")
        lines.append(f"🔗 <a href=\"{item['link']}\">Otwórz ofertę na Vinted</a>")
        return "\n".join(lines)

    # Nagłówek — Carhartt
    if search.get("carhartt_mode"):
        max_p = search.get("carhartt_max_price", 9999)
        if item["discount_pct"] >= 40:
            lines.append(f"🧥 <b>CARHARTT OKAZJA! -{item['discount_pct']:.0f}% poniżej rynku</b>")
        else:
            lines.append(f"🧥 <b>CARHARTT — model poniżej {max_p} zł!</b>")
        lines.append(f"🧥 <b>{search['name']}</b>")
        lines.append("")
        lines.append(f"📦 {item['title'][:120]}")
        lines.append("")
        lines.append(f"💰 Cena: <b>{item['price']:.0f} zł</b>")
        if item["market_price"]:
            lines.append(f"📊 Średnia: <i>{item['market_price']:.0f} zł</i>")
            if item["discount_pct"] > 0:
                lines.append(f"✂️ Oszczędzasz: <b>~{item['market_price'] - item['price']:.0f} zł</b>")
        if item["reasons"]:
            lines.append("")
            for r in item["reasons"][:3]:
                lines.append(f"  • {r}")
        lines.append("")
        lines.append(f"🔗 <a href=\"{item['link']}\">Otwórz ofertę na Vinted</a>")
        return "\n".join(lines)

    # Nagłówek — koszulki retro mają własny styl
    if search.get("football_mode"):
        if item["discount_pct"] >= 40:
            lines.append(f"⚽ <b>RETRO JERSEY OKAZJA! -{item['discount_pct']:.0f}% poniżej rynku</b>")
        else:
            lines.append("⚽ <b>KOSZULKA RETRO — oryginał!</b>")
    elif item["mismatch"]:
        lines.append("🔮 <b>HIDDEN GEM — zdjęcie ≠ opis!</b>")
    elif item["has_typo"]:
        lines.append(f"🔤 <b>BŁĘDNA PISOWNIA — może być {item['typo_brand'].upper()}!</b>")
    elif item["is_hidden_gem"]:
        lines.append("💎 <b>HIDDEN GEM wykryty przez AI!</b>")
    elif item["discount_pct"] >= 60:
        lines.append(f"🚨 <b>MEGA OKAZJA! -{item['discount_pct']:.0f}% poniżej rynku</b>")
    elif item["is_below"]:
        lines.append(f"🔥 <b>OKAZJA! -{item['discount_pct']:.0f}% poniżej rynku</b>")
    else:
        lines.append("💸 <b>NISKA CENA STEAL!</b>")

    lines.append(f"{emoji} <b>{search['name']}</b>")
    lines.append("")
    lines.append(f"📦 {item['title'][:120]}")
    lines.append("")
    lines.append(f"💰 Cena: <b>{item['price']:.0f} zł</b>")

    if item["market_price"]:
        lines.append(f"📊 Średnia rynkowa: <i>{item['market_price']:.0f} zł</i>")
        if item["discount_pct"] > 0:
            saved = item["market_price"] - item["price"]
            lines.append(f"✂️ Oszczędzasz: <b>~{saved:.0f} zł</b>")

    if item["ai_brand"]:
        lines.append(f"🤖 AI rozpoznało markę: <b>{item['ai_brand']}</b>")

    if item["reasons"]:
        lines.append("")
        lines.append("📋 <i>Powód alertu:</i>")
        for r in item["reasons"][:3]:
            lines.append(f"  • {r}")

    lines.append("")
    lines.append(f"🔗 <a href=\"{item['link']}\">Otwórz ofertę na Vinted</a>")

    return "\n".join(lines)

# ─────────────────────────────────────────
#  🚀 GŁÓWNA PĘTLA
# ─────────────────────────────────────────
print("✅ BOT HIDDEN GEM FINDER URUCHOMIONY")

# Pobierz sesję Vinted przed startem
refresh_session()

send_message(
    "✅ <b>Vinted Hidden Gem Finder uruchomiony!</b>\n\n"
    f"🔍 Monitoruję {len(SEARCHES)} wyszukiwań\n"
    f"🤖 AI analiza: {'✅ aktywna' if ANTHROPIC_KEY else '⚠️ brak klucza'}\n"
    f"🎯 Progi: -{MIN_DISCOUNT_PCT}% od mediany | ceny steal\n\n"
    "📦 Kategorie:\n"
    "  👟 Sneakersy | 👕 Ubrania\n"
    "  🧱 LEGO ogólne | 🎭 Funko Pop\n"
    "  ⭐ LEGO Star Wars (kompletne zestawy)\n"
    "  ⚽ Koszulki retro 70s/80s/90s/2000s\n"
    "  🧥 Carhartt: Trucker ≤150 zł | Santa Fe/Detroit/Active ≤250 zł\n"
    "  💎 Hidden Gem (AI scan)\n\n"
    "🔤 Detekcja typo: Nike/Adidas/Supreme/Carhartt...\n"
    "⚽ Retro: tylko oryginały, bez replik"
)

seen          = load_seen()
market_prices = {}
cycle         = 0

while True:
    try:
        # Co 50 cykli (~50 min) odśwież sesję Vinted
        if cycle % 50 == 0:
            refresh_session()

        if cycle % 10 == 0:
            print("\n📊 Aktualizuję mediany rynkowe...")
            for i, search in enumerate(SEARCHES):
                # Pomijamy hidden_gem_mode — nie mają sensu mediany
                if search.get("hidden_gem_mode"):
                    continue
                print(f"  [{i+1}/{len(SEARCHES)}] {search['name']}...")
                market_prices[search["name"]] = get_market_median(search)
            print("📊 Mediany gotowe — startuje cykl")

        cycle += 1
        print(f"\n🔄 Cykl #{cycle}")

        for search in SEARCHES:
            print(f"  ⏳ Sprawdzam: {search['name']}")
            market_price = market_prices.get(search["name"])
            new_items    = check_search(search, seen, market_price)
            print(f"  ✔ Gotowe: {search['name']} — nowych: {len(new_items)}")

            for item in new_items:
                msg = format_message(search, item)
                send_message(msg)
                seen[item["id"]] = time.time()
                tag = "💎" if item["is_hidden_gem"] else ("🔤" if item["has_typo"] else "✉️")
                print(f"  {tag} {item['title'][:55]} | {item['price']:.0f} zł")

        save_seen(seen)
        time.sleep(60)

    except Exception as e:
        print(f"Błąd głównej pętli: {e}")
        time.sleep(15)
