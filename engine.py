"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🧠  VINTED BOT — INTELLIGENCE ENGINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Moduł rozszerzający bota o:
  1. Auto-budowanie bazy cen rynkowych
  2. AI scoring (Claude)
  3. Confidence scoring (DB + market + AI)
  4. Trend detection
  5. Flip score
  6. Fake risk detection
  7. Tiered alert system
  8. Self-learning z feedbacku

Użycie w bot.py:
    from engine import Engine
    engine = Engine(anthropic_key=ANTHROPIC_KEY)

    # W pętli check_search, po podstawowych filtrach:
    result = engine.evaluate(item, search, market_price)
    if result["send_alert"]:
        msg = engine.format_alert(result)
        send_message(msg, ...)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import re
import json
import os
import time
import requests
from statistics import mean, median, stdev
import statistics   # dla statistics.median w add_sample
from collections import defaultdict


# ─────────────────────────────────────────────────────
#  📁 PLIKI — /tmp przeżywa restarty na Railway
# ─────────────────────────────────────────────────────
_DATA_DIR = os.getenv("DATA_DIR", "/tmp/vinted_bot")
os.makedirs(_DATA_DIR, exist_ok=True)

DB_FILE          = os.path.join(_DATA_DIR, "market_db.json")
RAW_FILE         = os.path.join(_DATA_DIR, "raw_items.json")
FEEDBACK_FILE    = os.path.join(_DATA_DIR, "feedback.json")
AI_CACHE_FILE    = os.path.join(_DATA_DIR, "ai_cache.json")

# ─────────────────────────────────────────────────────
#  ⚙️ PROGI
# ─────────────────────────────────────────────────────
CONFIDENCE_INSANE  = 8.5   # 🔴 INSANE DEAL
CONFIDENCE_GOOD    = 7.0   # 🟡 GOOD DEAL
CONFIDENCE_WATCH   = 5.5   # ⚪ WATCH — obniżone z 6.0 (więcej alertów)

DB_MIN_SAMPLES     = 5     # Part 2.7 — minimum próbek (podwyższone dla jakości)
DB_BUILD_EVERY     = 100   # buduj DB co N nowych itemów (częściej)
FLIP_MIN_PROFIT    = 20    # Part 2 — obniżone z 25 → 20 zł
FAKE_LUXURY_RATIO  = 0.35

# Part 2 — rolling window
DB_MAX_SAMPLES     = 50    # max próbek per klucz
DB_MAX_AGE_HOURS   = 48    # wyrzuć próbki starsze niż 48h

# Part 2.9 — vintage price premium
VINTAGE_PRICE_MULT = 1.2   # vintage rynek * 1.2

# Part 1 — debug mode
DEBUG_ALERTS       = True

LUXURY_BRANDS = {
    "gucci", "louis vuitton", "prada", "hermes", "balenciaga",
    "versace", "burberry", "fendi", "dior", "ysl", "saint laurent",
    "bottega veneta", "givenchy", "valentino", "off-white",
    "stone island", "cp company", "moncler", "canada goose",
}

HYPE_BRANDS = {
    "supreme", "palace", "stussy", "bape", "a bathing ape",
    "kaws", "travis scott", "yeezy", "jordan", "dunk",
    "nike sb", "sacai", "fragment", "fear of god", "essentials",
    "carhartt wip", "dickies", "wtaps",
    # FIX: Funko jako hype brand (kolekcjonerski)
    "funko", "funko pop",
    # Step 1 — nowe hype brandy flip engine
    "corteiz", "crtz", "broken planet", "denim tears",
    "represent", "arcteryx", "arc'teryx",
    "salomon",  # hype footwear
}

MAINSTREAM_BRANDS = {
    "nike", "adidas", "puma", "reebok", "new balance",
    "vans", "converse", "asics", "carhartt", "levi",
    "lego", "funko",
}

CATEGORY_MAP = {
    "sneakers": ["nike", "adidas", "jordan", "dunk", "yeezy", "samba", "air force",
                 "new balance", "vans", "converse", "asics", "reebok", "puma"],
    "streetwear": ["supreme", "palace", "stussy", "bape", "carhartt", "dickies"],
    "luxury": list(LUXURY_BRANDS),
    "lego": ["lego", "star wars", "technic", "ninjago", "creator"],
    "funko": ["funko", "pop!", "vinyl figure"],
    "football": ["koszulka", "jersey", "shirt", "football", "soccer"],
}

# FIX #5 — marki mainstream (Nike/Adidas ogólnie) — nie są w HYPE_BRANDS
# ale warto je traktować łagodniej w spam filter gdy brakuje danych DB
MAINSTREAM_BRANDS = {
    "nike", "adidas", "puma", "reebok", "new balance",
    "vans", "converse", "asics", "carhartt", "levi",
    "lego", "funko",
}

# ─────────────────────────────────────────────────────
#  🏷️ BRAND TIERS — Part 2
# ─────────────────────────────────────────────────────
PREMIUM_BRANDS = {
    "stone island", "cp company", "arc'teryx", "arcteryx",
    "patagonia", "salomon", "oakley", "nike acg", "helly hansen",
    "bape", "undercover", "number nine", "comme des garcons",
    "issey miyake", "yohji yamamoto", "raf simons",
}

VINTAGE_BRANDS = {
    "levis", "levi's", "levi strauss", "wrangler", "lee",
    "carhartt", "ll bean", "l.l. bean", "eddie bauer",
    "dickies", "ben davis", "key imperial", "pointer brand",
}

# Rozszerz HYPE_BRANDS o premium
HYPE_BRANDS.update(PREMIUM_BRANDS)

# ─────────────────────────────────────────────────────
#  🚫 PART 2 — FAKE MERCH FILTER
# ─────────────────────────────────────────────────────
FAKE_MERCH_BRANDS = {"alternative", "hm", "h&m", "zara", "bershka", "sinsay", "reserved"}
MERCH_KEYWORDS    = ["nirvana", "metallica", "harley", "band", "movie", "tour", "acdc", "ac/dc"]

# ─────────────────────────────────────────────────────
#  🎸 PART 3 — REAL VINTAGE SIGNALS (strict)
# ─────────────────────────────────────────────────────
REAL_VINTAGE_KEYWORDS = [
    "single stitch",
    "made in usa",
    "screen stars",
    "fruit of the loom",
    "hanes",
    "brockum",
    "liquid blue",
    "deadstock",
    "band tee",
    "tour tee",
    "concert tee",
    "rap tee",
    "nutmeg",
    "salem sportswear",
]

# ─────────────────────────────────────────────────────
#  ⚽ PART 4 — FOOTBALL QUALITY FILTERS
# ─────────────────────────────────────────────────────
BAD_FOOTBALL_KEYWORDS  = ["damska", "women", "crop", "baby", "kids", "dziecięca", "dziewczęca"]
GOOD_FOOTBALL_CLUBS    = ["barcelona", "arsenal", "milan", "real madrid", "chelsea", "manchester",
                           "juventus", "liverpool", "ajax", "dortmund", "psg", "atletico"]
GOOD_FOOTBALL_BRANDS   = {"nike", "adidas", "umbro", "kappa", "puma", "lotto", "diadora",
                           "hummel", "le coq sportif", "reebok", "score draw", "admiral"}

# ─────────────────────────────────────────────────────
#  🧱 PART 5 — LEGO FILTERS
# ─────────────────────────────────────────────────────
LEGO_MINIFIG_KEYWORDS = ["minifig", "figur", "figurk", "minifigurk"]

# ─────────────────────────────────────────────────────
#  🔤 NORMALIZACJA TYTUŁU
# ─────────────────────────────────────────────────────
_STOP_WORDS = {
    "marka", "stan", "rozmiar", "nowy", "nowa", "dobry", "dobra",
    "bardzo", "bez", "metki", "używany", "używana", "zł", "pln",
    "zawiera", "ochronę", "kupujących", "stan:", "rozmiar:",
    "the", "and", "for", "with", "de", "le", "la", "el",
}

# FIX #1 — dodatkowe słowa do usunięcia przed grupowaniem
_COLOR_WORDS = {
    "red", "black", "white", "blue", "green", "pink",
    "yellow", "grey", "gray", "navy", "beige", "brown",
    "orange", "purple", "cream", "czarny", "biały", "czerwony",
    "niebieski", "zielony", "szary", "granatowy",
}

_NOISE_WORDS = {
    "rare", "nowy", "new", "stan", "okazja", "sale",
    "polecam", "tanio", "super", "hit", "top", "ideał",
}


# ─────────────────────────────────────────────────────
#  🔧 HELPER FUNCTIONS
# ─────────────────────────────────────────────────────
def contains_keywords(text: str, keywords: list) -> bool:
    """True if any keyword from the list appears in the lowercased text."""
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def contains_year(text: str, year_from: int, year_to: int) -> bool:
    """True if any 4-digit year in range [year_from, year_to] appears in text."""
    years = re.findall(r'\b(1\d{3}|20\d{2})\b', text)
    for y in years:
        if year_from <= int(y) <= year_to:
            return True
    return False


def normalize_title(title: str) -> str:
    """
    Normalizuje tytuł do klucza grupowania.
    'Supreme Box Logo Hoodie FW18 Red XL' → 'supreme_box_logo'
    'LEGO Star Wars 75313'                → 'lego_75313'
    """
    t = title.lower()

    # FIX #1a — special item detection PRZED resztą przetwarzania
    if "box logo" in t or "bogo" in t:
        return "supreme_box_logo"

    # LEGO set number (4–6 cyfr)
    lego_match = re.search(r'\b(\d{4,6})\b', t) if "lego" in t else None
    if lego_match:
        return f"lego_{lego_match.group(1)}"

    # Nike Dunk
    if "dunk" in t:
        return "nike_dunk"

    # Usuń metadane Vinted
    t = re.sub(r',?\s*(marka|stan|rozmiar|brand|size|condition):.*', '', t)
    # Usuń rozmiary
    t = re.sub(r'\b(xs|s|m|l|xl|xxl|\d{2}/\d{2}|\d{2})\b', '', t)
    # Usuń lata i sezony
    t = re.sub(r'\b(fw|ss|aw|sp)\d{2,4}\b', '', t)
    # Usuń znaki specjalne i emoji
    t = re.sub(r'[^a-z0-9\s]', ' ', t)

    # Tokenizuj — usuń stop words + kolory + noise
    tokens = [
        w for w in t.split()
        if w not in _STOP_WORDS
        and w not in _COLOR_WORDS
        and w not in _NOISE_WORDS
        and len(w) > 2
    ]

    # FIX #1b — max 3–4 znaczące tokeny
    key = "_".join(tokens[:4])
    return key or "unknown"


def detect_category(title: str) -> str | None:
    """
    Fix #3 — Strict category detection.
    Returns None for unknown items → caller should block them from DB.
    """
    t = title.lower()

    # Strict item type detection per spec
    if any(k in t for k in ["t-shirt", "tshirt", "tee ", " tee", "band tee", "tour tee"]):
        return "tshirt"
    if any(k in t for k in ["hoodie", "hooded", "sweatshirt", "zip up", "crewneck"]):
        return "hoodie"
    if any(k in t for k in ["jacket", "kurtka", "bomber", "varsity", "windbreaker",
                              "anorak", "parka", "trucker", "chore coat", "work jacket"]):
        return "jacket"
    if any(k in t for k in ["coat", "płaszcz", "overcoat", "trench", "shearling", "kożuch"]):
        return "coat"
    if any(k in t for k in ["jeans", "denim", "dżinsy", "spodnie jeansowe"]):
        return "jeans"
    if any(k in t for k in ["cargo", "cargo pants", "cargo pant"]):
        return "cargo"
    if any(k in t for k in ["shirt", "koszula", "flannel", "oxford shirt"]):
        return "shirt"
    if any(k in t for k in ["sneakers", "shoes", "buty", "trainers", "kicks"]):
        return "sneakers"
    if any(k in t for k in ["jersey", "football shirt", "koszulka piłkarska"]):
        return "jersey"
    if any(k in t for k in ["cap", "hat", "czapka", "beanie", "snapback"]):
        return "cap"
    if any(k in t for k in ["bag", "backpack", "plecak", "torba"]):
        return "bag"

    # Fix #3 — BLOCK: zwróć None dla nierozpoznanych kategorii
    return None


def detect_brand(title: str) -> str | None:
    t = title.lower()
    ALL_KNOWN_BRANDS = sorted([
        *list(LUXURY_BRANDS),
        *list(HYPE_BRANDS),
        "nike", "adidas", "puma", "reebok", "lego", "funko",
        "new balance", "vans", "converse", "asics", "fila",
        "champion", "levi", "levis", "levi's", "wrangler",
        "lee ", "lee cooper", "dickies", "carhartt",
        "ralph lauren", "polo", "lacoste", "fred perry",
        "kappa", "umbro", "lotto", "diadora", "hummel",
        "le coq sportif", "ellesse", "sergio tacchini",
        "tommy hilfiger", "calvin klein", "guess",
        "columbia", "patagonia", "arc'teryx", "arcteryx",
        "the north face", "tnf", "salomon",
        "timberland", "dr martens", "birkenstock",
        "harley davidson", "harley",
        "starter", "russell athletic", "fruit of the loom",
        "hanes", "gildan", "screen stars", "delta",
    ], key=len, reverse=True)

    # FIX #5 — word boundary check: "palace" nie matchuje "monkey palace"
    # Marki które wymagają sprawdzenia jako osobne słowo (krótkie / mylące)
    WORD_BOUNDARY_BRANDS = {
        "palace", "polo", "delta", "guess", "lee ",
        "only ", "boss ", "george ", "rainbow ",
    }

    for brand in ALL_KNOWN_BRANDS:
        if brand not in t:
            continue
        if brand in WORD_BOUNDARY_BRANDS:
            # Sprawdź czy brand jest osobnym słowem (nie częścią innego)
            pattern = r'(?<![a-z])' + re.escape(brand.strip()) + r'(?![a-z])'
            if not re.search(pattern, t):
                continue
            # Dodatkowy kontekst: "monkey palace" → odrzuć
            # Szukaj czy brand jest modyfikowany przez rzeczownik przed nim
            idx = t.find(brand.strip())
            if idx > 0:
                before = t[max(0, idx-8):idx].strip()
                # Jeśli przed "palace" jest słowo które nie jest brand-related → skip
                non_brand_prefixes = ["monkey", "crystal", "ice", "winter", "summer",
                                      "beauty", "royal", "grand", "gra ", "planszow"]
                if any(p in before for p in non_brand_prefixes):
                    continue
        if brand in t:
            return brand.strip()
    return None


# ─────────────────────────────────────────────────────
#  💾 RAW ITEMS — surowe dane do budowania DB
# ─────────────────────────────────────────────────────
class RawStorage:
    def __init__(self):
        self.items: list[dict] = []
        self._load()

    def _load(self):
        try:
            if os.path.exists(RAW_FILE):
                with open(RAW_FILE) as f:
                    self.items = json.load(f)
        except:
            self.items = []

    def add(self, title: str, price: float, category: str):
        self.items.append({
            "title": title,
            "price": price,
            "category": category,
            "ts": time.time(),
        })
        # Trzymaj max 5000 ostatnich
        if len(self.items) > 5000:
            self.items = self.items[-5000:]

    def save(self):
        try:
            with open(RAW_FILE, "w") as f:
                json.dump(self.items, f)
        except:
            pass

    def count_new_since(self, ts: float) -> int:
        return sum(1 for i in self.items if i["ts"] > ts)


# ─────────────────────────────────────────────────────
#  🧱 MARKET DATABASE
# ─────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────
#  🧱 MARKET DATABASE — High-Quality Smart DB
# ─────────────────────────────────────────────────────

# Part 2.3 — vintage detection
_VINTAGE_DETECT_KW = [
    "vintage", "90s", "80s", "70s", "y2k", "single stitch",
    "made in usa", "made in italy", "retro", "old", "archive",
    "deadstock", "band tee", "tour shirt", "rap tee",
]

def _is_vintage(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in _VINTAGE_DETECT_KW)


# Part 2.2 — item type detection for smart key
_ITEM_TYPES = [
    ("hoodie",   ["hoodie", "bluza", "sweatshirt", "hooded"]),
    ("tee",      ["t-shirt", "tshirt", "tee", "koszulka", "t shirt"]),
    ("jacket",   ["jacket", "kurtka", "windbreaker", "bomber", "anorak", "parka"]),
    ("coat",     ["coat", "płaszcz", "overcoat", "trench"]),
    ("jeans",    ["jeans", "denim", "dżinsy"]),
    ("cargo",    ["cargo", "parachute pants"]),
    ("shirt",    ["shirt", "koszula", "flannel"]),
    ("sneakers", ["sneakers", "buty", "shoes", "kicks", "trainers"]),
    ("jersey",   ["jersey", "football shirt", "koszulka piłkarska"]),
    ("cap",      ["cap", "hat", "czapka", "beanie"]),
    ("bag",      ["bag", "torba", "backpack", "plecak"]),
]

def _detect_item_type(title: str) -> str:
    t = title.lower()
    for item_type, keywords in _ITEM_TYPES:
        if any(k in t for k in keywords):
            return item_type
    return "clothing"


def build_market_key(title: str, brand: str | None, is_vint: bool) -> str | None:
    """
    Fix #2 — Strict key system.
    HARD RULE: if not brand → return None → DO NOT store in DB.

    Examples:
      nike_tshirt_modern
      harley_tshirt_vintage
      stussy_jacket_modern
    """
    # Fix #2 — brak brandu = nie przechowuj
    if not brand:
        return None

    item_type = _detect_item_type(title)
    era       = "vintage" if is_vint else "modern"
    # Normalizuj brand (usuń spacje i znaki specjalne)
    brand_key = re.sub(r"[^a-z0-9]", "", brand.lower())
    return f"{brand_key}_{item_type}_{era}"


def should_add_to_db(item: dict, item_score: int) -> bool:
    """
    Fix #2 — Strict quality gate.
    HARD RULES:
    - brand required (no brand = do not store)
    - category must be known (not None)
    - min price 30 zł
    """
    price    = item.get("price", 0) or 0
    title    = item.get("title", "")
    brand    = detect_brand(title)
    category = detect_category(title)

    # Fix #2 — HARD: brak brandu → nie przechowuj
    if not brand:
        return False

    # Fix #3 — HARD: nieznana kategoria → nie przechowuj
    if not category:
        return False

    # Minimalna cena
    if price < 30:
        return False

    return True


class MarketDB:
    def __init__(self):
        self.db: dict[str, dict] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE) as f:
                    self.db = json.load(f)
                print(f"  📦 MarketDB: {len(self.db)} grup")
        except:
            self.db = {}

    def save(self):
        try:
            with open(DB_FILE, "w") as f:
                json.dump(self.db, f, indent=2)
        except:
            pass

    def build(self, raw_items: list[dict]):
        """
        Part 2 — High-Quality DB build.
        - Smart keys (brand+type+era)
        - Quality gate (should_add_to_db)
        - Rolling window (48h, max 50 samples)
        - Outlier filter (median ±50%)
        - Vintage premium (+20%)
        """
        now = time.time()
        max_age = DB_MAX_AGE_HOURS * 3600

        # Grupowanie po smart key
        groups:  dict[str, list[dict]] = defaultdict(list)

        for item in raw_items:
            title   = item.get("title", "")
            price   = item.get("price", 0) or 0
            brand   = detect_brand(title)
            is_vint = _is_vintage(title)
            score   = item.get("item_score", 0)

            # Part 2.1 — quality gate
            if not should_add_to_db(item, score):
                continue

            key = build_market_key(title, brand, is_vint)
            groups[key].append({
                "price":     price,
                "ts":        item.get("ts", now),
                "is_vintage": is_vint,
            })

        new_db = {}
        for key, samples in groups.items():
            # Part 2.5 — rolling window: wyrzuć stare próbki
            samples = [s for s in samples if now - s["ts"] < max_age]

            # Part 2.5 — max samples
            if len(samples) > DB_MAX_SAMPLES:
                samples = sorted(samples, key=lambda x: x["ts"])[-DB_MAX_SAMPLES:]

            if len(samples) < DB_MIN_SAMPLES:
                continue

            prices = [s["price"] for s in samples]

            # Part 2.6 — outlier filter (median-based)
            prices = self._clean_prices(prices)
            if len(prices) < DB_MIN_SAMPLES:
                continue

            # Part 2.8 — robust price calculation
            med   = median(prices)
            p25   = sorted(prices)[len(prices) // 4]
            p75   = sorted(prices)[(len(prices) * 3) // 4]
            avg_p = mean(prices)

            # Part 2.9 — vintage premium
            is_vint_key = "vintage" in key
            market_price = med * VINTAGE_PRICE_MULT if is_vint_key else med

            # Trend detection
            history = sorted(samples, key=lambda x: x["ts"])
            trend   = self._detect_trend([{"price": s["price"], "ts": s["ts"]} for s in history])

            new_entry = {
                "avg":          round(avg_p, 2),
                "median":       round(med, 2),
                "market_price": round(market_price, 2),  # Part 2.9
                "p25":          round(p25, 2),
                "p75":          round(p75, 2),
                "min":          round(min(prices), 2),
                "max":          round(max(prices), 2),
                "std":          round(stdev(prices) if len(prices) > 1 else 0, 2),
                "count":        len(prices),
                "trend":        trend,
                "is_vintage":   is_vint_key,
                "updated":      now,
            }

            # Merge z istniejącą bazą
            if key in self.db:
                old = self.db[key]
                old_n = old.get("count", 0)
                new_n = new_entry["count"]
                total = old_n + new_n
                if total > 0:
                    new_entry["avg"] = round(
                        (old["avg"] * old_n + new_entry["avg"] * new_n) / total, 2
                    )
                    new_entry["count"] = total
                    new_entry["min"] = min(old.get("min", new_entry["min"]), new_entry["min"])
                    new_entry["max"] = max(old.get("max", new_entry["max"]), new_entry["max"])

            new_db[key] = new_entry

        # Zachowaj historyczne wpisy
        for key, data in self.db.items():
            if key not in new_db:
                new_db[key] = data

        self.db = new_db
        self.save()
        vint_keys = sum(1 for k in new_db if "vintage" in k)
        print(f"  📊 MarketDB: {len(new_db)} grup ({vint_keys} vintage)")
        return new_db

    MAX_SAMPLES    = 50
    MAX_AGE_HOURS  = 48

    def add_sample(self, key: str | None, price: float):
        """
        Fix #2 — strict: jeśli key=None (brak brandu) → nie dodawaj.
        """
        if not key:
            return  # Fix #2 — HARD: brak klucza = brak brandu = nie przechowuj
        now = time.time()
        if key not in self.db:
            self.db[key] = {
                "avg": price, "median": price, "market_price": price,
                "p25": price, "p75": price, "min": price, "max": price,
                "std": 0, "count": 1, "trend": "stable",
                "is_vintage": "vintage" in key,
                "updated": now,
                "_samples": [],
            }

        entry = self.db[key]
        samples = entry.get("_samples", [])

        # Dodaj nową próbkę
        samples.append({"price": price, "ts": now})

        # Rolling window — usuń stare
        samples = [
            s for s in samples
            if now - s["ts"] < self.MAX_AGE_HOURS * 3600
        ]

        # Cap size
        samples = samples[-self.MAX_SAMPLES:]

        prices = sorted(s["price"] for s in samples)
        n      = len(prices)

        if n >= 2:
            med   = statistics.median(prices)
            low_p = prices[int(n * 0.25)]
            hi_p  = prices[int(n * 0.75)]
            is_vk = "vintage" in key
            entry.update({
                "avg":          round(sum(prices) / n, 2),
                "median":       round(med, 2),
                "market_price": round(med * (VINTAGE_PRICE_MULT if is_vk else 1.0), 2),
                "p25":          round(low_p, 2),
                "p75":          round(hi_p, 2),
                "min":          round(prices[0], 2),
                "max":          round(prices[-1], 2),
                "count":        n,
                "updated":      now,
            })

        entry["_samples"] = samples
        self.db[key] = entry


        """Part 2.6 — usuwa outlier'y względem mediany (±50%)."""
        if len(prices) < 3:
            return prices
        med = median(prices)
        lo  = med * 0.5
        hi  = med * 1.5
        cleaned = [p for p in prices if lo < p < hi]
        return cleaned if len(cleaned) >= 2 else prices

    def _filter_outliers(self, prices: list[float]) -> list[float]:
        """IQR fallback (używany gdzie nie ma median-based)."""
        return self._clean_prices(prices)

    def _detect_trend(self, history: list[dict]) -> str:
        if len(history) < 4:
            return "stable"
        prices = [h["price"] for h in history[-6:]]
        mid = len(prices) // 2
        avg_old = mean(prices[:mid])
        avg_new = mean(prices[mid:])
        if avg_new > avg_old * 1.15:
            return "rising"
        if avg_new < avg_old * 0.85:
            return "falling"
        return "stable"

    def lookup(self, title: str, brand: str | None = None, category: str | None = None) -> dict | None:
        """
        Fix #2 — szuka po strict key (brand+type+era).
        Jeśli brak brandu → smart_key=None → brak danych → zwróć None.
        """
        is_vint   = _is_vintage(title)
        smart_key = build_market_key(title, brand, is_vint)
        if smart_key and smart_key in self.db:
            return self.db[smart_key]
        # Fallback — stary klucz (kompatybilność wsteczna)
        old_key = normalize_title(title)
        if old_key in self.db:
            return self.db[old_key]
        # Fallback brand+category
        if brand and category:
            bc_key = f"{brand}_{category}"
            if bc_key in self.db:
                return self.db[bc_key]
        return None

    def lookup_by_brand_category(self, brand: str, category: str) -> dict | None:
        for key, data in self.db.items():
            if brand in key and data.get("count", 0) >= DB_MIN_SAMPLES:
                return data
        return None


# ─────────────────────────────────────────────────────
#  🤖 AI CACHE
# ─────────────────────────────────────────────────────
class AICache:
    def __init__(self):
        self.cache: dict[str, dict] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(AI_CACHE_FILE):
                with open(AI_CACHE_FILE) as f:
                    self.cache = json.load(f)
        except:
            self.cache = {}

    def save(self):
        try:
            with open(AI_CACHE_FILE, "w") as f:
                json.dump(self.cache, f)
        except:
            pass

    def get(self, title: str, price: float = 0) -> dict | None:
        # FIX #4 — klucz = pełny tytuł + cena (brak kolizji między różnymi itemami)
        key = f"{title.lower().strip()}_{round(price)}"
        entry = self.cache.get(key)
        if entry:
            # Cache ważny 24h
            if time.time() - entry.get("ts", 0) < 86400:
                return entry["data"]
        return None

    def set(self, title: str, data: dict, price: float = 0):
        # FIX #4 — spójny klucz z get()
        key = f"{title.lower().strip()}_{round(price)}"
        self.cache[key] = {"data": data, "ts": time.time()}
        # Trzymaj max 2000 wpisów
        if len(self.cache) > 2000:
            oldest = sorted(self.cache.items(), key=lambda x: x[1]["ts"])
            for k, _ in oldest[:200]:
                del self.cache[k]


# ─────────────────────────────────────────────────────
#  📈 SELF-LEARNING — feedback użytkownika
# ─────────────────────────────────────────────────────
class FeedbackLearner:
    def __init__(self):
        self.data: dict = {
            "brand_scores": {},
            "category_scores": {},
            "keyword_scores": {},
            "clicked": [],
            "bought": [],
        }
        self._load()

    def _load(self):
        try:
            if os.path.exists(FEEDBACK_FILE):
                with open(FEEDBACK_FILE) as f:
                    self.data = json.load(f)
        except:
            pass

    def save(self):
        try:
            with open(FEEDBACK_FILE, "w") as f:
                json.dump(self.data, f, indent=2)
        except:
            pass

    def record_click(self, item_id: str, brand: str, category: str):
        """Zwiększa score dla marki i kategorii po kliknięciu."""
        self.data["clicked"].append({"id": item_id, "ts": time.time()})
        self._boost(brand, category)
        self.save()

    def record_buy(self, item_id: str, brand: str, category: str):
        """Silniejszy boost po zakupie."""
        self.data["bought"].append({"id": item_id, "ts": time.time()})
        self._boost(brand, category, multiplier=2.0)
        self.save()

    def _boost(self, brand: str, category: str, multiplier: float = 1.0):
        if brand:
            self.data["brand_scores"][brand] = (
                self.data["brand_scores"].get(brand, 5.0) + 0.1 * multiplier
            )
        if category:
            self.data["category_scores"][category] = (
                self.data["category_scores"].get(category, 5.0) + 0.05 * multiplier
            )

    def get_brand_bonus(self, brand: str) -> float:
        """Zwraca bonus (0.0–1.0) dla marki na podstawie historii."""
        score = self.data["brand_scores"].get(brand, 5.0)
        return min((score - 5.0) / 10.0, 1.0)

    def get_category_bonus(self, category: str) -> float:
        score = self.data["category_scores"].get(category, 5.0)
        return min((score - 5.0) / 10.0, 1.0)


# ─────────────────────────────────────────────────────
#  🤖 AI ANALYZER (Claude)
# ─────────────────────────────────────────────────────
def _call_claude(prompt: str, anthropic_key: str) -> dict | None:
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        if r.status_code != 200:
            return None
        text = r.json()["content"][0]["text"].strip()
        text = re.sub(r"```json|```", "", text).strip()
        return json.loads(text)
    except:
        return None


def analyze_item_ai(
    title: str,
    description: str,
    price: float,
    db_data: dict | None,
    anthropic_key: str,
    ai_cache: AICache,
) -> dict:
    """
    Analizuje ofertę przez Claude.
    Zwraca:
    {
        brand, category, keywords,
        estimated_value, rarity (1-10), hype_score (1-10),
        underpriced (bool), final_score (0-10),
        decision: BUY / WATCH / SKIP
    }
    """
    # Sprawdź cache — FIX #4: klucz = tytuł + cena
    cached = ai_cache.get(title, price)
    if cached:
        return cached

    avg_str = f"{db_data['avg']:.0f} zł (z {db_data['count']} ofert)" if db_data else "brak danych"

    prompt = f"""Jesteś ekspertem od wyceny używanych ubrań, butów, LEGO i Funko Pop.
Analizujesz ofertę z Vinted i oceniasz czy warto kupić.

Tytuł: {title[:200]}
Opis: {description[:300] if description else 'brak'}
Cena: {price:.0f} zł
Średnia rynkowa (nasza baza): {avg_str}

Odpowiedz TYLKO w JSON (bez backtick, bez wyjaśnień):
{{
  "brand": "nazwa marki lub null",
  "category": "sneakers/streetwear/luxury/lego/funko/football/other",
  "keywords": ["max 3 słowa kluczowe"],
  "estimated_value": liczba_PLN,
  "rarity": 1-10,
  "hype_score": 1-10,
  "underpriced": true/false,
  "final_score": 0-10,
  "decision": "BUY/WATCH/SKIP"
}}

Zasady oceny:
- decision BUY: cena < 60% wartości rynkowej LUB rzadki item LUB hype > 7
- decision WATCH: cena < 80% wartości LUB interesujący item
- decision SKIP: normalna cena lub brak potencjału
- estimated_value: realna wartość rynkowa w PLN (sprawdź czy pasuje do polskiego rynku)
- rarity: 1=pospolite, 10=rzadkie kolekcjonerskie
- hype_score: 1=nikt nie chce, 10=wszyscy szukają"""

    result = _call_claude(prompt, anthropic_key)

    if not result:
        result = {
            "brand": detect_brand(title),
            "category": detect_category(title),
            "keywords": [],
            "estimated_value": db_data["avg"] if db_data else price * 1.5,
            "rarity": 3,
            "hype_score": 3,
            "underpriced": price < (db_data["avg"] * 0.7 if db_data else price),
            "final_score": 5.0,
            "decision": "WATCH",
        }

    ai_cache.set(title, result, price)
    return result


# ─────────────────────────────────────────────────────
#  🧮 CONFIDENCE SCORING
# ─────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────
#  🎸 VINTAGE SCORING — Step 2
# ─────────────────────────────────────────────────────
VINTAGE_KEYWORDS = [
    "vintage", "single stitch", "90s", "80s", "70s", "y2k",
    "retro", "deadstock", "made in usa", "made in usa",
    "distressed", "faded", "worn", "aged",
]

HIGH_VALUE_TOPICS = [
    # Muzyka
    "metallica", "nirvana", "tour", "band tee", "band shirt",
    "ac/dc", "rolling stones", "led zeppelin", "pink floyd",
    "rap tee", "rap shirt", "wu-tang", "wu tang", "tupac",
    "biggie", "eminem", "jay-z", "nas", "travis scott",
    # Pop culture
    "disney", "mickey", "mickey mouse", "looney tunes",
    "harley", "harley davidson", "nascar",
    "starter", "champion", "russell athletic",
    # Gaming
    "pokemon", "pikachu", "zelda", "mario", "nintendo",
    "anime", "dragon ball", "naruto", "playstation",
    # Inne tematyki vintage premium
    "usa olympic", "olympics", "world cup", "superbowl",
    "college", "university", "varsity",
]


def vintage_score(title: str, description: str | None = None) -> float:
    """
    Oblicza score vintage (0–10) na podstawie tytułu i opisu.
    Step 2 z flipengine spec.
    """
    t = (title + " " + (description or "")).lower()
    score = 0.0

    if any(k in t for k in VINTAGE_KEYWORDS):
        score += 2.0

    if any(k in t for k in HIGH_VALUE_TOPICS):
        score += 3.0

    if "tour" in t:
        score += 1.5

    if "single stitch" in t:
        score += 1.0

    # Zwykły t-shirt bez "vintage" — mała szansa na gem
    if ("t shirt" in t or "tshirt" in t or "tee" in t) and "vintage" not in t:
        score += 0.5

    return min(score, 10.0)


# ─────────────────────────────────────────────────────
#  ⚽ FOOTBALL VINTAGE SCORING — Step 3
# ─────────────────────────────────────────────────────
ERA_KEYWORDS = [
    "90s", "80s", "70s", "2000", "2001", "2002", "2003",
    "1998", "1996", "1994", "1992", "1990", "1988",
    "1986", "1984", "1982", "1980", "1970",
    "98", "96", "94", "92", "90", "88", "86",
]


def football_vintage_score(title: str) -> float:
    """
    Oblicza score koszulki vintage (0–10).
    Step 3 z flipengine spec.
    """
    t = title.lower()
    score = 0.0

    if "football" in t or "jersey" in t or "shirt" in t or "koszulka" in t:
        score += 1.0

    if any(k in t for k in ["vintage", "retro", "classic", "old", "original"]):
        score += 2.0

    if any(k in t for k in ["umbro", "kappa", "lotto", "diadora",
                              "hummel", "le coq sportif", "admiral", "bukta"]):
        score += 2.0

    if any(k in t for k in ERA_KEYWORDS):
        score += 1.5

    # Bonus za znane turnieje
    if any(k in t for k in ["world cup", "euro", "champions league",
                              "copa", "mundial", "mistrzostwa"]):
        score += 1.0

    return min(score, 10.0)


def calculate_confidence(
    price: float,
    db_data: dict | None,
    ai_data: dict,
    market_price: float | None,
    brand: str | None,
    category: str,
    learner: FeedbackLearner,
    title: str = "",
    description: str = "",
) -> dict:
    """
    Oblicza confidence score (0–10).
    Steps 4/5/7/8: vintage boost, football boost, flip boost,
                   chaos bonus, anti-spam, fake filter.
    """

    # ── DB SCORE (0–10) ──────────────────────
    db_score = 5.0
    flip_profit = 0.0
    fake_risk = False
    trend = "stable"

    if db_data:
        avg   = db_data["avg"]
        db_mkt = db_data.get("market_price", avg)
        p25   = db_data.get("p25", db_mkt * 0.75)
        ratio = price / db_mkt if db_mkt > 0 else 1.0
        trend = db_data.get("trend", "stable")

        # Part 5 — negotiation factor: cena po negocjacji -15%
        effective_price = price * 0.85
        effective_ratio = effective_price / db_mkt if db_mkt > 0 else 1.0

        # Użyj effective_ratio do oceny (uwzględnia potencjalne negocjacje)
        scoring_ratio = min(ratio, effective_ratio + 0.05)  # blend raw i effective

        if scoring_ratio < 0.50:
            db_score = 10.0
        elif scoring_ratio < 0.60:
            db_score = 9.0
        elif scoring_ratio < 0.70:
            db_score = 8.0
        elif scoring_ratio < 0.80:
            db_score = 6.5
        elif scoring_ratio < 0.90:
            db_score = 5.0
        else:
            db_score = 3.0

        if brand in LUXURY_BRANDS and ratio < FAKE_LUXURY_RATIO:
            fake_risk = True
            db_score = max(db_score - 2.0, 0.0)

        if brand in LUXURY_BRANDS and ratio < 0.30:
            fake_risk = True
            db_score = max(db_score - 3.0, 0.0)

        estimated   = ai_data.get("estimated_value", db_mkt)
        flip_profit = max(estimated - price, 0.0)

        # Part 2.10 — deal_score
        deal_score = (db_mkt - price) / db_mkt if db_mkt > 0 else 0.0
        if deal_score > 0.5:
            deal_tag = "STEAL"
        elif deal_score > 0.3:
            deal_tag = "GOOD"
        else:
            deal_tag = "WEAK"

        # Part 2.11 — anomaly detection
        anomaly_score = 0
        if price < db_mkt * 0.6:
            anomaly_score += 2

        if trend == "rising":
            db_score = min(db_score + 0.5, 10.0)
        elif trend == "falling":
            db_score = max(db_score - 0.5, 0.0)
    else:
        db_mkt        = None
        p25           = None
        effective_price = price * 0.85
        estimated     = ai_data.get("estimated_value", price * 1.5)
        flip_profit   = max(estimated - price, 0.0)
        deal_score    = 0.0
        deal_tag      = "WEAK"
        anomaly_score = 0

    # ── MARKET SCORE (0–10) ──────────────────
    market_score = 5.0
    if market_price and market_price > 0:
        if market_price < 20:
            market_score = 5.0
        else:
            ratio_m = price / market_price
            if ratio_m < 0.50:
                market_score = 10.0
            elif ratio_m < 0.60:
                market_score = 9.0
            elif ratio_m < 0.70:
                market_score = 8.0
            elif ratio_m < 0.80:
                market_score = 6.5
            elif ratio_m < 0.90:
                market_score = 5.0
            else:
                market_score = 3.0

    # ── AI SCORE (0–10) ──────────────────────
    ai_score = float(ai_data.get("final_score", 5.0))
    hype = ai_data.get("hype_score", 3)
    if hype >= 8:
        ai_score = min(ai_score + 1.0, 10.0)
    elif hype >= 6:
        ai_score = min(ai_score + 0.5, 10.0)

    rarity = ai_data.get("rarity", 3)
    if rarity >= 8:
        ai_score = min(ai_score + 1.0, 10.0)

    if flip_profit > FLIP_MIN_PROFIT:
        boost = min(flip_profit / 100.0, 1.5)
        ai_score = min(ai_score + boost, 10.0)

    # ── WEIGHTED CONFIDENCE ───────────────────
    confidence = (
        db_score     * 0.40 +
        market_score * 0.30 +
        ai_score     * 0.30
    )

    # ── STEP 4: VINTAGE BOOST ─────────────────
    v_score = vintage_score(title, description)
    if v_score >= 8:
        confidence += 2.0
    elif v_score >= 6:
        confidence += 1.0

    # ── STEP 4: FOOTBALL VINTAGE BOOST ────────
    f_score = football_vintage_score(title) if category == "football" else 0.0
    if f_score >= 6 and price < 100:
        confidence += 2.0
    elif f_score >= 5 and price < 150:
        confidence += 1.5

    # ── STEP 4: FLIP PROFIT BOOST ─────────────
    if flip_profit > 300:
        confidence += 2.0
    elif flip_profit > 150:
        confidence += 1.0

    # ── STEP 4: HYPE + UNDERPRICED BOOST ──────
    estimated_val = ai_data.get("estimated_value", price * 1.5)
    if hype >= 8 and estimated_val > 0 and price < estimated_val * 0.70:
        confidence += 1.0

    # Fix #7 — CLEAN CONFIDENCE gdy brak danych DB (nie pozwól na fake conf=9.8)
    # Structured scoring per spec zamiast chaotycznych boostów
    if not db_data:
        structured_conf = 0.0
        if brand:
            structured_conf += 3.0
        item_cat = detect_category(title)
        if item_cat:
            structured_conf += 2.0
        if flip_profit > 50:
            structured_conf += 2.0
        elif flip_profit > 30:
            structured_conf += 1.0
        # grail check — użyj v_score jako proxy
        if v_score >= 6:
            structured_conf += 2.0
        # trash penalty
        _trash_in_title = any(x in title.lower() for x in [
            "top,", "top z", "blouse", "dress", "cute", "coquette",
            "sukienka", "bluzka", "kombinezon", "crop top",
        ])
        if _trash_in_title:
            structured_conf -= 4.0
        # Użyj structured_conf zamiast chaotycznego weighted average
        confidence = max(0.0, min(structured_conf, 10.0))

    # Fix #7 — clamp 0–10
    confidence = max(0.0, min(confidence, 10.0))

    # ── STEP 5: ANTI-SPAM PENALTIES ───────────
    t_lower = title.lower()
    if any(b in t_lower for b in ["shein", "zara", "h&m", "hm "]):
        confidence -= 2.0
    if price < 20:
        confidence -= 1.0

    # ── STEP 7: CHAOS BONUS ───────────────────
    if brand is None:
        if price < 100:
            confidence += 0.5
        if ai_score < 6:
            confidence -= 1.0

    # ── STEP 8: FAKE FILTER ───────────────────
    if any(k in t_lower for k in ["replica", "replika", "fake", "kopia",
                                    "podróbka", "bootleg", "inspired"]):
        fake_risk = True
        confidence -= 3.0

    # ── PART 2.11: ANOMALY BOOST ─────────────
    # Fix #5 — anomaly boost tylko gdy mamy brand lub prawdziwe vintage keyword
    # (zapobiega conf=10 na śmieciowych "y2k streetwear" bez brandu)
    _has_real_signal = (
        brand is not None or
        any(k in title.lower() for k in [
            "single stitch", "made in usa", "made in italy",
            "deadstock", "band tee", "tour shirt", "harley davidson",
            "screen stars", "hanes", "gildan", "fruit of the loom",
        ])
    )
    if anomaly_score >= 2 and _has_real_signal:
        confidence += 1.5
    elif anomaly_score >= 2:
        confidence += 0.5  # słaby boost bez sygnału jakości

    # ── SELF-LEARNING BONUS ───────────────────
    if brand:
        confidence += learner.get_brand_bonus(brand) * 0.3
    confidence += learner.get_category_bonus(category) * 0.2

    # ── CLAMP 0–10 ────────────────────────────
    confidence = max(0.0, min(confidence, 10.0))

    return {
        "confidence":      round(confidence, 2),
        "db_score":        round(db_score, 2),
        "market_score":    round(market_score, 2),
        "ai_score":        round(ai_score, 2),
        "fake_risk":       fake_risk,
        "flip_profit":     round(flip_profit, 2),
        "trend":           trend,
        "vintage_score":   round(v_score, 2),
        "football_score":  round(f_score, 2),
        "deal_score":      round(deal_score, 4),
        "deal_tag":        deal_tag,
        "anomaly_score":   anomaly_score,
        "effective_price": round(effective_price, 2),           # Part 5
        "p25":             round(p25, 2) if p25 else None,      # Part 5
        "market_price_db": round(db_mkt, 2) if db_mkt else None,
    }


# ─────────────────────────────────────────────────────
#  💎 GRAIL DETECTION — Part 3
# ─────────────────────────────────────────────────────
GRAIL_KEYWORDS = [
    "single stitch", "made in usa", "made in italy",
    "90s", "80s", "70s", "tour", "promo",
    "band", "band tee", "movie", "film",
    "harley davidson", "grateful dead", "nirvana", "metallica",
    "rap tee", "bootleg tee", "concert tee", "concert shirt",
]

# Fix #4 — REAL grail keywords (strict subset — nie "vintage" alone)
REAL_GRAIL_KEYWORDS = [
    "single stitch",
    "made in usa",
    "90s",
    "80s",
    "tour",
    "promo",
    "band",
    "movie",
    "harley davidson",
    "deadstock",
    "rap tee",
    "concert tee",
    "bootleg",
]

GRAIL_BRANDS = [
    "screen stars", "hanes", "fruit of the loom", "delta pro weight",
    "delta", "gildan", "brockum", "liquid blue", "nutmeg",
    "anvil", "tultex", "jerzees", "artex", "signal sport",
    "salem sportswear", "logo 7", "chalk line",
]


def grail_score(title: str, anomaly_sc: int, deal_tag: str) -> tuple[int, bool]:
    """
    Fix #4 — Strict grail scoring.
    Uses REAL_GRAIL_KEYWORDS only (not loose "vintage").
    is_grail requires score >= 3 (raised from 4 → stricter threshold).
    """
    t     = title.lower()
    score = 0

    # Grail brand (vintage basic tee brand)
    if any(b in t for b in GRAIL_BRANDS):
        score += 2

    # Fix #4 — tylko REAL_GRAIL_KEYWORDS (nie "vintage" alone)
    kw_hits = sum(1 for k in REAL_GRAIL_KEYWORDS if k in t)
    if kw_hits >= 1:
        score += 2
    if kw_hits >= 2:
        score += 1  # bonus za kombinację

    # Anomaly pricing
    if anomaly_sc >= 2:
        score += 2

    # Dodatkowe sygnały
    if "band" in t or "movie" in t or "film" in t:
        score += 1
    if "tour" in t:
        score += 1
    if "single stitch" in t:
        score += 1
    if deal_tag == "STEAL":
        score += 1

    # Fix #4 — STRICT: grail_score < 3 → is_grail = False
    is_grail = score >= 3
    return score, is_grail



def get_alert_tier(confidence: float, ai_decision: str) -> str | None:
    """
    INSANE: conf >= 8.5 (prawdziwe okazje)
    GOOD:   conf >= 7.0 LUB (BUY + conf >= 6.5)
    WATCH:  conf >= 6.0
    """
    if confidence >= CONFIDENCE_INSANE:
        return "INSANE"
    if confidence >= CONFIDENCE_GOOD:
        return "GOOD"
    if ai_decision == "BUY" and confidence >= 6.5:
        return "GOOD"
    if confidence >= CONFIDENCE_WATCH:
        return "WATCH"
    return None


# ─────────────────────────────────────────────────────
#  🏗️ GŁÓWNA KLASA ENGINE
# ─────────────────────────────────────────────────────
class Engine:
    """
    Główny silnik inteligencji bota.

    Użycie:
        engine = Engine(anthropic_key="sk-ant-...")
        result = engine.evaluate(item, search, market_price)
        if result["send_alert"]:
            msg = engine.format_alert(result)
    """

    def __init__(self, anthropic_key: str | None = None):
        self.anthropic_key  = anthropic_key
        self.db             = MarketDB()
        self.raw            = RawStorage()
        self.ai_cache       = AICache()
        self.learner        = FeedbackLearner()
        self._raw_count_at_last_build = len(self.raw.items)
        # FIX #2 — deduplicacja alertów: ten sam item_id nie dostanie
        # alertu dwa razy w tej samej sesji (np. gdy pojawia się w kilku wyszukiwaniach)
        self._alerted_ids: set[str] = set()
        print(f"🧠 Engine zainicjowany | DB: {len(self.db.db)} grup | AI: {'✅' if anthropic_key else '❌'}")

    # ── GŁÓWNA METODA ────────────────────────
    def evaluate(
        self,
        item: dict,
        search: dict,
        market_price: float | None,
        use_ai: bool = True,
    ) -> dict:
        """
        Ocenia ofertę i zwraca decyzję.

        item: dict z kluczami id, title, price, link, ...
        search: słownik wyszukiwania z bot.py
        market_price: mediana z Vinted dla tego wyszukiwania
        """
        title    = item.get("title", "")
        price    = item.get("price", 0) or 0
        category = detect_category(title)
        brand    = detect_brand(title)

        # 1. Dodaj do surowych danych
        self.raw.add(title, price, category)

        # 2. Sprawdź czy budować DB
        new_since = len(self.raw.items) - self._raw_count_at_last_build
        if new_since >= DB_BUILD_EVERY:
            self.db.build(self.raw.items)
            self.raw.save()
            self._raw_count_at_last_build = len(self.raw.items)

        # 3. Lookup w bazie + add_sample (Part 2 — on-the-fly DB update)
        is_vint   = _is_vintage(title)
        smart_key = build_market_key(title, brand, is_vint)  # None gdy brak brandu

        # Fix #2: add_sample jest None-safe — ignoruje key=None (brak brandu)
        if price and price >= 30:
            self.db.add_sample(smart_key, price)

        db_data = self.db.lookup(title, brand=brand, category=category)
        if not db_data and brand:
            db_data = self.db.lookup_by_brand_category(brand, category)

        # 4. AI analiza (z cache, tylko gdy potrzebna)
        ai_data = None
        if use_ai and self.anthropic_key:
            # Użyj AI gdy: brak danych DB, lub cena anomalia, lub luksus
            should_use_ai = (
                db_data is None or
                (db_data and price < db_data["avg"] * 0.65) or
                brand in LUXURY_BRANDS or
                brand in HYPE_BRANDS
            )
            if should_use_ai:
                ai_data = analyze_item_ai(
                    title=title,
                    description=item.get("description", ""),
                    price=price,
                    db_data=db_data,
                    anthropic_key=self.anthropic_key,
                    ai_cache=self.ai_cache,
                )
                self.ai_cache.save()

        # Fallback AI data (bez wywołania Claude)
        if not ai_data:
            ai_data = self._heuristic_ai(title, price, db_data, brand, category)

        # 5. Confidence score
        scoring = calculate_confidence(
            price=price,
            db_data=db_data,
            ai_data=ai_data,
            market_price=market_price,
            brand=brand,
            category=category,
            learner=self.learner,
            title=title,
            description=item.get("description", ""),
        )

        # ── FRESHNESS SYSTEM — 3-TIER ────────────────────────────
        _has_brand   = bool(brand)
        _has_vintage = _is_vintage(title)
        item_age_ts  = item.get("created_at_ts")
        # If no ts: treat as AGED tier (360 min) — keeps DB learning alive
        item_age_minutes = int((time.time() - item_age_ts) / 60) if item_age_ts else 360

        # ── Grail + undervalue needed before freshness gate ──────
        anomaly_sc   = scoring.get("anomaly_score", 0)
        deal_tag     = scoring.get("deal_tag", "WEAK")
        g_score, is_grail = grail_score(title, anomaly_sc, deal_tag)

        estimated_market_price = (
            scoring.get("market_price_db") or
            (db_data["avg"] if db_data else None) or
            ai_data.get("estimated_value")
        )
        if not estimated_market_price:
            if brand in PREMIUM_BRANDS:
                estimated_market_price = price * 1.6
            elif "vintage" in title.lower():
                estimated_market_price = price * 1.4
        undervalue_ratio  = (price / estimated_market_price) if estimated_market_price else 1.0
        strong_undervalue = undervalue_ratio < 0.6

        # ── PART 2 — DB learning always happens regardless of freshness ──
        if brand and category:
            smart_key_learn = build_market_key(title, brand, _is_vintage(title))
            if smart_key_learn and price >= 30:
                self.db.add_sample(smart_key_learn, price)

        # ── TIER ASSIGNMENT & CONFIDENCE BOOST ──────────────────
        confidence  = scoring["confidence"]
        flip_speed  = "MEDIUM"

        if item_age_minutes <= 10:
            # 🟢 TIER 1 — ULTRA FRESH
            freshness_tier = "ULTRA"
            confidence     = min(confidence + 3.0, 10.0)
            flip_speed     = "FAST"
        elif item_age_minutes <= 60:
            # 🟡 TIER 2 — FRESH
            freshness_tier = "FRESH"
            confidence     = min(confidence + 1.0, 10.0)
        elif item_age_minutes <= 360:
            # 🔵 TIER 3 — AGED (1–6 hours): only allow if grail or strong undervalue
            freshness_tier = "AGED"
            if not strong_undervalue and not is_grail:
                # Still let DB learn, then skip alert
                if DEBUG_ALERTS:
                    print(f"  ⏭  AGED skip (age={item_age_minutes}m, no undervalue/grail) | {title[:35]}")
                return {
                    "send_alert": False, "tier": None,
                    "confidence": confidence, "scoring": scoring,
                    "ai_data": ai_data, "db_data": db_data,
                    "brand": brand, "category": category,
                    "flip_profit": scoring.get("flip_profit", 0), "item": item,
                    "market_price": market_price, "is_grail": is_grail,
                    "grail_score": g_score, "deal_tag": deal_tag,
                    "flip_speed": "SLOW", "item_age_min": item_age_minutes,
                    "undervalue_ratio": round(undervalue_ratio, 3),
                    "_skip_reason": "aged_no_signal",
                    "freshness_tier": freshness_tier,
                }
        else:
            # ❌ HARD REJECT — older than 6 hours
            freshness_tier = "STALE"
            if DEBUG_ALERTS:
                print(f"  ❌ STALE reject (age={item_age_minutes}m) | {title[:35]}")
            return {
                "send_alert": False, "tier": None,
                "confidence": confidence, "scoring": scoring,
                "ai_data": ai_data, "db_data": db_data,
                "brand": brand, "category": category,
                "flip_profit": scoring.get("flip_profit", 0), "item": item,
                "market_price": market_price, "is_grail": False,
                "grail_score": g_score, "deal_tag": deal_tag,
                "flip_speed": "SLOW", "item_age_min": item_age_minutes,
                "undervalue_ratio": round(undervalue_ratio, 3),
                "_skip_reason": "stale",
                "freshness_tier": freshness_tier,
            }

        # PART 4 — Debug freshness log
        if DEBUG_ALERTS:
            print(f"  ⏱ age={item_age_minutes}m tier={freshness_tier} | {title[:40]}")

        ai_decision  = ai_data.get("decision", "SKIP")
        flip_profit  = scoring["flip_profit"]

        # PART 2 — FAKE MERCH FILTER
        t_lower = title.lower()
        fake_merch = (
            brand in FAKE_MERCH_BRANDS and
            contains_keywords(title, MERCH_KEYWORDS)
        )
        if fake_merch:
            confidence = max(confidence - 5.0, 0.0)
            if DEBUG_ALERTS:
                print(f"  🚫 FAKE MERCH: brand={brand} title={title[:40]}")

        # PART 3 — REAL VINTAGE SIGNAL BOOST
        if contains_keywords(title, REAL_VINTAGE_KEYWORDS):
            confidence = min(confidence + 3.0, 10.0)

        # PART 4 — FOOTBALL QUALITY FILTER
        if category == "jersey" or search.get("football_mode"):
            # Reject bad football items
            if contains_keywords(title, BAD_FOOTBALL_KEYWORDS):
                if DEBUG_ALERTS:
                    print(f"  ⛔ BAD FOOTBALL KW: {title[:40]}")
                return {
                    "send_alert": False, "tier": None,
                    "confidence": confidence, "scoring": scoring,
                    "ai_data": ai_data, "db_data": db_data,
                    "brand": brand, "category": category,
                    "flip_profit": flip_profit, "item": item,
                    "market_price": market_price, "is_grail": is_grail,
                    "grail_score": g_score, "deal_tag": deal_tag,
                    "flip_speed": flip_speed, "item_age_min": item_age_minutes,
                    "undervalue_ratio": round(undervalue_ratio, 3),
                    "_skip_reason": "bad_football",
                }
            # Require at least one quality signal
            good_club_match  = contains_keywords(title, GOOD_FOOTBALL_CLUBS)
            good_brand_match = brand in GOOD_FOOTBALL_BRANDS
            year_match       = contains_year(title, 1990, 2010)
            if not (good_club_match or good_brand_match or year_match):
                if DEBUG_ALERTS:
                    print(f"  ⛔ NO QUALITY FOOTBALL SIGNAL: {title[:40]}")
                return {
                    "send_alert": False, "tier": None,
                    "confidence": confidence, "scoring": scoring,
                    "ai_data": ai_data, "db_data": db_data,
                    "brand": brand, "category": category,
                    "flip_profit": flip_profit, "item": item,
                    "market_price": market_price, "is_grail": is_grail,
                    "grail_score": g_score, "deal_tag": deal_tag,
                    "flip_speed": flip_speed, "item_age_min": item_age_minutes,
                    "undervalue_ratio": round(undervalue_ratio, 3),
                    "_skip_reason": "low_quality_football",
                }

        # PART 5 — LEGO SYSTEM
        if "lego" in t_lower or search.get("lego_sw_mode") or search.get("category") == "lego":
            is_minifig = contains_keywords(title, LEGO_MINIFIG_KEYWORDS)
            is_set     = any(char.isdigit() for char in title)
            is_sw_lego = "star wars" in t_lower
            if is_minifig:
                if price > 25:
                    if DEBUG_ALERTS:
                        print(f"  ⛔ LEGO MINIFIG TOO EXPENSIVE price={price}: {title[:40]}")
                    return {
                        "send_alert": False, "tier": None,
                        "confidence": confidence, "scoring": scoring,
                        "ai_data": ai_data, "db_data": db_data,
                        "brand": brand, "category": category,
                        "flip_profit": flip_profit, "item": item,
                        "market_price": market_price, "is_grail": is_grail,
                        "grail_score": g_score, "deal_tag": deal_tag,
                        "flip_speed": flip_speed, "item_age_min": item_age_minutes,
                        "undervalue_ratio": round(undervalue_ratio, 3),
                        "_skip_reason": "lego_minifig_overpriced",
                    }
            if is_set:
                confidence = min(confidence + 2.0, 10.0)
            if is_sw_lego:
                confidence = min(confidence + 2.0, 10.0)

        # ── PART 7 — TRASH FILTER (hard reject low-value women's items) ─
        TRASH_KEYWORDS = [
            "dress", "sukienka", "blouse", "bluzka", "bikini",
            "crop top", "leggings", "legginsy", "kombinezon bodysuit",
        ]
        if contains_keywords(title, TRASH_KEYWORDS):
            if not is_grail and price < 80:
                if DEBUG_ALERTS:
                    print(f"  🗑️ TRASH skip | {title[:40]}")
                return {
                    "send_alert": False, "tier": None,
                    "confidence": confidence, "scoring": scoring,
                    "ai_data": ai_data, "db_data": db_data,
                    "brand": brand, "category": category,
                    "flip_profit": scoring.get("flip_profit", 0), "item": item,
                    "market_price": market_price, "is_grail": is_grail,
                    "grail_score": g_score, "deal_tag": deal_tag,
                    "flip_speed": flip_speed, "item_age_min": item_age_minutes,
                    "undervalue_ratio": round(undervalue_ratio, 3),
                    "freshness_tier": freshness_tier,
                    "_skip_reason": "trash_item",
                }

        # PART 7 — CONTEXTUAL SCORING (additive on top of confidence)
        ctx_score = 0
        if brand:
            ctx_score += 2
        if contains_keywords(title, REAL_VINTAGE_KEYWORDS):
            ctx_score += 3
        if strong_undervalue:
            ctx_score += 2
        if price >= 150:
            ctx_score += 2
        if item_age_minutes <= 5:
            ctx_score += 3
        if fake_merch:
            ctx_score -= 5
        # Blend: ctx_score drives a small nudge rather than overriding confidence
        confidence = min(max(confidence + ctx_score * 0.15, 0.0), 10.0)

        # PART 8 — UNDERVALUE BOOSTS
        if undervalue_ratio < 0.6:
            confidence = min(confidence + 2.0, 10.0)
            deal_tag = "STEAL"
        elif undervalue_ratio < 0.75:
            confidence = min(confidence + 1.0, 10.0)
            if deal_tag == "WEAK":
                deal_tag = "GOOD"

        # Confidence floor
        if confidence < 5.0:
            ai_decision = "SKIP"

        # Part 5 — FLIP_MIN_PROFIT = 25
        flip_min = 10 if is_grail else FLIP_MIN_PROFIT

        # Force alert: price < 50% avg DB
        force_alert = (
            db_data is not None and
            price < db_data["avg"] * 0.50
        )

        tier = get_alert_tier(confidence, ai_decision)

        # High value mode (items 150+ zł)
        high_value = price >= 150
        if high_value and estimated_market_price:
            if price < estimated_market_price * 0.75:
                confidence = min(confidence + 2.0, 10.0)
                flip_profit = max(flip_profit, estimated_market_price * 0.25)

        # Fallback category key for DB (vintage without brand)
        if not brand and _has_vintage and category:
            fallback_key = f"{category}_generic"
            if fallback_key not in self.db.db:
                self.db.add_sample(fallback_key, price)

        # ── PART 3+4 — LOW-DATA FALLBACK (no MarketDB) ───────────
        low_confidence_mode = False
        has_db_data         = db_data is not None and estimated_market_price is not None
        if not has_db_data:
            # Heuristic market estimate
            if not estimated_market_price:
                estimated_market_price = price * 1.6
                undervalue_ratio       = price / estimated_market_price   # always 0.625
                strong_undervalue      = undervalue_ratio < 0.6
            flip_profit         = max(flip_profit, estimated_market_price - price)
            low_confidence_mode = True

            # PART 4 — baseline confidence when no DB
            confidence = max(confidence, 5.5)
            if brand:
                confidence = min(confidence + 1.0, 10.0)
            if _has_vintage or contains_keywords(title, REAL_VINTAGE_KEYWORDS):
                confidence = min(confidence + 1.0, 10.0)
            if price < 50:
                confidence = min(confidence + 0.5, 10.0)

        # PART 1 — no-brand PENALTY (not a block)
        if not _has_brand:
            confidence = max(confidence - 2.0, 0.0)

        # Confidence floor for ai_decision
        if confidence < 5.0:
            ai_decision = "SKIP"

        flip_min    = 10 if is_grail else FLIP_MIN_PROFIT
        force_alert = (
            db_data is not None and
            price < db_data["avg"] * 0.50
        )
        tier        = get_alert_tier(confidence, ai_decision)

        # High-value mode (items 150+ zł)
        high_value = price >= 150
        if high_value and estimated_market_price:
            if price < estimated_market_price * 0.75:
                confidence  = min(confidence + 2.0, 10.0)
                flip_profit = max(flip_profit, estimated_market_price * 0.25)

        # ── PART 5 — GRAIL OVERRIDE ───────────────────────────────
        if is_grail:
            send_alert = flip_profit >= 10

        # ── PART 8 — FINAL ALERT LOGIC (unified, no hard brand/DB blocks) ──
        else:
            effective_price  = scoring.get("effective_price", price)
            market_price_db  = scoring.get("market_price_db")
            price_undervalue = (
                market_price_db is not None and
                effective_price < market_price_db * 0.85
            )
            normal_send = (
                (flip_profit >= flip_min and confidence >= 6.0)
                or (strong_undervalue and confidence >= 5.5)
                or (price_undervalue and confidence >= 5.5)
                or (high_value and undervalue_ratio < 0.75 and confidence >= 5.0)
                or (force_alert and confidence >= 5.5)
            )
            # PART 3 — low-data path: lower bar when no DB
            lowdata_send = (
                low_confidence_mode
                and flip_profit >= 15
                and confidence >= 5.0
            )
            send_alert = normal_send or lowdata_send

        # ── PART 8 — DEBUG OUTPUT ─────────────────────────────────
        if DEBUG_ALERTS:
            lc_tag  = " [LOW-DATA]" if low_confidence_mode else ""
            gr_tag  = " 💎GRAIL"   if is_grail else ""
            action  = "📤 SEND" if send_alert else "⏭  SKIP"
            age_str = f"{item_age_minutes}m"
            print(f"  {action}{lc_tag}{gr_tag} | {title[:50]} | price={price} | profit={flip_profit:.0f} | conf={confidence:.1f} | age={age_str}m")
            print(f"  DEBUG: brand={brand} profit={flip_profit:.0f} conf={confidence:.1f} db={estimated_market_price}")

        # Deduplicacja sesyjna
        item_id = str(item.get("id", ""))
        if send_alert and item_id:
            if item_id in self._alerted_ids:
                send_alert = False
            else:
                self._alerted_ids.add(item_id)
                if len(self._alerted_ids) > 10_000:
                    self._alerted_ids = set(list(self._alerted_ids)[-5_000:])

        return {
            "send_alert":    send_alert,
            "tier":          "💎 GRAIL" if is_grail else (tier or ("GOOD" if force_alert else None)),
            "confidence":    confidence,
            "scoring":       scoring,
            "ai_data":       ai_data,
            "db_data":       db_data,
            "brand":         brand,
            "category":      category,
            "flip_profit":   flip_profit,
            "item":          item,
            "market_price":  market_price,
            "is_grail":      is_grail,
            "grail_score":   g_score,
            "deal_tag":      deal_tag,
            "flip_speed":    flip_speed,
            "item_age_min":  item_age_minutes,
            "undervalue_ratio": round(undervalue_ratio, 3),
            "freshness_tier": freshness_tier,
        }

    # ── HEURYSTYCZNY AI (bez Claude) ─────────
    def _heuristic_ai(
        self,
        title: str,
        price: float,
        db_data: dict | None,
        brand: str | None,
        category: str,
    ) -> dict:
        """Prosta heurystyka gdy brak klucza AI.
        FIX: wyższy bazowy score dla znanych brandów — żeby conf=5.6
        nie blokowało wszystkiego przy pustej bazie DB.
        """
        t = title.lower()
        hype = 8 if brand in HYPE_BRANDS else (6 if brand in LUXURY_BRANDS else 3)
        rarity = 7 if any(w in t for w in ["rare", "rzadka", "kolekcjoner", "limited", "deadstock"]) else 3

        # FIX #1 — bazowy score zależny od rozpoznania brandu
        # FIX #3 — Funko bez DB dostawało base=6.5 → score=8.0 → BUY → GOOD/INSANE
        # mimo braku jakichkolwiek danych rynkowych. Rozróżniamy:
        # - Supreme/Palace/Jordan (streetwear hype) → 6.5 (mają realny rynek wtórny)
        # - Funko/LEGO (kolekcjonerskie ale zmienne) → 6.0 (potrzebują potwierdzenia ceną)
        # - Luxury → 6.0 (wymaga sygnału fake-risk)
        # - Mainstream (Nike/Adidas ogólnie) → 5.8
        # - Znana kategoria bez marki → 5.5
        # ── PART 3: CONTEXTUAL BRAND LOGIC ────────────────
        # Nie wystarczy wykryć brand — liczy się KONTEKST
        contextual_bonus = 0.0

        # Jeff Hamilton — zawsze grail, rynek wtórny 200–2000 USD
        if "jeff hamilton" in t:
            contextual_bonus += 5.0
            base = max(base, 8.0)

        # Levi's — nie każde Levi's jest warte flip
        if "levi" in t or "levis" in t:
            if any(k in t for k in ["501", "505", "made in usa", "orange tab",
                                     "vintage", "deadstock", "big e", "red tab"]):
                contextual_bonus += 3.0
            else:
                contextual_bonus -= 1.0  # generic Levi's → mniej warte

        # Wrangler vintage — kurtki i spodnie vintage mają rynek
        if "wrangler" in t:
            if any(k in t for k in ["vintage", "jacket", "kurtka", "denim", "western"]):
                contextual_bonus += 2.0

        # Nike ACG — premium subbrand
        if "nike acg" in t or ("nike" in t and "acg" in t):
            contextual_bonus += 3.0
            base = max(base, 7.0)

        # Stone Island / CP Company
        if "stone island" in t or "cp company" in t:
            contextual_bonus += 2.0
            base = max(base, 7.5)

        # Varsity / College jacket — niszowy rynek premium
        if any(k in t for k in ["varsity", "letterman", "college jacket"]):
            contextual_bonus += 2.0

        # Workwear vintage — Carhartt Detroit/Santa Fe/chore coat
        if "carhartt" in t:
            if any(k in t for k in ["detroit", "santa fe", "chore", "active",
                                     "michigan", "ranger", "vintage", "wip"]):
                contextual_bonus += 2.0

        STREETWEAR_HYPE = {"supreme", "palace", "stussy", "bape", "a bathing ape",
                           "kaws", "travis scott", "yeezy", "jordan", "nike sb",
                           "sacai", "fragment", "fear of god", "wtaps"}
        COLLECTOR_HYPE  = {"funko", "funko pop", "lego"}

        if brand in STREETWEAR_HYPE:
            base = 6.5   # mocny hype streetwear — rynek wtórny pewny
        elif brand in COLLECTOR_HYPE or brand in (HYPE_BRANDS - STREETWEAR_HYPE):
            base = 6.0   # kolekcjonerskie — potrzebują ceny rynkowej do pewności
        elif brand in LUXURY_BRANDS:
            base = 6.0
        elif brand in MAINSTREAM_BRANDS:
            base = 5.8
        elif category in ("sneakers", "funko", "lego"):
            base = 5.5   # znana kategoria ale bez marki
        else:
            base = 5.0

        avg = db_data["avg"] if db_data else price * 1.5
        underpriced = price < avg * 0.70
        estimated = avg * 1.1 if db_data else price * 1.5

        score = base + contextual_bonus
        if underpriced:
            score += 2.0
        if hype >= 8:
            score += 1.5
        if rarity >= 7:
            score += 1.0
        score = min(score, 10.0)

        if score >= 8:
            decision = "BUY"
        elif score >= 6:
            decision = "WATCH"
        else:
            decision = "SKIP"

        return {
            "brand": brand,
            "category": category,
            "keywords": [],
            "estimated_value": round(estimated, 2),
            "rarity": rarity,
            "hype_score": hype,
            "underpriced": underpriced,
            "final_score": round(score, 1),
            "decision": decision,
        }

    # ── FORMAT ALERTU ────────────────────────
    def format_alert(self, result: dict) -> str:
        tier      = result["tier"]
        conf      = result["confidence"]
        item      = result["item"]
        ai        = result["ai_data"]
        db        = result["db_data"]
        scoring   = result["scoring"]
        price     = item.get("price", 0)
        title     = item.get("title", "")
        brand     = result.get("brand") or ""
        flip        = result.get("flip_profit", 0)
        flip_speed  = result.get("flip_speed", "MEDIUM")
        age_min     = result.get("item_age_min", 9999)
        uv_ratio    = result.get("undervalue_ratio", 1.0)
        age_str     = f"{age_min}min" if age_min < 9999 else "?"
        speed_emoji = {"FAST": "⚡", "MEDIUM": "📦", "SLOW": "🐢"}.get(flip_speed, "📦")

        # Tytuł bez metadanych Vinted
        clean = re.sub(r',?\s*(marka|stan|rozmiar):.*', '', title, flags=re.IGNORECASE).strip()

        # Tier emoji + grail override
        is_grail = result.get("is_grail", False)
        grail_sc = result.get("grail_score", 0)
        deal_tag = result.get("deal_tag", "")

        if is_grail:
            header = f"💎 GRAIL DETECTED  (score={grail_sc})"
        elif tier == "INSANE":
            header = "🔴 INSANE DEAL"
        elif tier == "GOOD":
            header = "🟡 GOOD DEAL"
        else:
            header = "⚪ WATCH"

        if deal_tag and deal_tag != "WEAK":
            deal_badges = {"STEAL": "🔥 STEAL", "GOOD": "✅ GOOD PRICE"}
            header += f"  ·  {deal_badges.get(deal_tag, deal_tag)}"

        lines = [
            f"{'━'*28}",
            f"{header}  •  confidence: {conf:.1f}/10",
            f"{'━'*28}",
            "",
            f"📦  {clean[:90]}",
            "",
            f"💰  Cena:       {price:.0f} zł",
        ]

        if db:
            lines.append(f"📊  Śr. w bazie: {db['avg']:.0f} zł ({db['count']} ofert)")
            disc = (1 - price / db["avg"]) * 100 if db["avg"] > 0 else 0
            if disc > 0:
                lines.append(f"✂️   Taniej o:   {disc:.0f}%  (~{db['avg']-price:.0f} zł)")

        if result["market_price"]:
            lines.append(f"📈  Mediana:     {result['market_price']:.0f} zł")

        if flip > FLIP_MIN_PROFIT:
            lines.append(f"💚  Flip profit: ~{flip:.0f} zł  {speed_emoji} {flip_speed}")

        # Part 10 — age + undervalue in alert
        meta = []
        if age_min < 9999:
            meta.append(f"⏱ {age_str}")
        if uv_ratio < 1.0:
            pct = int((1 - uv_ratio) * 100)
            meta.append(f"📉 -{pct}% vs rynek")
        if meta:
            lines.append("   ".join(meta))

        trend = scoring.get("trend", "stable")
        if trend == "rising":
            lines.append("📈  Trend:       rosnący ↑")
        elif trend == "falling":
            lines.append("📉  Trend:       malejący ↓")

        if scoring.get("fake_risk"):
            lines.append("⚠️   Uwaga:       ryzyko fałszywki!")

        lines += [
            "",
            f"🤖  AI:   {ai.get('decision','?')}  •  score {ai.get('final_score',0):.1f}/10",
            f"🔥  Hype: {ai.get('hype_score',0)}/10  "
            f"•  Rarity: {ai.get('rarity',0)}/10",
            "",
            f"📊  DB:{scoring['db_score']:.1f}  "
            f"Mkt:{scoring['market_score']:.1f}  "
            f"AI:{scoring['ai_score']:.1f}",
        ]

        return "\n".join(lines)

    # ── FEEDBACK ─────────────────────────────
    def record_click(self, item_id: str, brand: str, category: str):
        self.learner.record_click(item_id, brand, category)

    def record_buy(self, item_id: str, brand: str, category: str):
        self.learner.record_buy(item_id, brand, category)

    # ── STATYSTYKI ───────────────────────────
    def stats(self) -> str:
        return (
            f"🧠 Engine stats:\n"
            f"  DB groups:   {len(self.db.db)}\n"
            f"  Raw items:   {len(self.raw.items)}\n"
            f"  AI cache:    {len(self.ai_cache.cache)}\n"
            f"  Clicked:     {len(self.learner.data.get('clicked', []))}\n"
            f"  Bought:      {len(self.learner.data.get('bought', []))}"
        )
