"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🧠  VINTED BOT — MULTI-ENGINE v2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3 niezależne silniki:
  🔵 ChaosEngine  — tanie niedowartościowane itemy (brand NIE wymagany)
  🟣 BrandEngine  — markowe itemy vs mediana rynkowa
  🟡 GrailEngine  — rzadkie vintage / kolekcjonerskie

Użycie w bot.py (nowy interfejs):
    from engine import Engine, format_alert

    engine = Engine()

    def run_cycle(items, market_prices):
        results = engine.run_cycle(items, market_prices)
        for r in results:
            send_to_telegram(format_alert(r))

Stary interfejs bot.py (backward compatible):
    result = engine.evaluate(item, search, market_price)
    if result["send_alert"]:
        msg = engine.format_alert(result)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import re
import json
import os
import time
import statistics
from collections import defaultdict


# ─────────────────────────────────────────────────────
#  📁 PLIKI
# ─────────────────────────────────────────────────────
_DATA_DIR     = os.getenv("DATA_DIR", "/data/vinted_bot")
os.makedirs(_DATA_DIR, exist_ok=True)

DB_FILE       = os.path.join(_DATA_DIR, "market_db.json")

DEBUG_ALERTS    = True
DEBUG_PIPELINE  = os.getenv("DEBUG_PIPELINE", "0") == "1"   # Part 7 — verbose pipeline log


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🧠 PART 1 — CENTRAL FEATURE EXTRACTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_item_features(item: dict) -> dict:
    """
    Single source of truth dla cech itemu.
    ZAWSZE zwraca pełny dict — nigdy nie crashuje.
    Używane przez wszystkie 3 silniki i check_search w bot.py.

    Returns:
        brand       : str | None  — wykryty brand
        has_brand   : bool        — czy brand wykryty
        is_vintage  : bool        — czy sygnały vintage
        category    : str | None  — hoodie/tshirt/jacket/jeans/...
        keywords    : list[str]   — znalezione tagi vintage/style
    """
    try:
        if not item or not isinstance(item, dict):
            return {"brand": None, "has_brand": False,
                    "is_vintage": False, "category": None, "keywords": []}
        title  = str(item.get("title") or "")
        t      = title.lower()

        brand    = detect_brand(title)
        # Fix 2 — Band Brand System: band = brand dla celów scoringu
        band     = detect_band(title)
        if not brand and band:
            brand = band   # traktuj band jak brand
        category = detect_category(title)

        # Zbierz pasujące tagi
        _TAGS = [
            "vintage", "90s", "80s", "70s", "y2k", "single stitch",
            "made in usa", "retro", "archive", "deadstock",
            "band tee", "tour shirt", "rap tee", "tour", "bootleg",
            "grunge", "streetwear", "workwear", "gorpcore", "skater",
            "baggy", "oversized", "distressed",
        ]
        tags = [tag for tag in _TAGS if tag in t]

        is_vintage = _is_vintage(title)
        # Fix 2 — band is strong if also vintage/90s/single stitch
        _band_raw      = detect_band(title)
        is_strong_band = bool(_band_raw and is_vintage)

        # Rule 4 — VALUE SIGNALS
        _val_count = count_value_signals(title)
        _has_vals  = _val_count > 0

        feat = {
            "brand":              brand,
            "has_brand":          brand is not None,
            "is_vintage":         is_vintage,
            "category":           category,
            "keywords":           tags,
            "band":               _band_raw,
            "is_strong_band":     is_strong_band,
            "value_signal_count": _val_count,
            "has_value_signals":  _has_vals,
        }

        if DEBUG_PIPELINE:
            print(f"  [FEAT] brand={brand} vintage={is_vintage} "
                  f"cat={category} tags={tags} | {title[:50]}")

        return feat

    except Exception as e:
        # Part 6 — NIGDY nie crashuj cichutko; zawsze loguj
        print(f"  ❌ extract_item_features ERROR: {e} | item={item.get('title','?')[:60]}")
        return {
            "brand": None, "has_brand": False,
            "is_vintage": False, "category": None, "keywords": [],
        }

# Part 6 — zmienione z 15 → 60 min
MAX_ITEM_AGE_MINUTES = 60


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🌍 LANGUAGE FILTER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Słowa typowe dla innych języków niż PL/EN — filtrujemy tytuły
# gdzie >40% tokenów to nie-PL/EN
_FOREIGN_TOKENS = {
    # Rumuński
    "tricou", "damă", "bumbac", "pantaloni", "geacă", "haina", "bluza",
    "fusta", "rochie", "sacou", "palton", "cizme", "ghete", "pantofi",
    "marime", "culoare", "stare", "nou", "purtata", "foarte", "buna",
    # Fiński
    "paita", "takki", "housut", "kengät", "uusi", "hyvä", "kunto",
    "hinta", "myyn", "koko", "väri", "urheil",
    # Węgierski
    "dzseki", "nadrág", "cipő", "póló", "méret", "állapot", "szép",
    "eladó", "újszerű", "használt", "kabát", "felső",
    # Czeski/Słowacki
    "bunda", "mikina", "tričko", "kalhoty", "boty", "nový", "dobrý",
    "stav", "pánský", "dámský", "veľkosť",
    # Litewski/Łotewski/Estoński
    "striukė", "marškinėliai", "batai", "džinsai", "nauji",
    # Duński/Norweski/Szwedzki
    "trøje", "jakke", "bukser", "sko", "sælger", "brugt", "stand",
    "størrelse", "farve", "dragt", "vindjacka", "byxor",
    "til", "str", "brugt", "mærke", "pris", "køber",
}

def is_foreign_title(title: str, threshold: float = 0.40) -> bool:
    """
    Zwraca True jeśli tytuł jest podejrzanie obcojęzyczny.
    threshold = odsetek tokenów które są w liście obcych słów.
    Bezpiecznie obsługuje None i nie-stringi.
    """
    if not title or not isinstance(title, str):
        return False
    tokens = re.findall(r'\b[^\W\d_]+\b', title.lower(), re.UNICODE)
    if len(tokens) < 3:
        return False   # Za krótki tytuł — nie odrzucaj
    foreign_hits = sum(1 for t in tokens if t in _FOREIGN_TOKENS)
    if foreign_hits == 0:
        return False
    ratio = foreign_hits / len(tokens)
    # Dla krótkich tytułów (3-5 tokenów) jeden hit wystarczy
    if len(tokens) <= 5:
        return ratio >= 0.20
    return ratio >= threshold


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🔧 HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def kw(text: str, keywords: list) -> bool:
    """True jeśli jakiekolwiek słowo kluczowe jest w tekście (lowercase)."""
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def item_age_minutes(item: dict) -> int:
    """Wiek itemu w minutach. Brak ts → syntetyczny wiek z pozycji rank."""
    ts = item.get("created_at_ts")
    if ts:
        try:
            return max(0, int((time.time() - float(ts)) / 60))
        except:
            pass
    rank = item.get("_rank")
    if rank is not None:
        if rank <= 5:   return 5
        if rank <= 20:  return 30
        if rank <= 50:  return 90
        return 180
    return 360


def freshness_boost(age_min: int) -> float:
    """Confidence boost za świeżość."""
    if age_min <= 10:  return 3.0
    if age_min <= 30:  return 1.5
    if age_min <= 60:  return 0.5
    return 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🔤 BRAND / CATEGORY DETECTION (shared)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_ALL_BRANDS = sorted([
    # Premium / outdoor
    "arc'teryx", "arcteryx", "arc teryx",
    "stone island", "cp company", "patagonia",
    "supreme", "palace", "stussy", "bape",
    "fear of god", "essentials",
    "corteiz", "crtz", "broken planet", "denim tears", "represent",
    # Sportswear
    "nike", "adidas", "puma", "reebok",
    "new balance", "asics", "salomon",
    "vans", "converse", "timberland",
    # Workwear / denim
    "carhartt", "carhartt wip",
    "dickies", "wrangler",
    "levi's", "levis", "levi", "lee ",
    "ben davis", "pointer brand",
    # Outdoor / lifestyle
    "the north face", "tnf",
    "columbia", "helly hansen",
    "columbia sportswear",
    # Classic / preppy
    "ralph lauren", "polo ralph lauren",
    "lacoste", "fred perry", "champion",
    "tommy hilfiger", "calvin klein",
    "nautica", "izod",
    # Luxury — partial match safe
    "gucci", "louis vuitton", "prada",
    "hermes", "balenciaga", "versace",
    "burberry", "fendi", "dior",
    "off-white", "stone island",
    "moncler", "canada goose", "moose knuckles",
    # Added missing (diesel, etc.)
    "diesel", "g-star", "g star",
    "replay", "true religion",
    # Football
    "umbro", "kappa", "lotto", "diadora",
    "hummel", "admiral", "le coq sportif",
    "erima", "joma",
    # Music / moto — collector value
    "harley davidson", "harley-davidson", "harley",
    "fruit of the loom", "gildan", "delta",
    "brockum", "liquid blue", "nutmeg",
    "anvil", "tultex",
    "salem sportswear", "russell athletic",
    "starter", "jerzees", "artex",
    "signal sport", "logo 7", "chalk line",
], key=len, reverse=True)

LUXURY_BRANDS = {
    "gucci", "louis vuitton", "prada", "hermes", "balenciaga",
    "versace", "burberry", "fendi", "dior", "off-white",
    "moncler", "canada goose", "moose knuckles",
}

# Brands that guarantee minimum confidence 6.0 when detected (Global rule 2)
STRONG_BRANDS = {
    "arc'teryx", "arcteryx", "arc teryx",
    "stone island", "cp company", "patagonia",
    "supreme", "palace", "stussy", "bape",
    "fear of god", "essentials",
    "corteiz", "crtz", "broken planet", "denim tears", "represent",
    "carhartt", "carhartt wip", "salomon",
    "the north face", "tnf", "helly hansen",
    "nike", "adidas", "new balance", "asics",
    "levi's", "levis", "levi", "wrangler", "diesel",
    "ralph lauren", "polo ralph lauren",
    "gucci", "louis vuitton", "prada", "hermes",
    "balenciaga", "versace", "burberry", "fendi", "dior",
    "off-white", "moncler", "canada goose",
    "harley davidson", "harley-davidson",
}

# Brands eligible for GRAIL layer (must also have rarity keyword)
GRAIL_ELIGIBLE_BRANDS = {
    # Vintage basics / print shops
    "screen stars", "hanes", "fruit of the loom", "gildan",
    "delta", "brockum", "liquid blue", "nutmeg", "anvil",
    "tultex", "salem sportswear", "russell athletic",
    "starter", "jerzees", "artex", "signal sport",
    # Heritage / workwear with collector value
    "carhartt", "levi's", "levis", "levi",
    "wrangler", "ben davis",
    # Music / merch brands
    "harley davidson", "harley-davidson",
}

_ITEM_TYPES = [
    ("hoodie",   ["hoodie", "bluza", "sweatshirt", "hooded", "crewneck", "zip up"]),
    ("tshirt",   ["t-shirt", "tshirt", "tee ", " tee", "koszulka", "t shirt"]),
    ("jacket",   ["jacket", "kurtka", "bomber", "varsity", "windbreaker",
                  "anorak", "parka", "trucker", "chore coat"]),
    ("coat",     ["coat", "płaszcz", "overcoat", "trench", "shearling"]),
    ("jeans",    ["jeans", "denim", "dżinsy"]),
    ("cargo",    ["cargo"]),
    ("shirt",    ["shirt", "koszula", "flannel"]),
    ("sneakers", ["sneakers", "shoes", "buty", "trainers", "kicks"]),
    ("jersey",   ["jersey", "football shirt", "koszulka piłkarska"]),
    ("cap",      ["cap", "hat", "czapka", "beanie", "snapback"]),
]


def detect_brand(title: str) -> str | None:
    """
    Detects brand even if lowercase, partial, or inside longer text.
    Returns normalized brand string (lowercase).
    """
    if not title:
        return None
    t = title.lower()
    for brand in _ALL_BRANDS:
        if brand in t:
            return brand.strip()
    return None


def brand_strength(brand: str | None) -> float:
    """
    Returns minimum confidence floor for a detected brand.
    Global rule: if brand in STRONG_BRANDS → min conf = 6.0
    """
    if not brand:
        return 0.0
    if brand in STRONG_BRANDS:
        return 6.0
    # Known but not strong (kappa, lotto, umbro etc.)
    return 4.0


def detect_category(title: str) -> str | None:
    t = title.lower()
    for cat, keywords in _ITEM_TYPES:
        if any(k in t for k in keywords):
            return cat
    return None


def _is_vintage(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in [
        "vintage", "90s", "80s", "70s", "y2k", "single stitch",
        "made in usa", "retro", "old ", "archive", "deadstock",
        "band tee", "tour shirt", "rap tee",
    ])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  💾 MARKET DB — Part 5 (simplified, accepts chaos data)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MarketDB:
    """
    Baza cen rynkowych z pełną persistencją.

    Part 3: automatyczny zapis co 5 min + przy shutdown (atexit).
    Part 4: rolling window 48h, median/p25/p75, deal classification, anomaly score.
    Part 6: brak cichych błędów — każdy wyjątek jest logowany.
    """
    MAX_SAMPLES   = 50
    MAX_AGE_HOURS = 48
    SAVE_INTERVAL = 300   # 5 minut

    def __init__(self):
        self.db: dict[str, dict] = {}
        self._last_save: float   = time.time()
        self._dirty: bool        = False
        self._load()
        self._register_atexit()

    # ── LOAD / SAVE ──────────────────────────────────

    def _load(self):
        """Part 3 — wczytaj DB z pliku przy starcie."""
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE) as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.db = loaded
                    print(f"  📦 MarketDB loaded: {len(self.db)} grup")
                else:
                    print(f"  ⚠️ MarketDB: nieprawidłowy format — reset")
                    self.db = {}
            else:
                print(f"  📦 MarketDB: brak pliku — start od zera")
                self.db = {}
        except Exception as e:
            print(f"  ❌ MarketDB load ERROR: {e} — start od zera")
            self.db = {}

    def save(self, force: bool = False):
        """
        Part 3 — zapisz DB do pliku.
        Automatycznie co SAVE_INTERVAL lub gdy force=True.
        """
        now = time.time()
        if not force and not self._dirty:
            return
        if not force and (now - self._last_save) < self.SAVE_INTERVAL:
            return
        try:
            tmp = DB_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.db, f, indent=2)
            os.replace(tmp, DB_FILE)   # atomic replace
            self._last_save = now
            self._dirty     = False
            if DEBUG_PIPELINE:
                print(f"  💾 MarketDB saved: {len(self.db)} grup → {DB_FILE}")
        except Exception as e:
            print(f"  ❌ MarketDB save ERROR: {e}")

    def _register_atexit(self):
        """Part 3 — zapisz przy shutdown."""
        import atexit
        atexit.register(self.save, force=True)

    # ── ADD SAMPLE ────────────────────────────────────

    def add_sample(self, key: str, price: float):
        """
        Part 4 — przechowuje próbkę ceny.
        Part 2 FIX: akceptuje każdy klucz — brand NIE jest wymagany.
        Klucze: brand_category, chaos_category, category_unknown, vintage_category.
        """
        if not key or not isinstance(price, (int, float)) or price < 10:
            return
        try:
            now = time.time()
            if key not in self.db:
                self.db[key] = {
                    "median": price, "avg": price, "p25": price, "p75": price,
                    "count": 0, "updated": now, "_samples": [],
                }
            entry   = self.db[key]
            samples = entry.get("_samples", [])

            # Rolling window: usuń stare próbki
            samples.append({"price": float(price), "ts": now})
            samples = [s for s in samples
                       if now - s.get("ts", 0) < self.MAX_AGE_HOURS * 3600]
            samples = samples[-self.MAX_SAMPLES:]

            prices = sorted(s["price"] for s in samples)
            n      = len(prices)

            entry["count"] = n
            if n >= 2:
                med = statistics.median(prices)
                p25 = prices[max(0, n // 4 - 1)]
                p75 = prices[min(n - 1, (n * 3) // 4)]

                # Part 4 — deal classification
                p_cur = float(price)
                if p_cur < p25:
                    deal = "STRONG"
                elif p_cur < med:
                    deal = "GOOD"
                else:
                    deal = "WEAK"

                # Part 4 — anomaly score
                anomaly = 0
                if p_cur < med * 0.6:
                    anomaly = 2
                elif p_cur < med * 0.75:
                    anomaly = 1

                entry.update({
                    "median":        round(med, 2),
                    "avg":           round(sum(prices) / n, 2),
                    "p25":           round(p25, 2),
                    "p75":           round(p75, 2),
                    "min":           round(prices[0], 2),
                    "max":           round(prices[-1], 2),
                    "count":         n,
                    "updated":       now,
                    "last_deal":     deal,
                    "last_anomaly":  anomaly,
                })

            entry["count"]    = n
            entry["_samples"] = samples
            self.db[key]      = entry
            self._dirty       = True

            # Periodic auto-save (Part 3)
            self.save()

        except Exception as e:
            print(f"  ❌ MarketDB.add_sample ERROR: key={key} price={price} | {e}")

    # ── LOOKUP ────────────────────────────────────────

    def lookup(self, key: str) -> dict | None:
        """Zwraca dane dla klucza lub None."""
        return self.db.get(key)

    def lookup_brand_category(self, brand: str, category: str | None) -> dict | None:
        """Szuka po brand+category lub samym brand."""
        try:
            if category:
                key = f"{brand}_{category}"
                if key in self.db:
                    return self.db[key]
            brand_l = brand.lower()
            for k, v in self.db.items():
                if brand_l in k.lower() and v.get("count", 0) >= 3:
                    return v
            return None
        except Exception as e:
            print(f"  ❌ MarketDB.lookup ERROR: {e}")
            return None

    def get_deal_tag(self, key: str, price: float) -> str:
        """
        Part 4 — zwraca deal tag dla ceny względem DB.
        Zwraca: 'STRONG' | 'GOOD' | 'WEAK' | 'NO_DATA'
        """
        try:
            entry = self.db.get(key)
            if not entry or entry.get("count", 0) < 3:
                return "NO_DATA"
            p25 = entry.get("p25", 0)
            med = entry.get("median", 0)
            if price < p25:
                return "STRONG"
            if price < med:
                return "GOOD"
            return "WEAK"
        except:
            return "NO_DATA"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🔵 CHAOS ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_CHAOS_TRASH = [
    "dress", "sukienka", "blouse", "bluzka", "bikini", "crop top",
    "leggings", "legginsy", "bra ", "stanik", "swimsuit", "bodysuit",
    "kombinezon", "rajstopy",
]

# Fix 1 — LOW VALUE: brak brand + brak vintage → HARD SKIP
_LOW_VALUE_KEYWORDS = [
    "top", "blouse", "basic", "casual wear", "everyday",
    "bershka", "h&m", "shein", "fashion nova", "primark",
    "sinsay", "reserved", "stradivarius", "pull&bear",
]

# Fix 2 — BAND BRANDS: muzyczne merche traktowane jak brand
# Rule 1: bands are mid-tier brands — treated like brand for scoring
# Rule 2: Do NOT add fast fashion here
# Rule 3: Do NOT expand luxury brands here
BAND_BRANDS = [
    # Classic rock / metal
    "nirvana", "metallica", "acdc", "ac/dc", "slipknot", "korn",
    "rammstein", "deftones", "tool", "pantera", "megadeth",
    "iron maiden", "black sabbath", "led zeppelin", "pink floyd",
    "grateful dead", "ramones", "sex pistols", "the clash",
    "pearl jam", "soundgarden", "alice in chains",
    "rage against", "system of a down",
    # Hip-hop / rap
    "wu-tang", "wu tang", "tupac", "biggie", "eminem",
    "public enemy", "beastie boys", "nas", "jay-z",
    # Pop / other collectible
    "rolling stones", "david bowie", "the who",
    "bruce springsteen", "johnny cash", "fleetwood mac",
    "guns n roses", "aerosmith", "kiss band",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  💎 VALUE SIGNALS — Rule 4
#  Items with these signals get confidence boost even without brand
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VALUE_SIGNALS = [
    "single stitch",   # premium vintage construction
    "made in usa",     # collector signal
    "made in u.s.a",
    "90s",             # decade marker
    "80s",
    "wool",            # material quality signal
    "cashmere",
    "merino",
    "deadstock",       # unworn vintage
    "unwashed",        # collector term
    "og",              # original / first run
    "1st press",
    "first press",
    "screen printed",
    "tour tee",
    "band tee",
    "concert tee",
    "promo only",
    "promo shirt",
    "bootleg",
    "archive",
    "rare",
]

def has_value_signals(title: str) -> bool:
    """True if title contains at least one VALUE_SIGNAL."""
    t = title.lower()
    return any(sig in t for sig in VALUE_SIGNALS)

def count_value_signals(title: str) -> int:
    """Count how many VALUE_SIGNALs are present."""
    t = title.lower()
    return sum(1 for sig in VALUE_SIGNALS if sig in t)


def detect_band(title: str) -> str | None:
    """
    Fix 2 — Wykrywa band brand w tytule.
    Jeśli wykryty → traktowany jak brand (has_brand=True, strong=True gdy vintage).
    """
    t = title.lower()
    for band in BAND_BRANDS:
        if band in t:
            return band
    return None


_CHAOS_STYLE_KW = [
    "y2k", "grunge", "archive", "workwear", "streetwear",
    "vintage", "90s", "80s", "70s", "retro", "distressed",
    "baggy", "oversized", "skater", "gorpcore",
]

_CHAOS_VINTAGE_KW = [
    "single stitch", "made in usa", "screen stars", "fruit of the loom",
    "hanes", "brockum", "deadstock", "band tee", "tour tee", "rap tee",
    "nutmeg", "liquid blue",
]


class ChaosEngine:
    """
    🔵 CHAOS ENGINE — niedowartościowane itemy, brand NIE wymagany.

    Profit logic: estimated_value = price * 1.6 → profit = price * 0.6
    Send rule:    price <= 80 AND profit >= 15 AND score >= 1
    """

    def __init__(self, market_db: MarketDB):
        self.db       = market_db
        self._sent    = 0
        self._skipped = 0
        self._errors  = 0

    def run(self, items: list[dict]) -> list[dict]:
        self._sent = self._skipped = self._errors = 0
        total   = len(items)
        results = []
        for item in items:
            # Part 2 — pipeline safety: każdy item MUSI być przetworzony
            try:
                r = self._evaluate(item)
                if r["send_alert"]:
                    results.append(r)
                    self._sent += 1
                else:
                    self._skipped += 1
            except Exception as e:
                self._errors += 1
                title = (item.get("title") or "?")[:80] if isinstance(item, dict) else "?"
                print(f"  ❌ [CHAOS] ITEM ERROR: {e} | {title}")
        if DEBUG_ALERTS:
            print(f"  [CHAOS] processed={total} sent={self._sent} "
                  f"skipped={self._skipped} errors={self._errors}")
        return results

    def _evaluate(self, item: dict) -> dict:
        features = extract_item_features(item)
        title    = item.get("title", "") or ""
        price    = float(item.get("price") or 0)

        base = {"engine": "CHAOS", "item": item, "send_alert": False,
                "tier": "CHAOS", "profit": 0, "confidence": 0,
                "anomaly_score": 0, "deal_tag": "NO_DATA"}

        if is_foreign_title(title):
            return {**base, "_skip_reason": "foreign_language"}
        if kw(title, _CHAOS_TRASH):
            return {**base, "_skip_reason": "trash"}
        if price < 15 or price > 200:
            return {**base, "_skip_reason": "price_out_of_range"}

        age = item_age_minutes(item)
        if age > MAX_ITEM_AGE_MINUTES * 6:
            return {**base, "_skip_reason": "stale"}

        brand     = features["brand"]
        band      = features.get("band")
        cat       = features["category"]
        is_vint   = features["is_vintage"]
        has_brand = features["has_brand"]   # True jeśli brand LUB band

        # Fix 4 — CHAOS QUALITY GUARD
        # no_brand AND no_rarity AND generic_item → HARD SKIP
        has_rarity = kw(title, _CHAOS_VINTAGE_KW) or is_vint
        has_style  = kw(title, _CHAOS_STYLE_KW)
        if not has_brand and not has_rarity and not has_style:
            if DEBUG_ALERTS:
                print(f"  [QUALITY] skip_reason=no_market_value | {title[:50]}")
            return {**base, "_skip_reason": "no_market_value"}

        # Fix 1 — LOW_VALUE_KEYWORDS: brak brand + brak vintage → SKIP
        if kw(title, _LOW_VALUE_KEYWORDS) and not has_brand and not is_vint:
            if DEBUG_ALERTS:
                print(f"  [QUALITY] skip_reason=low_value_item | {title[:50]}")
            return {**base, "_skip_reason": "low_value_item"}

        # Rule 5 — SOFT_GRAIL routing: no brand but strong value signals
        # → route to soft grail path with boosted confidence
        # This increases diversity without increasing spam
        val_count   = features.get("value_signal_count", 0)
        has_vals    = features.get("has_value_signals", False)
        is_soft_grail = (
            not has_brand
            and has_vals
            and val_count >= 2
            and (features["is_vintage"] or features.get("band"))
        )

        # Market price: heuristic > DB > 1.6x fallback
        market_price    = None
        brand_heuristic = None
        if brand and cat:
            bp = _HEURISTIC_PRICES.get(brand)
            if bp:
                brand_heuristic = float(bp.get(cat, bp["default"]))
                market_price    = brand_heuristic
        if not market_price and brand and not cat:
            bp = _HEURISTIC_PRICES.get(brand)
            if bp:
                market_price = float(bp["default"])
        if not market_price and cat:
            db_key  = f"{brand}_{cat}" if brand else f"chaos_{cat}"
            db_data = self.db.lookup(db_key)
            if db_data and db_data.get("count", 0) >= 3:
                market_price = db_data.get("median")
        if not market_price:
            market_price = price * 1.6

        estimated_value = market_price
        profit          = estimated_value - price

        # Confidence: brand floor enforced (Global rule)
        confidence = 4.0
        b_strength = brand_strength(brand)
        if features["has_brand"]:
            confidence = max(confidence + 1.5, b_strength)
        else:
            confidence = max(confidence - 0.5, 1.0)   # bez brandu — niższy start

        # Fix 2 — Band Brand boost
        if features.get("band"):
            confidence += 1.5
            if features.get("is_strong_band"):   # band + vintage
                confidence += 1.0   # np. "nirvana vintage tee 90s" → extra boost
            confidence -= 1.5   # soft penalty, not block

        if features["is_vintage"]:       confidence += 1.5
        if kw(title, _CHAOS_VINTAGE_KW): confidence += 2.0
        if kw(title, _CHAOS_STYLE_KW):   confidence += 0.5

        # Rule 4 — VALUE SIGNALS boost (wool, single stitch, 90s, made in usa etc.)
        if val_count == 1:   confidence += 0.5
        elif val_count == 2: confidence += 1.0
        elif val_count >= 3: confidence += 1.5   # multiple strong signals

        # Rule 5 — SOFT_GRAIL boost: no brand but strong signals combination
        if is_soft_grail:
            confidence += 1.5
            if DEBUG_ALERTS:
                print(f"  [SOFT_GRAIL] routed: val_count={val_count} | {title[:45]}")

        # Vibe filter — FIX OVERKILL: reduce conf, NOT hard skip
        if cat == "jacket":     confidence += 1.0
        elif cat == "hoodie":   confidence += 0.5
        elif cat == "sneakers": confidence -= 0.8   # was hard -1.5, now soft
        elif cat == "tshirt" and not features["is_vintage"]:
            confidence -= 0.3   # was -0.5, now softer
        if 20 <= price <= 50:   confidence += 0.5
        confidence += freshness_boost(age) * 0.3

        _WOMENS_KW  = ["damska", "damski", "women", "woman", "damen", "femme"]
        _SPORT_ONLY = {"lotto", "kappa", "diadora", "hummel", "admiral",
                       "le coq sportif", "erima", "joma"}
        if kw(title, _WOMENS_KW) and brand in _SPORT_ONLY:
            return {**base, "_skip_reason": "womens_sport_brand"}

        _SPORT_ACT = ["rowerow", "kolarski", "cycling", "fitness",
                      "silowni", "running", "treningow"]
        if kw(title, _SPORT_ACT) and cat == "tshirt":
            return {**base, "_skip_reason": "sport_activity_tshirt"}

        # Undervaluation detection
        anomaly_score = 0
        if market_price and market_price > price:
            ratio = price / market_price
            if ratio < 0.70:
                anomaly_score = 2
                confidence   += 1.5
            elif ratio < 0.85:
                anomaly_score = 1
                confidence   += 0.5

        confidence = round(min(max(confidence, 0.0), 10.0), 2)

        if profit < 10 and anomaly_score == 0:
            return {**base, "_skip_reason": "low_profit_no_anomaly",
                    "confidence": confidence, "profit": round(profit, 2)}

        # Fix 1 — CHAOS send rule: PODNIESIONE PROGI
        # profit >= 50 AND conf >= 6.0 (normalna ścieżka)
        # Wyjątki: strong brand lub band brand obniżają próg
        is_strong_brand     = brand in STRONG_BRANDS
        is_band             = bool(features.get("band"))
        is_strong_band_feat = features.get("is_strong_band", False)

        if DEBUG_ALERTS:
            send = profit >= 15 and confidence >= 4.0
        else:
            send = (
                # Standard: wysoki profit + conf
                (profit >= 50 and confidence >= 6.0)
                # Strong brand — niższy próg
                or (profit >= 30 and is_strong_brand and confidence >= 5.0)
                # Band brand + vintage — grail-like
                or (profit >= 20 and is_band and is_strong_band_feat and confidence >= 5.0)
                # Anomaly z brand
                or (profit >= 20 and anomaly_score >= 2 and is_strong_brand)
                # Rule 5 — SOFT_GRAIL: no brand but strong value signals
                # Lower threshold to increase diversity without spam
                or (is_soft_grail and profit >= 30 and confidence >= 5.5)
            )

        # DB learning
        if cat:
            self.db.add_sample(f"chaos_{cat}", price)
        if brand and cat:
            self.db.add_sample(f"{brand}_{cat}", price)
        elif cat:
            self.db.add_sample(f"{cat}_unknown", price)
        if features["is_vintage"] and cat:
            self.db.add_sample(f"vintage_{cat}", price)

        deal_tag = "NO_DATA"
        if cat:
            db_key   = f"{brand}_{cat}" if brand else f"chaos_{cat}"
            deal_tag = self.db.get_deal_tag(db_key, price)

        if DEBUG_ALERTS:
            action = "\U0001f4e4 ALERT" if send else "\u23ed  SKIP"
            print(f"  {action}: conf={confidence:.1f} profit={profit:.0f} "
                  f"anomaly={anomaly_score} brand={brand or '\u2014'} "
                  f"strong={is_strong_brand} | {title[:45]}")

        return {
            **base,
            "send_alert":        send,
            "profit":            round(profit, 2),
            "estimated_value":   round(estimated_value, 2),
            "market_price":      round(market_price, 2) if market_price else None,
            "confidence":        confidence,
            "anomaly_score":     anomaly_score,
            "brand":             brand,
            "category":          cat,
            "is_strong_brand":   is_strong_brand,
            "is_soft_grail":     is_soft_grail,
            "value_signal_count": val_count,
            "age_min":           age,
            "deal_tag":          deal_tag,
            "_skip_reason":      None if send else "below_threshold",
        }


# Heurystyczne ceny rynkowe per brand+category (gdy brak DB)
_HEURISTIC_PRICES: dict[str, dict[str, float]] = {
    "arc'teryx":     {"jacket": 700, "hoodie": 450, "sneakers": 500, "default": 400},
    "arcteryx":      {"jacket": 700, "hoodie": 450, "default": 400},
    "arc teryx":     {"jacket": 700, "hoodie": 450, "default": 400},
    "stone island":  {"jacket": 800, "hoodie": 500, "tshirt": 350, "default": 450},
    "cp company":    {"jacket": 600, "hoodie": 400, "default": 350},
    "patagonia":     {"jacket": 500, "hoodie": 350, "default": 280},
    "supreme":       {"jacket": 600, "hoodie": 350, "tshirt": 280, "default": 300},
    "palace":        {"jacket": 500, "hoodie": 300, "tshirt": 250, "default": 250},
    "stussy":        {"jacket": 350, "hoodie": 250, "tshirt": 180, "default": 200},
    "corteiz":       {"jacket": 500, "hoodie": 300, "tshirt": 200, "default": 250},
    "broken planet": {"hoodie": 400, "tshirt": 250, "default": 300},
    "represent":     {"jacket": 600, "hoodie": 400, "tshirt": 300, "default": 350},
    "carhartt":      {"jacket": 350, "hoodie": 220, "tshirt": 130, "default": 180},
    "carhartt wip":  {"jacket": 400, "hoodie": 280, "default": 220},
    "dickies":       {"jacket": 200, "cargo": 150, "default": 120},
    "salomon":       {"sneakers": 380, "jacket": 450, "default": 280},
    "the north face":{"jacket": 400, "hoodie": 280, "default": 250},
    "tnf":           {"jacket": 400, "hoodie": 280, "default": 250},
    "helly hansen":  {"jacket": 350, "hoodie": 220, "default": 200},
    "new balance":   {"sneakers": 220, "jacket": 220, "default": 160},
    "asics":         {"sneakers": 200, "default": 150},
    "nike":          {"sneakers": 250, "jacket": 220, "hoodie": 180, "tshirt": 120, "default": 160},
    "adidas":        {"sneakers": 220, "jacket": 200, "hoodie": 160, "tshirt": 110, "default": 140},
    "levi's":        {"jeans": 160, "jacket": 220, "default": 140},
    "levis":         {"jeans": 160, "jacket": 220, "default": 140},
    "levi":          {"jeans": 150, "jacket": 200, "default": 130},
    "wrangler":      {"jeans": 130, "jacket": 180, "default": 120},
    "diesel":        {"jeans": 180, "jacket": 200, "hoodie": 150, "default": 140},
    "g-star":        {"jeans": 160, "jacket": 180, "default": 130},
    "g star":        {"jeans": 160, "jacket": 180, "default": 130},
    "ralph lauren":  {"polo": 150, "tshirt": 140, "jacket": 250, "default": 160},
    "polo ralph lauren": {"polo": 150, "tshirt": 140, "jacket": 250, "default": 160},
    "gucci":         {"jacket": 2000, "hoodie": 1500, "tshirt": 900, "default": 1200},
    "balenciaga":    {"jacket": 3000, "hoodie": 2000, "tshirt": 800, "sneakers": 2500, "default": 1500},
    "off-white":     {"jacket": 2000, "hoodie": 1200, "tshirt": 700, "default": 1000},
    "moncler":       {"jacket": 3000, "default": 2000},
    "canada goose":  {"jacket": 2500, "default": 1800},
    # Vintage basics — grail items priced by collectibility
    "screen stars":  {"tshirt": 150, "default": 120},
    "brockum":       {"tshirt": 250, "default": 200},
    "liquid blue":   {"tshirt": 200, "default": 160},
    "nutmeg":        {"tshirt": 180, "default": 150},
    "hanes":         {"tshirt": 80,  "default": 60},
    "fruit of the loom": {"tshirt": 80, "default": 60},
    "harley davidson": {"tshirt": 200, "jacket": 400, "hoodie": 250, "default": 180},
    "harley-davidson": {"tshirt": 200, "jacket": 400, "hoodie": 250, "default": 180},
    # Band brands — mid-tier pricing (Rule 1: mid-tier brand)
    # Value depends on vintage/rarity combo; base = single stitch era prices
    "nirvana":       {"tshirt": 280, "hoodie": 200, "default": 220},
    "metallica":     {"tshirt": 250, "hoodie": 180, "default": 200},
    "pink floyd":    {"tshirt": 220, "hoodie": 160, "default": 180},
    "ac/dc":         {"tshirt": 200, "hoodie": 150, "default": 160},
    "acdc":          {"tshirt": 200, "hoodie": 150, "default": 160},
    "grateful dead": {"tshirt": 350, "hoodie": 250, "default": 280},
    "led zeppelin":  {"tshirt": 220, "hoodie": 160, "default": 180},
    "rolling stones":{"tshirt": 200, "hoodie": 150, "default": 160},
    "black sabbath": {"tshirt": 200, "hoodie": 150, "default": 160},
    "wu-tang":       {"tshirt": 300, "hoodie": 220, "default": 240},
    "wu tang":       {"tshirt": 300, "hoodie": 220, "default": 240},
    "tupac":         {"tshirt": 250, "hoodie": 180, "default": 200},
    "iron maiden":   {"tshirt": 200, "hoodie": 150, "default": 160},
}


class BrandEngine:
    """
    🟣 BRAND ENGINE — brand REQUIRED, sprawdza cenę vs mediana rynkowa.

    Send rule: price < median * 0.7 AND profit >= 25
    Confidence: brand +3, category +2, good price +2.
    """

    def __init__(self, market_db: MarketDB):
        self.db       = market_db
        self._sent    = 0
        self._skipped = 0
        self._errors  = 0

    def run(self, items: list[dict], market_prices: dict | None = None) -> list[dict]:
        self._sent = self._skipped = self._errors = 0
        total = len(items)
        results = []
        market_prices = market_prices or {}
        for item in items:
            try:
                r = self._evaluate(item, market_prices)
                if r["send_alert"]:
                    results.append(r)
                    self._sent += 1
                else:
                    self._skipped += 1
            except Exception as e:
                self._errors += 1
                title = (item.get("title") or "?")[:80] if isinstance(item, dict) else "?"
                print(f"  ❌ [BRAND] ITEM ERROR: {e} | {title}")
        if DEBUG_ALERTS:
            print(f"  [BRAND] processed={total} sent={self._sent} "
                  f"skipped={self._skipped} errors={self._errors}")
        return results

    def _evaluate(self, item: dict, market_prices: dict) -> dict:
        # Part 1 — single source of truth
        features = extract_item_features(item)
        title    = item.get("title", "")
        price    = float(item.get("price") or 0)
        brand    = features["brand"]
        category = features["category"]

        base = {"engine": "BRAND", "item": item, "send_alert": False,
                "tier": "BRAND", "profit": 0, "confidence": 0,
                "brand": brand, "category": category}

        if is_foreign_title(title):
            return {**base, "_skip_reason": "foreign_language"}

        # Part 5 — brand REQUIRED (global rule: no_brand skip stays valid for BRAND engine)
        if not features["has_brand"]:
            return {**base, "_skip_reason": "no_brand"}
        if not category:
            return {**base, "_skip_reason": "no_category"}

        age = item_age_minutes(item)
        if age > MAX_ITEM_AGE_MINUTES * 4:
            return {**base, "_skip_reason": "stale"}

        median_price    = self._find_median(brand, category, market_prices)
        profit          = (median_price - price) if median_price else 0.0
        is_strong_brand = brand in STRONG_BRANDS

        # Confidence: apply brand_strength floor (Global rule)
        b_floor = brand_strength(brand)
        conf    = max(3.0, b_floor - 2.0)  # start from floor minus room to grow
        if category:
            conf += 2.0

        if median_price and median_price > 0:
            ratio = price / median_price
            if ratio < 0.50:   conf += 4.0
            elif ratio < 0.60: conf += 3.0
            elif ratio < 0.70: conf += 2.0
            elif ratio < 0.80: conf += 1.0
            else:              conf -= 1.0

        conf += freshness_boost(age) * 0.4

        # Luxury fake guard (price too low → probably fake)
        if brand in LUXURY_BRANDS and price < 100:
            conf -= 3.0

        # Undervaluation detection
        anomaly_score = 0
        if median_price and median_price > 0:
            if price < median_price * 0.70:
                anomaly_score = 2
                conf         += 1.5
            elif price < median_price * 0.85:
                anomaly_score = 1
                conf         += 0.5

        # Apply brand floor AFTER all adjustments (Global rule: min 6.0 for strong)
        if is_strong_brand:
            conf = max(conf, b_floor)

        conf = round(min(max(conf, 0.0), 10.0), 2)

        # Send rule aligned with final decision (CASE 1: profit>=40, CASE 3b: profit>=25)
        if DEBUG_ALERTS:
            send = profit >= 15
        else:
            send = (
                (is_strong_brand and profit >= 25)    # strong brand: lower bar
                or (profit >= 25 and conf >= 5.5)
                or (profit >= 15 and anomaly_score >= 2 and is_strong_brand)
            )

        # DB learning
        if category:
            self.db.add_sample(f"{brand}_{category}", price)
            self.db.add_sample(f"chaos_{category}", price)

        db_key   = f"{brand}_{category}" if category else brand
        deal_tag = self.db.get_deal_tag(db_key, price)

        if DEBUG_ALERTS:
            action = "📤 ALERT" if send else "⏭  SKIP"
            print(f"  {action}: conf={conf:.1f} profit={profit:.0f} "
                  f"anomaly={anomaly_score} brand={brand} strong={is_strong_brand} "
                  f"| {title[:45]}")

        return {
            **base,
            "send_alert":       send,
            "profit":           round(profit, 2),
            "median_price":     round(median_price, 2) if median_price else None,
            "estimated_value":  round(median_price, 2) if median_price else 0,
            "confidence":       conf,
            "anomaly_score":    anomaly_score,
            "brand":            brand,
            "category":         category,
            "is_strong_brand":  is_strong_brand,
            "age_min":          age,
            "deal_tag":         deal_tag,
            "_skip_reason":     None if send else "below_threshold",
        }

    def _find_median(self, brand: str, category: str, market_prices: dict) -> float | None:
        brand_l = brand.lower()

        # 1. bot.py market_prices — szukaj najlepszego dopasowania
        # Priorytet: exact brand match > partial match
        best_mp = None
        best_score = 0
        for mp_key, mp_val in market_prices.items():
            if not mp_val:
                continue
            key_l = mp_key.lower()
            # Exact brand in key (np. "new balance" in "New Balance 1906R")
            if brand_l in key_l:
                # Preferuj klucz bez extra słów (np. "New Balance" > "New Balance 1906R")
                score = 10 - key_l.replace(brand_l, "").count(" ")
                if score > best_score:
                    best_score = score
                    best_mp = float(mp_val)
        if best_mp:
            return best_mp

        # 2. MarketDB
        db_data = self.db.lookup_brand_category(brand, category)
        if db_data:
            v = db_data.get("median") or db_data.get("avg")
            if v:
                return float(v)

        # 3. Heurystyczna cena (zawsze dostępna dla znanych brandów)
        brand_prices = _HEURISTIC_PRICES.get(brand_l) or _HEURISTIC_PRICES.get(brand)
        if brand_prices and category:
            return float(brand_prices.get(category, brand_prices["default"]))
        if brand_prices:
            return float(brand_prices["default"])

        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🟡 GRAIL ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_GRAIL_KEYWORDS = [
    "single stitch", "made in usa", "90s", "80s", "70s",
    "tour", "promo", "band", "band tee", "movie", "film",
    "rap tee", "harley davidson", "harley", "bootleg", "concert tee",
    "deadstock", "grateful dead", "nirvana", "metallica",
    "ac/dc", "acdc", "wu-tang", "wu tang",
]

_GRAIL_BRANDS = [
    "screen stars", "hanes", "fruit of the loom", "gildan",
    "delta", "brockum", "liquid blue", "nutmeg", "anvil",
    "tultex", "jerzees", "artex", "signal sport",
    "salem sportswear", "logo 7", "chalk line",
    "russell athletic", "starter",
]


class GrailEngine:
    """
    🟡 GRAIL ENGINE — rzadkie vintage / kolekcjonerskie.

    Grail scoring: keyword_match +2, grail_brand +2, underpriced +2.
    is_grail = score >= 3.
    Send rule:   is_grail AND profit >= 10.
    """

    def __init__(self, market_db: MarketDB):
        self.db       = market_db
        self._sent    = 0
        self._skipped = 0
        self._errors  = 0

    def run(self, items: list[dict]) -> list[dict]:
        self._sent = self._skipped = self._errors = 0
        total   = len(items)
        results = []
        for item in items:
            try:
                r = self._evaluate(item)
                if r["send_alert"]:
                    results.append(r)
                    self._sent += 1
                else:
                    self._skipped += 1
            except Exception as e:
                self._errors += 1
                title = (item.get("title") or "?")[:80] if isinstance(item, dict) else "?"
                print(f"  ❌ [GRAIL] ITEM ERROR: {e} | {title}")
        if DEBUG_ALERTS:
            print(f"  [GRAIL] processed={total} sent={self._sent} "
                  f"skipped={self._skipped} errors={self._errors}")
        return results

    def _evaluate(self, item: dict) -> dict:
        features = extract_item_features(item)
        title    = item.get("title", "") or ""
        price    = float(item.get("price") or 0)
        t        = title.lower()

        base = {"engine": "GRAIL", "item": item, "send_alert": False,
                "tier": "GRAIL", "profit": 0, "confidence": 0,
                "is_grail": False, "grail_score": 0}

        if is_foreign_title(title):
            return {**base, "_skip_reason": "foreign_language"}

        age = item_age_minutes(item)
        if age > MAX_ITEM_AGE_MINUTES * 6:
            return {**base, "_skip_reason": "stale"}

        brand = features["brand"]
        cat   = features["category"]
        band  = features.get("band")

        # Fix 3 — GRAIL LOGIC PATCH
        # rarity NIE wystarcza samo w sobie.
        # Wymagane: rarity + (grail_brand OR band OR grail_category)
        _RARITY_KW = [
            "vintage", "90s", "80s", "70s", "rare", "single stitch",
            "archive", "made in usa", "deadstock",
            "band tee", "tour tee", "rap tee", "bootleg",
        ]
        _GRAIL_CATEGORIES = {"tshirt", "hoodie", "jacket"}   # tylko clothing — nie jeans/sneakers
        has_rarity      = any(r in t for r in _RARITY_KW)
        is_grail_brand  = brand in GRAIL_ELIGIBLE_BRANDS if brand else False
        is_band         = bool(band)
        is_grail_cat    = cat in _GRAIL_CATEGORIES

        # Fix 3 — Patch: grail wymaga KOMBINACJI, nie samej rzadkości
        has_grail_qualifier = is_grail_brand or is_band or (has_rarity and is_grail_cat)

        # Anti-grail: items that must NEVER qualify
        _LOW_EFFORT = [
            "basic jeans", "spodnie codzienne", "bluza zwykla",
            "koszulka zwykla", "y2k aesthetic", "y2k outfit",
        ]
        if any(le in t for le in _LOW_EFFORT):
            return {**base, "_skip_reason": "low_effort_item"}

        # Grail scoring
        score   = 0
        kw_hits = sum(1 for k in _GRAIL_KEYWORDS if k in t)
        if kw_hits >= 1:   score += 2
        if kw_hits >= 2:   score += 1

        if kw(title, _GRAIL_BRANDS):   score += 2

        if "tour"            in t: score += 1
        if "single stitch"   in t: score += 1
        if "band" in t and ("tee" in t or "shirt" in t or "tour" in t): score += 1
        if "bootleg"         in t: score += 1
        if features["is_vintage"]:     score += 1

        # Rule 4 — VALUE SIGNALS boost in grail context
        val_count = features.get("value_signal_count", 0)
        if val_count >= 1:   score += 1
        if val_count >= 3:   score += 1   # extra for multiple quality signals

        # Fix 2 — Band brand boost score
        if is_band:
            score += 2   # band = traktowany jak grail-eligible brand

        # Fix 3 — STRICT GATE: grail wymaga brand+rarity LUB band+rarity LUB silne kw
        if not has_grail_qualifier:
            # Brak qualifiera → NIGDY grail (np. generic "y2k baggy jeans")
            if DEBUG_ALERTS:
                print(f"  [QUALITY] skip_reason=no_grail_qualifier | {title[:50]}")
            return {**base, "_skip_reason": "no_grail_qualifier"}

        if is_grail_brand and has_rarity:
            is_grail_qualified = score >= 3
        elif is_band and has_rarity:
            is_grail_qualified = score >= 3   # band + vintage = grail-like
        elif is_band and kw_hits >= 1:
            is_grail_qualified = score >= 3
        elif has_rarity and kw_hits >= 2:
            is_grail_qualified = score >= 4
        elif is_grail_brand and kw_hits >= 1:
            is_grail_qualified = score >= 3
        else:
            is_grail_qualified = False

        estimated = self._estimate_value(title, price, score)
        profit    = estimated - price

        # Undervaluation
        anomaly_score = 0
        if estimated > 0 and price < estimated * 0.70:
            anomaly_score = 2
            if is_grail_qualified:
                score += 2
        elif estimated > 0 and price < estimated * 0.85:
            anomaly_score = 1
            if is_grail_qualified:
                score += 1

        is_grail = is_grail_qualified and score >= 3
        conf     = float(score) * 1.2 + freshness_boost(age) * 0.4
        # Grail brand boosts confidence floor
        if is_grail_brand:
            conf = max(conf, brand_strength(brand))
        conf = round(min(max(conf, 0.0), 10.0), 2)

        # Send rule: grail AND profit >= 10 (final decision gate raises to 50)
        if DEBUG_ALERTS:
            send = profit >= 10 and is_grail
        else:
            send = (
                (is_grail and profit >= 10)
                or (profit >= 15 and anomaly_score >= 2 and is_grail)
            )

        # DB learning
        if cat:
            self.db.add_sample(f"grail_{cat}", price)
            self.db.add_sample(f"chaos_{cat}", price)
        if features["has_brand"] and cat:
            self.db.add_sample(f"{brand}_{cat}", price)
        elif cat:
            self.db.add_sample(f"{cat}_unknown", price)

        if DEBUG_ALERTS:
            action = "\U0001f4e4 ALERT" if send else "\u23ed  SKIP"
            print(f"  {action}: conf={conf:.1f} profit={profit:.0f} "
                  f"score={score} grail={is_grail} brand={brand or '\u2014'} "
                  f"grail_brand={is_grail_brand} rarity={has_rarity} | {title[:40]}")

        return {
            **base,
            "send_alert":      send,
            "is_grail":        is_grail,
            "grail_score":     score,
            "profit":          round(profit, 2),
            "estimated_value": round(estimated, 2),
            "confidence":      conf,
            "anomaly_score":   anomaly_score,
            "brand":           brand,
            "category":        cat,
            "is_grail_brand":  is_grail_brand,
            "has_rarity":      has_rarity,
            "age_min":         age,
            "_skip_reason":    None if send else ("strict_gate" if not is_grail else "low_profit"),
        }

    def _estimate_value(self, title: str, price: float, score: int) -> float:
        t = title.lower()
        if "single stitch" in t and ("tour" in t or "band" in t):
            return max(price * 3.0, 150.0)
        if "made in usa" in t and ("tour" in t or "harley" in t):
            return max(price * 2.5, 120.0)
        if "rap tee" in t or ("90s" in t and "tour" in t):
            return max(price * 2.5, 120.0)
        if "bootleg" in t:
            return max(price * 2.0, 100.0)
        mult = 1.4 + (score * 0.15)
        return price * min(mult, 3.0)



def format_alert(result: dict) -> str:
    """Formatuje alert Telegram. Obsługuje wyniki z CHAOS, BRAND i GRAIL engine."""
    engine   = result.get("engine", "?")
    item     = result.get("item", {})
    title    = item.get("title", "")
    price    = item.get("price", 0)
    profit   = result.get("profit", 0)
    conf     = result.get("confidence", 0)
    brand    = result.get("brand") or ""
    category = result.get("category") or ""
    age_min  = result.get("age_min", 0)
    is_grail = result.get("is_grail", False)
    est_val  = result.get("estimated_value") or result.get("median_price") or 0

    clean    = re.sub(r',?\s*(marka|stan|rozmiar|brand|size|condition):.*',
                      '', title, flags=re.IGNORECASE).strip()

    if is_grail:
        header = f"💎 GRAIL  ·  score={result.get('grail_score', 0)}"
    elif result.get("is_soft_grail"):
        header = "✨ SOFT GRAIL"
    elif result.get("band"):
        header = f"🎸 BAND DEAL  ·  {result.get('band', '').upper()}"
    elif engine == "CHAOS":
        header = "🔵 CHAOS FLIP"
    elif engine == "BRAND":
        header = "🟣 BRAND DEAL"
    else:
        header = "⚪ DEAL"

    age_str = f"{age_min}min" if age_min < 360 else "?"

    lines = [
        f"{'━'*30}",
        f"{header}  ·  conf={conf:.1f}/10",
        f"{'━'*30}",
        "",
        f"📦  {clean[:90]}",
        "",
        f"💰  Cena:     {price:.0f} zł",
    ]

    if est_val and est_val > price:
        lines.append(f"📈  Wycena:   ~{est_val:.0f} zł")
        disc = (1 - price / est_val) * 100
        lines.append(f"✂️   Taniej o: {disc:.0f}%")

    if profit >= 10:
        lines.append(f"💚  Profit:   ~{profit:.0f} zł")

    meta = []
    if brand:      meta.append(f"🏷 {brand}")
    if category:   meta.append(f"📂 {category}")
    if age_str != "?": meta.append(f"⏱ {age_str}")
    if meta:
        lines.append("  ·  ".join(meta))

    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🏗️ ENGINE FACADE — backward compatibility z bot.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Engine:
    """
    Fasada zachowująca 100% kompatybilność z bot.py.
    Stary interfejs: engine.evaluate(item, search, market_price)
    Nowy interfejs:  engine.run_cycle(items, market_prices) → list[dict]
    """

    def __init__(self, anthropic_key: str | None = None):
        self.anthropic_key = anthropic_key
        self.db     = MarketDB()
        self.chaos  = ChaosEngine(self.db)
        self.brand  = BrandEngine(self.db)
        self.grail  = GrailEngine(self.db)
        # Legacy stubs
        self.raw      = type("_R", (), {"items": []})()
        self.ai_cache = type("_C", (), {"cache": {}})()
        self.learner  = type("_L", (), {"data": {"clicked": [], "bought": []}})()
        self._alerted_ids: set[str] = set()
        print(f"🧠 Engine v2.0 zainicjowany | DB: {len(self.db.db)} grup | "
              f"Silniki: CHAOS + BRAND + GRAIL | AI: {'✅' if anthropic_key else '❌'}")

    def run_cycle(self, items: list[dict], market_prices: dict | None = None) -> list[dict]:
        """
        Uruchamia wszystkie 3 silniki i zwraca deduplikowane wyniki.
        Part 3: auto-save DB po każdym cyklu.
        """
        chaos_r = self.chaos.run(items)
        brand_r = self.brand.run(items, market_prices)
        grail_r = self.grail.run(items)
        all_r   = chaos_r + brand_r + grail_r

        # Part 3 — zapisz DB po cyklu (throttled — max co 5 min)
        self.db.save()

        # Deduplikacja po item_id — zachowaj wersję z najwyższym profit
        best: dict[str, dict] = {}
        for r in all_r:
            item_id = str(r["item"].get("id", ""))
            if not item_id:
                continue
            if item_id not in best or r.get("profit", 0) > best[item_id].get("profit", 0):
                best[item_id] = r

        deduped = sorted(
            [r for r in best.values() if r.get("send_alert")],
            key=lambda x: -x.get("profit", 0)
        )

        brand_counts: dict[str, int] = {}
        final = []
        for r in deduped:
            item_id  = str(r["item"].get("id", ""))
            is_grail = r.get("is_grail", False)
            if item_id and item_id in self._alerted_ids and not is_grail:
                continue

            brand = r.get("brand") or ""
            if brand and not is_grail:
                count = brand_counts.get(brand, 0)
                if count >= 2:
                    continue
                brand_counts[brand] = count + 1

            if item_id:
                self._alerted_ids.add(item_id)
            final.append(r)

        if len(self._alerted_ids) > 10_000:
            self._alerted_ids = set(list(self._alerted_ids)[-5_000:])

        return final

    # ── SINGLE ENTRY POINT (Requirement 1) ──────────────
    def evaluate_and_decide(self, item: dict, market_prices: dict | None = None) -> dict:
        """
        JEDYNY punkt decyzyjny — każdy item MUSI przez to przejść.
        Uruchamia wszystkie 3 silniki, agreguje, podejmuje decyzję.

        Returns:
          send     : bool
          engine   : str (winning engine)
          reason   : str
          profit   : float
          confidence: float
          ... (pola z wygrywającego silnika)
        """
        market_prices = market_prices or {}
        title = ""
        try:
            title = str(item.get("title") or "")
        except Exception:
            pass

        # ── Requirement 2: HARD FILTERS (przed jakimkolwiek silnikiem) ──
        _HARD_TRASH = [
            "blouse", "bluzka", "sukienka", "dress",
            "crop top", "bikini", "bra ", "stanik",
            "swimsuit", "bodysuit", "leggings", "legginsy",
            "tights", "rajstopy", "coquette", "cute ",
            "kombinezon damski",
        ]
        tl = title.lower()
        for trash in _HARD_TRASH:
            if trash in tl:
                return {
                    "send": False, "engine": None,
                    "reason": f"hard_filter:{trash}",
                    "profit": 0, "confidence": 0,
                    "item": item, "send_alert": False,
                }

        if is_foreign_title(title):
            return {
                "send": False, "engine": None,
                "reason": "foreign_language",
                "profit": 0, "confidence": 0,
                "item": item, "send_alert": False,
            }

        # ── Requirement 3: RUN ALL THREE ENGINES ──────────
        try:
            c_result = self.chaos._evaluate(item)
        except Exception as e:
            print(f"  ❌ [evaluate_and_decide] CHAOS error: {e} | {title[:60]}")
            c_result = {"send_alert": False, "profit": 0, "confidence": 0, "engine": "CHAOS"}

        try:
            b_result = self.brand._evaluate(item, market_prices)
        except Exception as e:
            print(f"  ❌ [evaluate_and_decide] BRAND error: {e} | {title[:60]}")
            b_result = {"send_alert": False, "profit": 0, "confidence": 0, "engine": "BRAND"}

        try:
            g_result = self.grail._evaluate(item)
        except Exception as e:
            print(f"  ❌ [evaluate_and_decide] GRAIL error: {e} | {title[:60]}")
            g_result = {"send_alert": False, "profit": 0, "confidence": 0, "engine": "GRAIL"}

        # ── Requirement 4: AGGREGATION ─────────────────────
        # ── AGGREGATION: Hierarchy BRAND > GRAIL > CHAOS (Global rule 2) ──
        # BRAND wins if brand is strong AND brand engine returned a result
        # GRAIL wins next if is_grail qualifies
        # CHAOS is fallback
        brand_name  = b_result.get("brand")
        is_strong   = b_result.get("is_strong_brand", False) or (
            brand_name in STRONG_BRANDS if brand_name else False
        )
        is_grail    = g_result.get("is_grail", False)

        # Apply hierarchy strictly
        if features_brand := detect_brand(title):
            # Brand exists → BRAND layer is authoritative for brand strength
            if not is_strong:
                # Brand detected but not STRONG_BRANDS → downgrade
                b_result = dict(b_result)
                b_result["confidence"] = min(b_result.get("confidence", 0), 5.0)

        # Select engine by hierarchy
        if is_strong and b_result.get("confidence", 0) >= 6.0:
            best_name = "BRAND"
            best      = dict(b_result)
        elif is_grail and g_result.get("is_grail_brand", False) or (
             is_grail and g_result.get("has_rarity", False)):
            best_name = "GRAIL"
            best      = dict(g_result)
        elif b_result.get("confidence", 0) > 0 and b_result.get("_skip_reason") not in ("no_brand", "no_category"):
            # Non-strong brand but brand engine produced result
            best_name = "BRAND"
            best      = dict(b_result)
        elif c_result.get("confidence", 0) > 0:
            best_name = "CHAOS"
            best      = dict(c_result)
        else:
            # Fallback: pick highest confidence
            best_name, best = max(
                [("GRAIL", g_result), ("BRAND", b_result), ("CHAOS", c_result)],
                key=lambda x: x[1].get("confidence", 0)
            )
            best = dict(best)

        best["engine"] = best_name

        profit     = best.get("profit", 0)
        confidence = best.get("confidence", 0)
        is_grail   = best.get("is_grail", False)
        brand_name = best.get("brand")

        # ── Debug log: all 3 engines ──────────────────────
        if DEBUG_ALERTS:
            c_s = c_result.get("confidence", 0)
            b_s = b_result.get("confidence", 0)
            g_s = g_result.get("confidence", 0)
            c_p = c_result.get("profit", 0)
            b_p = b_result.get("profit", 0)
            g_p = g_result.get("profit", 0)
            g_is = g_result.get("is_grail", False)
            c_r = c_result.get("_skip_reason", "—")
            b_r = b_result.get("_skip_reason", "—")
            print(f"  [SCORE] {title[:45]}")
            print(f"    CHAOS: conf={c_s:.1f} profit={c_p:.0f} skip={c_r}")
            print(f"    BRAND: conf={b_s:.1f} profit={b_p:.0f} skip={b_r} strong={is_strong}")
            print(f"    GRAIL: conf={g_s:.1f} profit={g_p:.0f} grail={g_is} "
                  f"brand={g_result.get('is_grail_brand')} rarity={g_result.get('has_rarity')}")
            print(f"    WINNER: {best_name}")

        # Failsafe: no engine returned a valid score
        if all(r.get("confidence", 0) == 0 for r in [c_result, b_result, g_result]):
            return {
                "send": False, "engine": None,
                "reason": "no_valid_score",
                "profit": 0, "confidence": 0,
                "item": item, "send_alert": False,
            }

        # ── FINAL DECISION RULES (spec-compliant) ─────────
        send   = False
        reason = "below_threshold"

        if DEBUG_ALERTS:
            # Debug mode: lower thresholds to see what flows
            if is_grail and profit >= 10:
                send   = True
                reason = f"grail_debug(score={best.get('grail_score',0)})"
            elif is_strong and profit >= 20:
                send   = True
                reason = f"brand_strong_debug(profit={profit:.0f})"
            elif profit >= 20 and confidence >= 5.0:
                send   = True
                reason = f"flip_debug(profit={profit:.0f},conf={confidence:.1f})"
            elif confidence > 0:
                reason = f"fallback_candidate(conf={confidence:.1f},profit={profit:.0f})"
        else:
            # CASE 1: Strong brand AND profit >= 40 → SEND (priority HIGH)
            if is_strong and profit >= 40:
                send   = True
                reason = f"brand_strong(profit={profit:.0f},conf={confidence:.1f})"

            # CASE 2: Grail AND profit >= 50 → SEND
            elif is_grail and profit >= 50:
                send   = True
                reason = f"grail(score={best.get('grail_score',0)},profit={profit:.0f})"

            # CASE 3: Chaos (or non-strong brand) AND profit >= 30 → SEND
            elif best_name == "CHAOS" and profit >= 30 and confidence >= 5.0:
                send   = True
                reason = f"chaos_flip(profit={profit:.0f},conf={confidence:.1f})"

            # CASE 3b: Brand (non-strong) AND profit >= 25
            elif best_name == "BRAND" and profit >= 25 and confidence >= 5.5:
                send   = True
                reason = f"brand_deal(profit={profit:.0f},conf={confidence:.1f})"

            # Fallback candidate (for run_cycle_strict TOP-1)
            elif confidence > 0:
                reason = f"fallback_candidate(conf={confidence:.1f},profit={profit:.0f})"

        if DEBUG_ALERTS:
            action = "📤 SEND" if send else "⏭  SKIP"
            print(f"  [{best_name}] {action} | "
                  f"conf={confidence:.1f} profit={profit:.0f} "
                  f"grail={is_grail} brand={brand_name or '—'} "
                  f"strong={is_strong} | reason={reason}")

        return {
            **best,
            "send":       send,
            "send_alert": send,
            "reason":     reason,
            "engine":     best_name,
        }

    def run_cycle_strict(self, items: list[dict], market_prices: dict | None = None) -> list[dict]:
        """
        Strict pipeline — każdy item przez evaluate_and_decide.
        Task 3: obniżone progi.
        Task 4: fallback TOP 1 gdy wszystkie odrzucone.
        Task 5: deduplikacja po item_id.
        Task 6: auto-save DB.
        """
        market_prices = market_prices or {}
        total      = len(items)
        processed  = 0
        results    = []
        fallbacks  = []   # Task 4 — kandydaci fallback

        for item in items:
            try:
                r = self.evaluate_and_decide(item, market_prices)
                processed += 1
                if r.get("send"):
                    results.append(r)
                elif r.get("confidence", 0) > 0:
                    # Task 4 — zachowaj jako fallback kandydata
                    fallbacks.append(r)
            except Exception as e:
                processed += 1
                title = str(item.get("title", "?"))[:80] if isinstance(item, dict) else "?"
                print(f"  ❌ ITEM ERROR: {e} | {title}")

        # Task 2 — pipeline metrics
        print(f"  📊 Processed: {processed}/{total} | Accepted: {len(results)} | Fallbacks: {len(fallbacks)}")

        # Task 4 — fallback: jeśli 0 zaakceptowanych → wyślij TOP 1 po confidence
        if not results and fallbacks:
            fallbacks.sort(key=lambda r: -(r.get("confidence", 0) + r.get("profit", 0)))
            top1 = fallbacks[0]
            top1["send"]       = True
            top1["send_alert"] = True
            top1["reason"]     = f"top1_fallback(conf={top1.get('confidence',0):.1f})"
            results = [top1]
            print(f"  ⚠️ FALLBACK TOP1: {top1.get('item',{}).get('title','?')[:50]} "
                  f"| conf={top1.get('confidence',0):.1f}")

        # Task 9: sort by profit+confidence DESC, limit 10
        results.sort(key=lambda r: -(r.get("profit", 0) + r.get("confidence", 0)))

        # Task 5 — dedup po item_id (prevent same item multiple times)
        brand_counts: dict[str, int] = {}
        final    = []
        sent_ids = set()   # Task 5: lokalny set per-cykl (nie tylko sesyjny)

        for r in results:
            item_id  = str(r.get("item", {}).get("id", ""))
            is_grail = r.get("is_grail", False)

            # Task 5 — dedup: sprawdź ZARÓWNO sesyjny set jak i lokalny
            if item_id and item_id in sent_ids:
                continue
            if item_id and item_id in self._alerted_ids and not is_grail:
                continue

            brand = r.get("brand") or ""
            if brand and not is_grail:
                if brand_counts.get(brand, 0) >= 2:
                    continue
                brand_counts[brand] = brand_counts.get(brand, 0) + 1

            if item_id:
                sent_ids.add(item_id)
                self._alerted_ids.add(item_id)
            final.append(r)
            if len(final) >= 10:
                break

        if len(self._alerted_ids) > 10_000:
            self._alerted_ids = set(list(self._alerted_ids)[-5_000:])

        # Task 6 — auto-save DB po każdym cyklu
        self.db.save(force=True)
        print(f"  💾 MarketDB saved: {len(self.db.db)} grup → {DB_FILE}")

        return final

    def evaluate(self, item: dict, search: dict, market_price: float | None) -> dict:
        """
        Legacy evaluate() — deleguje do evaluate_and_decide().
        Zachowane dla backward compatibility.
        """
        mps = {search.get("name", ""): market_price} if market_price else {}
        result = self.evaluate_and_decide(item, mps)
        return self._to_legacy(result)

    def _to_legacy(self, r: dict) -> dict:
        """Konwertuje wynik silnika do formatu legacy."""
        item  = r.get("item", {})
        price = item.get("price", 0)
        est   = r.get("estimated_value", 0) or r.get("median_price", 0) or price * 1.6
        return {
            "send_alert":      r.get("send_alert", False),
            "tier":            r.get("tier"),
            "confidence":      r.get("confidence", 0),
            "scoring": {
                "confidence":     r.get("confidence", 0),
                "flip_profit":    r.get("profit", 0),
                "db_score":       0, "market_score": 0, "ai_score": 0,
                "fake_risk":      False, "trend": "stable",
                "vintage_score":  0, "football_score": 0,
                "deal_score":     0, "deal_tag": "WEAK",
                "anomaly_score":  0, "effective_price": price,
                "p25":            None, "market_price_db": r.get("median_price"),
            },
            "ai_data": {
                "decision": "BUY" if r.get("send_alert") else "WATCH",
                "final_score": min(r.get("confidence", 5), 10),
                "hype_score": 5, "rarity": 5,
                "estimated_value": est,
            },
            "db_data":         None,
            "brand":           r.get("brand"),
            "category":        r.get("category"),
            "flip_profit":     r.get("profit", 0),
            "item":            item,
            "market_price":    r.get("median_price"),
            "is_grail":        r.get("is_grail", False),
            "grail_score":     r.get("grail_score", 0),
            "deal_tag":        "GOOD" if r.get("send_alert") else "WEAK",
            "flip_speed":      "FAST" if r.get("age_min", 999) <= 30 else "MEDIUM",
            "item_age_min":    r.get("age_min", 360),
            "undervalue_ratio": (price / est) if est > 0 else 1.0,
            "freshness_tier":  "ULTRA" if r.get("age_min", 999) <= 10 else "FRESH",
            "_engine":         r.get("engine", "?"),
        }

    def format_alert(self, result: dict) -> str:
        """
        Formatuje alert. Obsługuje wyniki z:
        - run_cycle() — wyniki bezpośrednio z silników (mają klucz 'engine')
        - evaluate()  — legacy wyniki (mają klucz '_engine')
        """
        # run_cycle output — ma klucz 'engine' bezpośrednio
        if result.get("engine") in ("CHAOS", "BRAND", "GRAIL"):
            return format_alert(result)

        # legacy evaluate() output — ma klucz '_engine'
        eng  = result.get("_engine", "CHAOS")
        item = result.get("item", {})
        return format_alert({
            "engine":          eng,
            "item":            item,
            "profit":          result.get("flip_profit", 0),
            "confidence":      result.get("confidence", 0),
            "brand":           result.get("brand"),
            "category":        result.get("category"),
            "age_min":         result.get("item_age_min", 0),
            "is_grail":        result.get("is_grail", False),
            "grail_score":     result.get("grail_score", 0),
            "estimated_value": result.get("ai_data", {}).get("estimated_value", 0),
            "median_price":    result.get("market_price"),
            "tier":            result.get("tier"),
        })

    def stats(self) -> str:
        db_count = len(self.db.db)
        db_dirty = "dirty" if self.db._dirty else "clean"
        return (
            f"🧠 Engine v2.0 stats:\n"
            f"  DB groups:   {db_count} ({db_dirty})\n"
            f"  DB file:     {DB_FILE}\n"
            f"  Raw items:   0 (chaos data in DB)\n"
            f"  AI cache:    0\n"
            f"  Clicked:     0\n"
            f"  Bought:      0"
        )

    def record_click(self, *args): pass
    def record_buy(self, *args):   pass


# Re-export so bot.py can import directly
__all__ = [
    "Engine", "MarketDB", "ChaosEngine", "BrandEngine", "GrailEngine",
    "format_alert", "extract_item_features",
    "detect_brand", "detect_band", "detect_category", "is_foreign_title",
    "has_value_signals", "count_value_signals",
    "BAND_BRANDS", "VALUE_SIGNALS", "STRONG_BRANDS",
    "GRAIL_ELIGIBLE_BRANDS",
]
