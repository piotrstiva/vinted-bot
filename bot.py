
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
MIN_SAVING_PLN   = 6       # minimalna oszczędność w zł (odrzuć 1-5 zł różnicę)
MAX_ALERTS_PER_SEARCH = 5  # max powiadomień per wyszukiwanie per cykl

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
#  🚫 SŁOWA KTÓRE ZAWSZE ODRZUCAMY
# ─────────────────────────────────────────
GLOBAL_EXCLUDE = [
    # Ubrania dziecięce
    "dziecięc", "dzieciec", "niemowl", "chłopięc", "chlopiec",
    "dziewczęc", "dziewczec", "dla dzieci", "dla chłopca", "dla dziewcz",
    "rozmiar 86", "rozmiar 92", "rozmiar 98", "rozmiar 104",
    "rozmiar 110", "rozmiar 116", "rozmiar 122", "rozmiar 128",
    "r.86", "r.92", "r.98", "r.104", "r.110", "r.116",
    "duplo", "baby", "junior ", "kids ", " kid ", "toddler",
    # Karty/albumy LEGO
    "karta lego", "karty lego", "album lego", "naklejki lego",
    "lego karta", "lego album", "lego naklejki", "lego card",
    "trading card", "trading kart", "sticker", "naklejka",
    # Minecraft
    "minecraft",
    # Gry video
    "nintendo switch", "xbox", "playstation", "ps4", "ps5",
    "gra lego", "lego gra", "lego game",
]

# ─────────────────────────────────────────
#  🚫 MARKI KTÓRYCH NIE CHCEMY NIGDY
# ─────────────────────────────────────────
BLOCKED_BRANDS = [
    # Fast fashion
    "h&m", "zara", "bershka", "sinsay", "reserved", "house",
    "shein", "primark", "pepco", "c&a", "stradivarius",
    "new yorker", "cropp", "new look", "boohoo", "asos",
    "pull&bear", "mango", "vero moda", "only ", "jack&jones",
    "terranova", "mohito", "medicine", "diverse", "carry",
    "lager 157", "rainbow ", "iné", "amisu", "george ",
    # Premium marki których nie chcemy
    "tommy hilfiger", "tommy jeans", "calvin klein", "ralph lauren",
    "lacoste", "hugo boss", "boss ", "michael kors", "guess ",
    "armani exchange", "emporio armani",
    # Sportowe masowe
    "under armour", "columbia ", "quechua", "decathlon",
    "jack wolfskin", "the north face", "regatta",
]

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
        "exclude_keywords": ["polybag", "bitty", "keychain", "brelok", "kulcstart", "nyckelring", "mints", "saszetk"],
        "min_price": 15,
        "lego_sw_mode": True,
    },
    {
        "name":     "LEGO Star Wars — numery setów",
        "url":      "https://www.vinted.pl/catalog?search_text=lego+75&order=newest_first&currency=PLN&price_to=100",
        "category": "lego_sw",
        "keywords": ["lego", "75"],
        "exclude_keywords": ["polybag", "bitty", "keychain", "brelok", "kulcstart", "nyckelring"],
        "min_price": 15,
        "lego_sw_mode": True,
    },
    {
        "name":     "LEGO Star Wars — pojazdy",
        "url":      "https://www.vinted.pl/catalog?search_text=lego+x-wing+falcon+death+star&order=newest_first&currency=PLN&price_to=100",
        "category": "lego_sw",
        "keywords": ["lego"],
        "exclude_keywords": ["polybag", "bitty", "keychain", "brelok"],
        "min_price": 15,
        "lego_sw_mode": True,
    },
    {
        "name":     "LEGO zestawy (ogólne)",
        "url":      "https://www.vinted.pl/catalog?search_text=lego&order=newest_first&currency=PLN",
        "category": "lego",
        "keywords": ["lego", "technic", "city", "ninjago", "harry potter", "creator"],
        "exclude_keywords": ["polybag", "bitty", "keychain", "brelok"],
        "brands":   ["lego"],
        "min_price": 20,
    },
    {
        "name":     "Funko Pop",
        "url":      "https://www.vinted.pl/catalog?search_text=funko+pop&order=newest_first&currency=PLN",
        "category": "funko",
        "keywords": ["funko", "pop", "vinyl", "figurka"],
        "exclude_keywords": ["bitty", "minis", "funko minis", "pocket pop"],
        "brands":   ["funko"],
        "min_price": 10,
    },
    {
        "name":     "Funko Pop Star Wars (do 30 zł)",
        "url":      "https://www.vinted.pl/catalog?search_text=funko+pop+star+wars&order=newest_first&currency=PLN&price_to=30",
        "category": "funko",
        "keywords": ["funko", "star wars"],
        "exclude_keywords": ["bitty", "minis", "pocket pop"],
        "min_price": 5,
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
    # ── HIDDEN GEM — tylko gdy mamy klucz AI ──
    # Bez ANTHROPIC_KEY te wyszukiwania wysyłają wszystko bez filtracji
    # Włączone tylko gdy ANTHROPIC_KEY jest ustawiony w Railway
    {
        "name":     "Buty bez marki (hidden gem)",
        "url":      "https://www.vinted.pl/catalog?catalog[]=1206&order=newest_first&currency=PLN&price_to=80",
        "category": "sneakers",
        "keywords": ["nike", "adidas", "jordan", "puma", "reebok", "new balance", "vans", "converse"],
        "brands":   [],
        "min_price": 20,
        "hidden_gem_mode": True,
    },
    {
        "name":     "Ubrania bez marki (hidden gem)",
        "url":      "https://www.vinted.pl/catalog?catalog[]=4&order=newest_first&currency=PLN&price_to=30",
        "category": "clothing",
        "keywords": ["supreme", "stone island", "carhartt", "nike", "adidas", "ralph lauren", "tommy hilfiger", "lacoste"],
        "brands":   [],
        "min_price": 10,
        "hidden_gem_mode": True,
    },
]

# ─────────────────────────────────────────
#  💾 PAMIĘĆ  (z automatycznym czyszczeniem)
# ─────────────────────────────────────────
SEEN_FILE      = "seen_items.json"
SEEN_MAX_DAYS  = 30   # pamiętamy ID przez 30 dni — blokuje stare oferty

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
def get_vinted_thumb(item_url, item_id):
    return None


_last_tg_send   = 0.0
TG_MIN_INTERVAL = 2.0


def send_message(text, photo_url=None, item_link=None):
    global _last_tg_send
    import json as _json
    tg_base = f"https://api.telegram.org/bot{TOKEN}"

    elapsed = time.time() - _last_tg_send
    if elapsed < TG_MIN_INTERVAL:
        time.sleep(TG_MIN_INTERVAL - elapsed)

    clean = re.sub(r'<[^>]+>', '', text)

    # Klikalny przycisk z linkiem do oferty
    reply_markup = None
    if item_link:
        reply_markup = _json.dumps({
            "inline_keyboard": [[{"text": "🔗 Otwórz na Vinted", "url": item_link}]]
        })

    try:
        sent = False

        if photo_url:
            data = {"chat_id": CHAT_ID, "photo": photo_url, "caption": clean[:1024]}
            if reply_markup:
                data["reply_markup"] = reply_markup
            r = requests.post(f"{tg_base}/sendPhoto", data=data, timeout=15)
            if r.status_code == 200:
                sent = True
            elif r.status_code == 429:
                time.sleep(5)

        if not sent:
            data = {
                "chat_id":                  CHAT_ID,
                "text":                     clean[:4096],
                "disable_web_page_preview": True,
            }
            if reply_markup:
                data["reply_markup"] = reply_markup
            r = requests.post(f"{tg_base}/sendMessage", data=data, timeout=10)
            if r.status_code == 429:
                time.sleep(5)
                requests.post(f"{tg_base}/sendMessage", data=data, timeout=10)

        _last_tg_send = time.time()

    except Exception as e:
        print(f"Błąd wysyłania: {e}")

# ─────────────────────────────────────────
#  💰 WYCIĄGANIE CENY
# ─────────────────────────────────────────
def extract_price(text):
    """
    Wyciąga cenę z tekstu.
    Ignoruje liczby które wyglądają jak numery setów LEGO (4-5 cyfr w tytule)
    oraz inne fałszywe ceny.
    """
    if not text:
        return None

    # Szukamy wzorca ceny: liczba po której następuje "zł" lub "PLN"
    # albo liczba poprzedzona symbolem waluty
    price_patterns = [
        r'(\d+[.,]?\d*)\s*(?:zł|PLN|pln)',   # "150 zł" lub "150PLN"
        r'(?:cena|price)[:\s]+(\d+[.,]?\d*)',  # "cena: 150"
    ]

    for pattern in price_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(",", "."))
                if 1 < val < 5000:
                    return val
            except:
                pass

    # Fallback: ostatnia liczba w tekście jeśli jest sensowna
    nums = re.findall(r'\b(\d+[.,]?\d*)\b', text.replace("\xa0", " "))
    candidates = []
    for n in nums:
        try:
            val = float(n.replace(",", "."))
            if 1 < val < 5000:   # max 5000 zł — eliminuje numery setów
                candidates.append(val)
        except:
            pass

    return candidates[-1] if candidates else None

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
    Vinted renderuje przez JS — HTML nie zawiera treści ofert.
    Zamiast tego wyciągamy dane z JSON osadzonego w stronie
    (window.__PRELOADED_STATE__ lub podobny).
    Zwraca listę dictów: {id, title, price, url}
    """
    items    = []
    seen_ids = set()

    # Vinted osadza dane jako JSON w tagu <script>
    # Szukamy: "items":[{...}] lub "catalogItems":[{...}]
    patterns = [
        r'"items"\s*:\s*(\[.*?\])\s*[,}]',
        r'"catalogItems"\s*:\s*(\[.*?\])\s*[,}]',
        r'"data"\s*:\s*(\[.*?\])\s*[,}]',
    ]

    import json as _json

    for pattern in patterns:
        matches = re.findall(pattern, html, re.DOTALL)
        for match in matches:
            try:
                data = _json.loads(match)
                if not isinstance(data, list) or len(data) == 0:
                    continue
                if not isinstance(data[0], dict):
                    continue
                # Sprawdź czy to faktycznie lista ofert (musi mieć id i url/path)
                if "id" not in data[0] and "url" not in data[0]:
                    continue

                for entry in data:
                    try:
                        item_id = str(entry.get("id", ""))
                        if not item_id or not item_id.isdigit():
                            continue
                        if item_id in seen_ids:
                            continue
                        seen_ids.add(item_id)

                        title = entry.get("title", "") or entry.get("name", "") or ""
                        url   = entry.get("url", "") or f"https://www.vinted.pl/items/{item_id}"
                        if not url.startswith("http"):
                            url = "https://www.vinted.pl" + url

                        # Filtr czasu — tylko oferty z ostatnich 24h
                        created = (
                            entry.get("created_at_ts") or
                            entry.get("created_at") or
                            entry.get("last_push_up_at") or
                            entry.get("updated_at_ts") or
                            0
                        )
                        if created:
                            try:
                                ts = float(created)
                                # Jeśli timestamp w milisekundach — przelicz
                                if ts > 1e12:
                                    ts = ts / 1000
                                age_hours = (time.time() - ts) / 3600
                                if age_hours > 24:
                                    continue
                            except:
                                pass

                        # cena — może być string lub float
                        raw_price = entry.get("price", "") or entry.get("price_numeric", "")
                        price = None
                        try:
                            price = float(str(raw_price).replace(",", ".").replace(" ", ""))
                        except:
                            pass

                        # Zdjęcie — różne pola w zależności od wersji API
                        photo_url = None
                        photos = entry.get("photos") or entry.get("photo") or []
                        if isinstance(photos, list) and photos:
                            p = photos[0]
                            if isinstance(p, dict):
                                photo_url = (
                                    p.get("url") or
                                    p.get("full_size_url") or
                                    p.get("thumbnails", [{}])[0].get("url") if p.get("thumbnails") else None
                                )
                        elif isinstance(photos, dict):
                            photo_url = photos.get("url") or photos.get("full_size_url")

                        if title:
                            items.append({
                                "id":    item_id,
                                "title": title,
                                "price": price,
                                "url":   url,
                                "photo": photo_url,
                            })
                    except:
                        continue

                if items:
                    return items

            except:
                continue

    # Fallback: szukaj linków i tytułów przez og:title / meta
    if not items:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            if "/items/" not in href:
                continue
            if not href.startswith("http"):
                href = "https://www.vinted.pl" + href
            try:
                item_id = href.split("/items/")[1].split("-")[0].split("?")[0]
                if not item_id.isdigit() or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                # Tytuł z atrybutu title lub aria-label
                title = (
                    tag.get("title") or
                    tag.get("aria-label") or
                    tag.get_text(" ", strip=True)
                )
                price = extract_price(title) if title else None
                items.append({
                    "id":    item_id,
                    "title": title or "",
                    "price": price,
                    "url":   href,
                    "photo": None,
                })
            except:
                continue

    return items


# ─────────────────────────────────────────
#  🖼️ POBIERANIE SZCZEGÓŁÓW OFERTY (HTML)
# ─────────────────────────────────────────
def get_item_photo(item_id, item_url):
    """
    Pobiera URL zdjęcia oferty przez Vinted API.
    Zwraca URL zdjęcia lub None.
    """
    try:
        api_url = f"https://www.vinted.pl/api/v2/items/{item_id}"
        r = requests.get(api_url, headers={
            **get_headers(),
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        }, timeout=10)
        if r.status_code == 200:
            data = r.json()
            item = data.get("item", {})
            photos = item.get("photos", [])
            if photos:
                # Weź pierwsze zdjęcie, preferuj full_size_url
                p = photos[0]
                url = p.get("full_size_url") or p.get("url") or p.get("thumb_url")
                if url:
                    return url
    except:
        pass
    return None
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
#  🧱 BRICKLINK — ceny rynkowe LEGO
#  Cache zapisywany do pliku JSON
#  Odświeżamy ceny raz na 24h per set
# ─────────────────────────────────────────
BRICKLINK_CACHE_FILE = "bricklink_prices.json"
BRICKLINK_CACHE_TTL  = 24 * 3600  # 24h

_bl_cache = {}

def load_bricklink_cache():
    global _bl_cache
    try:
        if os.path.exists(BRICKLINK_CACHE_FILE):
            with open(BRICKLINK_CACHE_FILE) as f:
                _bl_cache = json.load(f)
    except:
        _bl_cache = {}

def save_bricklink_cache():
    try:
        with open(BRICKLINK_CACHE_FILE, "w") as f:
            json.dump(_bl_cache, f)
    except:
        pass

def get_bricklink_price(set_number):
    """
    Pobiera średnią cenę sprzedaży setu z BrickLink (używane).
    Zwraca cenę w PLN lub None.
    Cache 24h — nie odpytujemy za każdym razem.
    """
    global _bl_cache
    now = time.time()

    # Sprawdź cache
    if set_number in _bl_cache:
        entry = _bl_cache[set_number]
        if now - entry.get("ts", 0) < BRICKLINK_CACHE_TTL:
            return entry.get("price_pln")

    try:
        # BrickLink price guide — publiczna strona bez logowania
        # Używamy strony z cenami "used" (odpowiada Vinted)
        url = f"https://www.bricklink.com/v2/catalog/catalogitem.page?S={set_number}-1"
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }, timeout=15)

        if r.status_code != 200:
            return None

        # Szukamy ceny average w HTML — BrickLink pokazuje ją jako
        # "Avg Price: $XX.XX" lub w meta tagach
        text = r.text

        # Szukaj average price dla "Used" (U) condition
        avg_usd = None

        # Format: pewne fragmenty HTML z ceną
        patterns = [
            r'avg_price["\s:]+\$?([\d,\.]+)',
            r'Avg Price.*?\$([\d,\.]+)',
            r'"avg_price":"([\d\.]+)"',
            r'id="val_used_qty"[^>]*>.*?Avg.*?\$([\d\.]+)',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                try:
                    avg_usd = float(m.group(1).replace(",", ""))
                    if avg_usd > 0:
                        break
                except:
                    pass

        # Alternatywnie — szukaj w JSON osadzonym w stronie
        if not avg_usd:
            json_match = re.search(r'"avg_price"\s*:\s*"?([\d\.]+)"?', text)
            if json_match:
                try:
                    avg_usd = float(json_match.group(1))
                except:
                    pass

        if avg_usd:
            # Przelicz USD → PLN (kurs ~4.0)
            price_pln = avg_usd * 4.0
            _bl_cache[set_number] = {"price_pln": price_pln, "ts": now}
            save_bricklink_cache()
            print(f"  🧱 BrickLink #{set_number}: ${avg_usd:.2f} → {price_pln:.0f} zł")
            return price_pln

    except Exception as e:
        print(f"  ⚠️ BrickLink error #{set_number}: {e}")

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

    # Wymagamy WSZYSTKICH: Star Wars + LEGO + cokolwiek rozpoznane
    has_sw   = "star wars" in text or "starwars" in text or "gwiezdne wojny" in text
    has_lego = "lego" in text
    has_anything = found_set or found_vehicle or found_char

    if not has_sw:
        return False, 0, ["⛔ brak 'star wars' w tytule"], {}
    if not has_lego:
        return False, 0, ["⛔ brak 'lego' w tytule"], {}
    if not has_anything:
        return False, 0, ["⛔ brak rozpoznanego setu/pojazdu/postaci"], {}

    # Gry video — odrzuć
    if any(g in text for g in ["nintendo", "xbox", "playstation", "ps4", "ps5", "nintendo ds", "nintendo switch", "pc game", "gra na "]):
        return False, 0, ["⛔ gra video — odrzucono"], {}

    set_info = {
        "set_number":   found_set,
        "vehicle":      found_vehicle,
        "character":    found_char,
        "complete":     is_complete,
        "minifigs":     has_minifigs,
        "bl_price_pln": None,
    }

    # Pobierz cenę BrickLink jeśli znamy numer setu
    if found_set:
        bl_price = get_bricklink_price(found_set)
        if bl_price:
            set_info["bl_price_pln"] = bl_price
            reasons.append(f"🧱 BrickLink: ~{bl_price:.0f} zł")
            score += 10

    # Podnosimy próg — minimum 35 punktów
    is_valid = score >= 35
    return is_valid, score, reasons, set_info


# ─────────────────────────────────────────
#  ⚽ WALIDACJA KOSZULKI RETRO
# ─────────────────────────────────────────
def validate_football_jersey(title, description, ai_result):
    text = (title + " " + (description or "")).lower()

    # 1. Odrzuć repliki
    for rep in REPLICA_KEYWORDS:
        if rep in text:
            return False, ["replika — odrzucono"]

    # 2. Odrzuć śmieci — ROZSZERZONA lista
    NOISE = [
        "swag", "y2k", "00s ", "avant garde", "coquette", "drippy",
        "gorset", "spódniczk", "bluzka na", "top na ramiac", "body ",
        "koronkow", "halter", "babydoll", "cycling", "basketball",
        "primark", "stradivarius", "bershka", "muślinow", "satynow",
        "alt alternative", "japan style", "cropped top", "tank top",
        "pinterest", "taliow", "wiązan", "ażurow", "prześwituj",
        "goth", "aesthetic", "streetwear archive", "hip hop",
        "longsleeve vintage", "bluza vintage", "t-shirt vintage",
        "damsk", "damsk", "girl", "women", "woman",
        " top ", "bluzka", "sukienk", "spodnie", "kurtka jeans",
    ]
    for noise in NOISE:
        if noise in text:
            return False, [f"odrzucono: {noise.strip()}"]

    # 3. Musi zawierać "koszulka" lub "jersey" lub "shirt"
    is_jersey = any(w in text for w in ["koszulka", "jersey", "shirt", "trikot", "maillot"])
    if not is_jersey:
        return False, ["brak słowa koszulka/jersey"]

    # 4. Musi mieć oryginalną markę piłkarską
    has_brand = any(b in text for b in FOOTBALL_ORIGINAL_BRANDS)
    if not has_brand:
        return False, ["brak oryginalnej marki"]

    # 5. Musi mieć klub LUB reprezentację — WYMAGANE
    has_club = any(c in text for c in FOOTBALL_CLUBS)
    if not has_club:
        return False, ["brak klubu/reprezentacji"]

    # 6. Musi mieć słowo retro/vintage LUB rok z okresu 1970-2003
    is_retro = any(d in text for d in RETRO_DECADES)
    if not is_retro:
        return False, ["brak słowa retro/vintage lub roku 70s-2003"]

    reasons = []
    if has_brand:  reasons.append("✅ oryginalna marka")
    if has_club:   reasons.append("✅ klub/reprezentacja")
    if is_retro:   reasons.append("✅ retro/vintage")
    return True, reasons



# ─────────────────────────────────────────
#  🧥 WALIDACJA CARHARTT
# ─────────────────────────────────────────
def validate_carhartt(title, description, search):
    """
    Zwraca (is_valid, model_name, max_price, reasons)
    search = słownik wyszukiwania z carhartt_models i carhartt_max_price
    """
    text = (title + " " + (description or "")).lower()

    # Musi zawierać Carhartt (lub typo)
    if "carhartt" not in text:
        typo_brand, _ = detect_typo_brand(text)
        if typo_brand != "carhartt":
            return False, None, 0, ["brak marki Carhartt"]

    # Pobierz listę modeli i próg cenowy z wyszukiwania
    required_models = search.get("carhartt_models", [])
    max_price       = search.get("carhartt_max_price", 250)

    # Sprawdź czy oferta zawiera jeden z wymaganych modeli
    detected_model = None
    for model_kw in required_models:
        if model_kw in text:
            detected_model = model_kw
            break

    if not detected_model:
        if required_models:
            # Wyszukiwanie wymaga konkretnego modelu — odrzuć
            return False, None, 0, [f"brak modelu ({', '.join(required_models[:3])})"]
        else:
            detected_model = "carhartt"

    reasons = [
        f"✅ Carhartt {detected_model}",
        f"✅ cena ≤ {max_price} zł",
    ]
    return True, detected_model, max_price, reasons


# ─────────────────────────────────────────
#  🕵️ SPRAWDZANIE OFERT (HTML scraping)
# ─────────────────────────────────────────
def check_search(search, seen, market_price):
    found    = []
    all_ids  = []   # wszystkie ID widziane w tym cyklu
    cnt_seen = cnt_price = cnt_kw = cnt_rejected = 0

    try:
        r = vinted_fetch(search["url"], label=search["name"])
        if not r:
            return [], []

        items = parse_items_from_html(r.text)
        print(f"[{search['name']}] Ofert na stronie: {len(items)}")
        # Debug — pokaż pierwsze 2 tytuły żeby sprawdzić czy dane są poprawne
        for dbg in items[:2]:
            print(f"  🔍 '{dbg['title'][:60]}' | {dbg['price']} zł")

        hidden_gem_mode = search.get("hidden_gem_mode", False)
        football_mode   = search.get("football_mode", False)
        lego_sw_mode    = search.get("lego_sw_mode", False)
        carhartt_mode   = search.get("carhartt_mode", False)

        for item in items:
            if not item:
                continue
            try:
                item_id = item.get("id", "")
                title   = item.get("title", "")
                href    = item.get("url", "")
                price   = item.get("price")

                if not item_id or item_id in seen:
                    cnt_seen += 1
                    continue

                all_ids.append(item_id)  # zapamiętaj wszystkie widziane

                if not title or not href:
                    continue

                # Globalny filtr wykluczeń (dzieci, minecraft, karty, gry)
                title_lower = title.lower()
                if any(ex in title_lower for ex in GLOBAL_EXCLUDE):
                    continue

                # Odrzuć zablokowane marki (H&M, Zara, Bershka itp.)
                if any(b in title_lower for b in BLOCKED_BRANDS):
                    continue

                # Odrzuć wykluczone słowa kluczowe z danego wyszukiwania
                exclude_kw = search.get("exclude_keywords", [])
                if exclude_kw and any(ek in title_lower for ek in exclude_kw):
                    continue

                if not price or price < search.get("min_price", 1):
                    cnt_price += 1
                    continue

                # filtr słów kluczowych
                # hidden_gem_mode bez AI → używaj keywords jak normalny tryb
                effective_hidden = hidden_gem_mode and bool(ANTHROPIC_KEY)
                if not effective_hidden and not lego_sw_mode and not carhartt_mode and not football_mode:
                    keywords = search.get("keywords", [])
                    if keywords and not any(kw.lower() in title.lower() for kw in keywords):
                        cnt_kw += 1
                        continue

                # ocena cenowa
                steal_threshold = STEAL_PRICES.get(search["category"], 9999)
                is_steal_price  = price <= steal_threshold
                is_below_market = False
                discount_pct    = 0
                if market_price and market_price > 0:
                    discount_pct    = (1 - price / market_price) * 100
                    saving          = market_price - price
                    # Odrzuć jeśli oszczędność mniejsza niż MIN_SAVING_PLN
                    is_below_market = (
                        discount_pct >= MIN_DISCOUNT_PCT
                        and saving >= MIN_SAVING_PLN
                    )

                # typo
                typo_brand, typo_found = detect_typo_brand(title)
                has_typo = typo_brand is not None

                # walidacje specjalne
                lego_sw_valid, lego_sw_score, lego_sw_reasons, lego_set_info = False, 0, [], {}
                if lego_sw_mode:
                    lego_sw_valid, lego_sw_score, lego_sw_reasons, lego_set_info = validate_lego_sw(title, None, None)
                    # Podnosimy minimalny próg — żeby odrzucić śmieci
                    if lego_sw_score < 40:
                        lego_sw_valid = False
                    # Max cena dla LEGO SW
                    if price > 100:
                        lego_sw_valid = False

                football_valid, football_reasons = False, []
                if football_mode:
                    football_valid, football_reasons = validate_football_jersey(title, None, None)

                carhartt_valid, carhartt_reasons, carhartt_model_name, carhartt_max = False, [], None, 0
                if carhartt_mode:
                    cv, cm, cmax, cr = validate_carhartt(title, None, search)
                    if cv and price <= cmax:
                        carhartt_valid, carhartt_model_name, carhartt_max, carhartt_reasons = True, cm, cmax, cr

                # AI (tylko hidden gem)
                is_hidden_gem, ai_brand, ai_reason, mismatch = False, None, "", False
                if ANTHROPIC_KEY and hidden_gem_mode:
                    img_url, desc = get_item_details(href)
                    ai_res = analyze_with_ai(title, desc, img_url)
                    if ai_res:
                        is_hidden_gem = ai_res.get("is_hidden_gem", False)
                        if ai_res.get("confidence", 0) < MIN_AI_CONFIDENCE:
                            is_hidden_gem = False
                        ai_brand  = ai_res.get("detected_brand")
                        ai_reason = ai_res.get("reason", "")
                        mismatch  = ai_res.get("mismatch", False)

                # finalna decyzja
                if lego_sw_mode:
                    # LEGO SW — tylko przez walidator, cena nie wystarczy
                    qualifies = lego_sw_valid
                elif football_mode:
                    # Koszulki — tylko przez walidator
                    qualifies = football_valid
                elif carhartt_mode:
                    qualifies = carhartt_valid
                elif hidden_gem_mode and not ANTHROPIC_KEY:
                    # Hidden gem bez AI — tylko steal price z keywords
                    qualifies = is_steal_price or is_below_market
                else:
                    # Tryb normalny — cena + typo + AI
                    qualifies = (
                        is_steal_price or is_below_market
                        or has_typo or is_hidden_gem
                    )
                if not qualifies:
                    cnt_rejected += 1
                    continue

                reasons = []
                if lego_sw_valid:      reasons += lego_sw_reasons[:3]
                if football_valid:     reasons += football_reasons[:3]
                if carhartt_valid:     reasons.append(f"✅ model: {carhartt_model_name} | próg ≤{carhartt_max} zł")
                if has_typo:           reasons.append(f"błędna pisownia: '{typo_found}' → {typo_brand}")
                if mismatch:           reasons.append("zdjęcie ≠ opis (AI)")
                if is_below_market:    reasons.append(f"-{discount_pct:.0f}% od mediany")
                if is_steal_price:     reasons.append(f"cena steal <{steal_threshold} zł")
                if ai_reason:          reasons.append(ai_reason)

                found.append({
                    "id": item_id, "title": title, "link": href,
                    "price": price, "market_price": market_price,
                    "discount_pct": discount_pct,
                    "is_steal": is_steal_price, "is_below": is_below_market,
                    "has_typo": has_typo, "typo_brand": typo_brand if has_typo else None,
                    "is_hidden_gem": is_hidden_gem, "mismatch": mismatch,
                    "ai_brand": ai_brand, "reasons": reasons,
                    "lego_sw_valid": lego_sw_valid, "lego_sw_score": lego_sw_score,
                    "lego_set_info": lego_set_info,
                    "football_valid": football_valid,
                    "carhartt_valid": carhartt_valid,
                    "carhartt_model": carhartt_model_name,
                    "carhartt_max": carhartt_max,
                    "photo": item.get("photo"),
                })

            except Exception as e:
                print(f"  ⚠️ item error: {e}")
                continue

    except Exception as e:
        print(f"Błąd check_search [{search['name']}]: {e}")

    print(f"  📊 widziane={cnt_seen} brak_ceny={cnt_price} brak_słów={cnt_kw} odrzucone={cnt_rejected} wysłane={len(found)}")
    return found, all_ids


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
    price = item["price"]
    title = item["title"][:100]
    link  = item["link"]
    mp    = item.get("market_price")
    disc  = item.get("discount_pct", 0)

    # Nagłówek
    if search.get("lego_sw_mode"):
        if item.get("lego_sw_score", 0) >= 70:
            header = "🚀 LEGO STAR WARS — KULTOWY SET!"
        elif disc >= 40:
            header = f"🧱 LEGO SW OKAZJA! -{disc:.0f}% taniej"
        else:
            header = "🧱 LEGO Star Wars — zestaw"
    elif search.get("football_mode"):
        if disc >= 40:
            header = f"⚽ RETRO OKAZJA! -{disc:.0f}% taniej"
        else:
            header = "⚽ KOSZULKA RETRO — oryginal!"
    elif search.get("carhartt_mode"):
        model = (item.get("carhartt_model") or "").replace("_", " ").title()
        header = f"🧥 CARHARTT {model}".strip()
    elif item.get("mismatch"):
        header = "🔮 HIDDEN GEM — zdjecie nie pasuje do opisu!"
    elif item.get("has_typo"):
        header = f"🔤 BLEDNA PISOWNIA -> moze byc {(item.get('typo_brand') or '').upper()}!"
    elif item.get("is_hidden_gem"):
        header = "💎 HIDDEN GEM wykryty przez AI!"
    elif disc >= 60:
        header = f"🚨 MEGA OKAZJA! -{disc:.0f}% ponizej rynku"
    elif disc >= 40:
        header = f"🔥 OKAZJA! -{disc:.0f}% ponizej rynku"
    else:
        header = f"💸 {emoji} NISKA CENA!"

    lines = [header, "", f"📦 {title}", "", f"💰 Cena: {price:.0f} zl"]

    if mp:
        lines.append(f"📊 Srednia: {mp:.0f} zl")
        if disc > 0:
            lines.append(f"✂️ Oszczedzasz: ~{mp - price:.0f} zl")

    if search.get("lego_sw_mode"):
        info = item.get("lego_set_info", {})
        if info.get("set_number"):
            lines.append(f"🔢 Set: #{info['set_number']}")
        if info.get("vehicle"):
            lines.append(f"🚀 {info['vehicle']}")
        if info.get("character"):
            lines.append(f"👤 {info['character']}")
        if info.get("minifigs"):
            lines.append("🟡 Minifigurki: tak")
        # Cena BrickLink jako referencja rynkowa
        bl_price = info.get("bl_price_pln")
        if bl_price and bl_price > price:
            saving_bl = bl_price - price
            lines.append(f"🧱 BrickLink used: ~{bl_price:.0f} zl")
            lines.append(f"💚 Oszczedzasz vs BrickLink: ~{saving_bl:.0f} zl")

    reasons = item.get("reasons", [])
    if reasons:
        lines.append("")
        for r in reasons[:2]:
            lines.append(f"• {r}")

    # ── Separator i nagłówek kategorii ──
    CAT_LABEL = {
        "sneakers": "👟 Sneakersy",
        "clothing": "👕 Ubrania",
        "lego":     "🧱 LEGO",
        "lego_sw":  "⭐ LEGO Star Wars",
        "funko":    "🎭 Funko Pop",
        "football": "⚽ Koszulka Retro",
        "carhartt": "🧥 Carhartt",
    }
    cat_label = CAT_LABEL.get(search["category"], "🛍")

    # ── Typ alertu ──
    if disc >= 60:
        alert = f"🚨 MEGA OKAZJA  •  -{disc:.0f}% taniej"
    elif disc >= 40:
        alert = f"🔥 OKAZJA  •  -{disc:.0f}% taniej"
    elif item.get("has_typo"):
        alert = f"🔤 Błędna pisownia → {(item.get('typo_brand') or '').upper()}"
    elif item.get("is_hidden_gem"):
        alert = "💎 Hidden Gem"
    elif search.get("lego_sw_mode") and item.get("lego_sw_score", 0) >= 70:
        alert = "🚀 Kultowy set!"
    elif search.get("football_mode"):
        alert = "⚽ Oryginał retro"
    elif search.get("carhartt_mode"):
        model = (item.get("carhartt_model") or "").replace("_", " ").title()
        alert = f"🧥 Carhartt {model}".strip()
    else:
        alert = "💸 Niska cena"

    # ── Tytuł oferty — usuń "marka: X, stan: Y, rozmiar: Z" ──
    clean_title = re.sub(r',?\s*(marka|stan|rozmiar):.*', '', title, flags=re.IGNORECASE).strip()
    if not clean_title:
        clean_title = title[:80]

    # ── Składaj wiadomość ──
    lines = [
        f"{'─'*30}",
        f"{alert}",
        f"{cat_label}",
        f"{'─'*30}",
        f"",
        f"📦  {clean_title}",
        f"",
        f"💰  Cena:       {price:.0f} zł",
    ]

    if mp and mp > price:
        lines.append(f"📊  Śr. rynkowa: {mp:.0f} zł")
        lines.append(f"✂️   Oszczędzasz: ~{mp - price:.0f} zł")

    # LEGO SW szczegóły
    if search.get("lego_sw_mode"):
        info = item.get("lego_set_info", {})
        if info.get("set_number"):
            lines.append(f"🔢  Set:         #{info['set_number']}")
        if info.get("vehicle"):
            lines.append(f"🚀  Pojazd:      {info['vehicle']}")
        if info.get("character"):
            lines.append(f"👤  Postać:      {info['character']}")
        if info.get("minifigs"):
            lines.append(f"🟡  Minifigurki: tak")
        bl = info.get("bl_price_pln")
        if bl and bl > price:
            lines.append(f"🧱  BrickLink:   ~{bl:.0f} zł")
            lines.append(f"💚  vs BL:       ~{bl - price:.0f} zł taniej")

    return "\n".join(lines)


# ─────────────────────────────────────────
#  🚀 GŁÓWNA PĘTLA
# ─────────────────────────────────────────
print("✅ BOT HIDDEN GEM FINDER URUCHOMIONY")

load_bricklink_cache()
refresh_session()

send_message(
    "━━━━━━━━━━━━━━━━━━━━━━━\n"
    "🤖  VINTED BOT  •  ONLINE\n"
    "━━━━━━━━━━━━━━━━━━━━━━━\n"
    "\n"
    f"📡  Monitoruję {len(SEARCHES)} wyszukiwań\n"
    f"🎯  Próg okazji: -{MIN_DISCOUNT_PCT}% od mediany\n"
    "\n"
    "📦  Kategorie:\n"
    "    👟  Nike / Adidas\n"
    "    🧥  Carhartt (Trucker / Santa Fe / Detroit)\n"
    "    🧱  LEGO  •  ⭐ LEGO Star Wars\n"
    "    🎭  Funko Pop  •  🎭⭐ Funko Star Wars\n"
    "    ⚽  Koszulki Retro 70s – 2003\n"
    "    💎  Hidden Gem\n"
    "\n"
    "━━━━━━━━━━━━━━━━━━━━━━━"
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
            new_items, all_ids = check_search(search, seen, market_price)
            print(f"  ✔ Gotowe: {search['name']} — nowych: {len(new_items)}")

            now = time.time()
            for item in new_items[:MAX_ALERTS_PER_SEARCH]:
                msg = format_message(search, item)
                # Spróbuj pobrać zdjęcie przez API
                photo = item.get("photo")
                if not photo:
                    photo = get_item_photo(item["id"], item["link"])
                send_message(msg, photo_url=photo, item_link=item.get("link"))
                seen[item["id"]] = now
                tag = "💎" if item.get("is_hidden_gem") else ("🔤" if item.get("has_typo") else "✉️")
                print(f"  {tag} {item['title'][:55]} | {item['price']:.0f} zł")

            for item in new_items[:MAX_ALERTS_PER_SEARCH]:
                msg = format_message(search, item)
                send_message(msg, photo_url=item.get("photo"), item_link=item.get("link"))
                seen[item["id"]] = now
                tag = "💎" if item["is_hidden_gem"] else ("🔤" if item["has_typo"] else "✉️")
                print(f"  {tag} {item['title'][:55]} | {item['price']:.0f} zł")

        save_seen(seen)
        time.sleep(60)

    except Exception as e:
        print(f"Błąd głównej pętli: {e}")
        time.sleep(15)
