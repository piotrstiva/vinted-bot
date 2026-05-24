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

DEBUG_ALERTS    = os.getenv("DEBUG_ALERTS", "1") == "1"
VERBOSE_ITEM_DEBUG = os.getenv("VERBOSE_ITEM_DEBUG", "0") == "1"
NO_MARKET_DATA_CAP_LOG_LIMIT = int(os.getenv("NO_MARKET_DATA_CAP_LOG_LIMIT", "10"))
WATCH_ALERTS_ENABLED = os.getenv("WATCH_ALERTS_ENABLED", "0") == "1"
WATCH_MAX_PER_CYCLE = int(os.getenv("WATCH_MAX_PER_CYCLE", "2"))
TASTE_WATCH_ENABLED = os.getenv("TASTE_WATCH_ENABLED", "1") == "1"
TASTE_WATCH_SEND_ENABLED = os.getenv("TASTE_WATCH_SEND_ENABLED", "0") == "1"
TASTE_WATCH_MAX_PER_CYCLE = int(os.getenv("TASTE_WATCH_MAX_PER_CYCLE", "2"))
DEBUG_PIPELINE  = os.getenv("DEBUG_PIPELINE", "0") == "1"   # Part 7 — verbose pipeline log


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🧠 PART 1 — CENTRAL FEATURE EXTRACTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NO_MARKET_DATA_CAP_STATS = {
    "count": 0,
    "examples": [],
}


def reset_no_market_data_cap_stats():
    NO_MARKET_DATA_CAP_STATS["count"] = 0
    NO_MARKET_DATA_CAP_STATS["examples"] = []


def log_no_market_data_cap(title: str, real_signal_hits: list):
    NO_MARKET_DATA_CAP_STATS["count"] += 1
    if len(NO_MARKET_DATA_CAP_STATS["examples"]) < 5:
        NO_MARKET_DATA_CAP_STATS["examples"].append(str(title or "")[:60])
    if VERBOSE_ITEM_DEBUG or NO_MARKET_DATA_CAP_STATS["count"] <= NO_MARKET_DATA_CAP_LOG_LIMIT:
        print(f"  [NO_MARKET_DATA_CAP] title={str(title or '')[:60]} confidence_cap=5.5 real_signals={real_signal_hits}")


def print_no_market_data_cap_summary():
    count = int(NO_MARKET_DATA_CAP_STATS.get("count") or 0)
    if count:
        print(f"[NO_MARKET_DATA_CAP_SUMMARY] count={count} examples={NO_MARKET_DATA_CAP_STATS.get('examples', [])}")


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
        _band_raw   = detect_band(title)
        is_strong_band = bool(_band_raw and is_vintage)

        feat = {
            "brand":         brand,
            "has_brand":     brand is not None,
            "is_vintage":    is_vintage,
            "category":      category,
            "keywords":      tags,
            "band":          _band_raw,           # Fix 2
            "is_strong_band": is_strong_band,     # Fix 2
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
    # Denim — spec DENIM_KEYWORDS
    "diesel", "g-star", "g star", "true religion",
    "replay", "roca wear", "rocawear", "evisu",
    # Outdoor / lifestyle
    "the north face", "tnf",
    "columbia", "helly hansen",
    "columbia sportswear",
    # Classic / preppy
    "ralph lauren", "polo ralph lauren",
    "lacoste", "fred perry", "champion",
    "tommy hilfiger", "calvin klein",
    "nautica", "izod",
    # Luxury
    "gucci", "louis vuitton", "prada",
    "hermes", "balenciaga", "versace",
    "burberry", "fendi", "dior",
    "off-white", "stone island",
    "moncler", "canada goose", "moose knuckles",
    # Football
    "umbro", "kappa", "lotto", "diadora",
    "hummel", "admiral", "le coq sportif",
    "erima", "joma",
    # Harley — all variations (spec HARLEY_KEYWORDS)
    "harley davidson", "harley-davidson",
    "harley tee", "harley vintage", "harley",
    # Vintage basics
    "screen stars", "hanes beefy", "hanes",
    "fruit of the loom", "gildan", "delta",
    "brockum", "liquid blue", "nutmeg",
    "anvil", "tultex",
    "salem sportswear", "russell athletic",
    "starter", "jerzees", "artex",
    "signal sport", "logo 7", "chalk line",
    # Band names — spec BAND_KEYWORDS (detect_brand picks them up)
    "nirvana", "metallica", "ramones", "acdc", "ac/dc",
    "pink floyd", "slipknot", "grateful dead",
    "led zeppelin", "black sabbath", "iron maiden",
    "rolling stones", "david bowie",
    "pearl jam", "soundgarden", "alice in chains",
    "rage against", "system of a down",
    "sex pistols", "the clash",
], key=len, reverse=True)

LUXURY_BRANDS = {
    "gucci", "louis vuitton", "prada", "hermes", "balenciaga",
    "versace", "burberry", "fendi", "dior", "off-white",
    "moncler", "canada goose", "moose knuckles",
}

# Brands that guarantee minimum confidence 6.0 when detected
STRONG_BRANDS = {
    "patagonia",
    "supreme", "palace", "stussy", "bape",
    "fear of god", "essentials",
    "carhartt",
    "helly hansen",
    "asics",
    "levi's", "levis", "levi", "wrangler", "diesel",
    "ralph lauren", "polo ralph lauren",
    "gucci", "louis vuitton", "prada", "hermes",
    "balenciaga", "versace", "burberry", "fendi", "dior",
    "off-white", "moncler", "canada goose",
    # Harley — all spec variants
    "harley davidson", "harley-davidson",
    # Denim — spec
    "true religion", "roca wear", "rocawear",
}

# ── Task 1: Brand tiers ───────────────────────────────
# BLOCKED: reject immediately, no evaluation
BLOCKED_BRANDS = {
    "corteiz", "crtz",   # removed from STRONG — high hype, low real margin on Vinted
}

# LOW_ROI: penalise confidence + final_score, reject if no pattern
LOW_ROI_BRANDS = {
    "essentials", "fear of god essentials",
    "zara", "h&m", "shein",
    "bershka", "sinsay", "reserved", "primark",
    "pull&bear", "pull bear", "stradivarius",
    "romwe", "cider", "boohoo", "temu",
}
GRAIL_ELIGIBLE_BRANDS = {
    # Vintage basics / print shops
    "screen stars", "hanes beefy", "hanes",
    "fruit of the loom", "gildan", "delta",
    "brockum", "liquid blue", "nutmeg", "anvil",
    "tultex", "salem sportswear", "russell athletic",
    "starter", "jerzees", "artex", "signal sport",
    # Heritage / workwear with collector value
    "carhartt", "levi's", "levis", "levi",
    "wrangler", "ben davis",
    # Harley — all spec variants
    "harley davidson", "harley-davidson", "harley",
    # Band names — grail-eligible when + rarity (spec BAND_KEYWORDS)
    "nirvana", "metallica", "ramones", "acdc", "ac/dc",
    "pink floyd", "slipknot", "grateful dead",
    "led zeppelin", "black sabbath", "iron maiden",
    "rolling stones", "david bowie",
    "pearl jam", "soundgarden",
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🎸 KEYWORD GROUPS (spec)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VINTAGE_SIGNALS = [
    "single stitch", "made in usa", "all over print", "aop",
    "screen stars", "hanes beefy", "giant tag", "fruit of the loom usa",
    "made in the usa", "made in u.s.a", "deadstock", "nos",
]

BAND_KEYWORDS = [
    "nirvana", "metallica", "ramones", "acdc", "ac/dc",
    "pink floyd", "slipknot", "grateful dead",
    "led zeppelin", "black sabbath", "iron maiden",
    "rolling stones", "david bowie", "pearl jam",
    "soundgarden", "alice in chains", "sex pistols",
    "rage against", "system of a down", "korn",
    "rammstein", "deftones", "tool", "pantera", "megadeth",
    "the clash", "biggie", "eminem", "the strokes",
]

HARLEY_KEYWORDS = [
    "harley davidson", "harley-davidson",
    "harley tee", "harley vintage", "harley",
    "daytona", "sturgis", "bike week",
    "flame", "skull", "eagle",
]

DENIM_KEYWORDS = [
    "diesel", "levis", "levi's", "levi", "carhartt",
    "true religion", "g star", "g-star", "roca wear", "rocawear",
]

RARITY_KEYWORDS = [
    "rare", "deadstock", "nos", "archive", "sample", "og",
    "promo", "unreleased", "limited", "one of a kind", "1/1",
    "1st press", "first press",
]

LOW_EFFORT = [
    "y2k aesthetic", "clean girl", "soft girl",
    "basic", "vintage style", "vintage vibe",
    "aesthetic", "cottagecore", "indie kid", "dark academia",
]

# Band brand list — synced with BAND_KEYWORDS
BAND_BRANDS = BAND_KEYWORDS[:]   # same list, different name for legacy compatibility

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🚫 FAKE VINTAGE DETECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Fast fashion brands that produce cheap licensed band reprints
FAST_FASHION_BRANDS = {
    "h&m", "hm", "bershka", "pull&bear", "pull bear",
    "zara", "primark", "cropp", "sinsay", "house",
    "c&a", "new yorker", "divided", "topshop",
    "shein", "romwe", "cider", "boohoo", "temu",
    "fashion nova", "urban outfitters basic",
}

# Signals that indicate a genuine vintage band tee
AUTHENTICITY_SIGNALS = [
    "single stitch", "made in usa", "made in u.s.a",
    "faded", "90s", "80s", "70s", "giant", "giant tag",
    "brockum", "screen stars", "fruit of the loom usa",
    "hanes beefy", "all over print", "aop", "tour",
    "concert tee", "concert shirt", "original",
    "deadstock", "nos", "1st press", "first press",
    "licensed", "winterland", "fruit of the loom vintage",
    "tour dates", "cracked print", "paper thin", "2000", "2000s",
]

# Reprint/fast-fashion signals that invalidate band tee authenticity
REPRINT_SIGNALS = [
    "primark", "h&m", "hm brand", "modern fit", "slim fit",
    "new collection", "licensed tee", "licensed product",
    "officially licensed", "divided", "fast fashion",
    "high street", "retail tag", "store tag",
]


def detect_fake_vintage(
    title: str,
    brand: str | None,
    band: str | None,
    confidence: float,
    pattern_score: int,
    is_grail: bool,
) -> dict:
    """
    Detects fake/reprint vintage band tees.

    Returns dict with:
      - is_fake_vintage  : bool
      - confidence       : adjusted float
      - pattern_score    : adjusted int
      - is_grail         : adjusted bool
      - reject           : bool  (confidence dropped below 5)
      - reason           : str
      - cap_engine       : str | None  (force max engine tier)
      - cap_confidence   : float | None
    """
    t = title.lower()
    result = {
        "is_fake_vintage": False,
        "confidence":      confidence,
        "pattern_score":   pattern_score,
        "is_grail":        is_grail,
        "reject":          False,
        "reason":          None,
        "cap_engine":      None,
        "cap_confidence":  None,
    }

    if not band:
        return result   # nie jest band tee → nie sprawdzamy

    # ── Rule 1: band + fast fashion brand → fake reprint ─────────────
    brand_lower = (brand or "").lower()
    is_ff_brand = brand_lower in FAST_FASHION_BRANDS or \
                  any(ff in t for ff in FAST_FASHION_BRANDS)

    if is_ff_brand:
        result["is_fake_vintage"]  = True
        result["is_grail"]         = False
        result["confidence"]       = confidence - 4.0
        result["pattern_score"]    = max(pattern_score - 3, 0)
        result["reason"]           = "fake_vintage_fast_fashion"
        if result["confidence"] < 5.0:
            result["reject"] = True
        if DEBUG_ALERTS:
            print(f"  [FAKE_VINTAGE] {result['reason']} "
                  f"conf:{confidence:.1f}→{result['confidence']:.1f} | {title[:50]}")
        return result

    # ── Rule 2: band tee — require authenticity signal ────────────────
    auth_hits = [a for a in AUTHENTICITY_SIGNALS if a in t]
    has_auth = len(set(auth_hits)) >= 2

    if not has_auth:
        # No authenticity signal → cap engine to CHAOS, cap confidence to 6.0
        result["cap_engine"]      = "CHAOS"
        result["cap_confidence"]  = 6.0
        result["confidence"]      = min(confidence, 6.0)
        result["is_grail"]        = False
        result["pattern_score"]   = max(pattern_score - 2, 0)
        result["reason"]          = "band_tee_auth_signals_lt_2"
        if DEBUG_ALERTS:
            print(f"  [FAKE_VINTAGE] {result['reason']} "
                  f"→ cap CHAOS/conf≤6.0 | {title[:50]}")
        return result

    # ── Rule 3: band + reprint signal → confidence penalty ───────────
    has_reprint = any(r in t for r in REPRINT_SIGNALS)

    if has_reprint:
        result["is_grail"]   = False
        result["confidence"] = confidence - 3.0
        result["reason"]     = "band_tee_reprint_signal"
        if DEBUG_ALERTS:
            print(f"  [FAKE_VINTAGE] {result['reason']} "
                  f"conf:{confidence:.1f}→{result['confidence']:.1f} | {title[:50]}")
        return result

    return result


def detect_band(title: str) -> str | None:
    """
    Wykrywa band brand w tytule.
    Jeśli wykryty → traktowany jak brand (has_brand=True, strong=True gdy vintage).
    """
    t = title.lower()
    for band in BAND_BRANDS:
        if band in t:
            return band
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🎯 PATTERN SCORING (spec — core system)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AESTHETIC_SPAM_KEYWORDS = [
    "aesthetic", "soft girl", "coquette", "grunge aesthetic",
    "y2k aesthetic", "fairycore", "tiktok", "vintage style",
    "retro style", "streetwear aesthetic",
]

AUTHENTICITY_PENALTY_PHRASES = [
    "y2k aesthetic", "grunge aesthetic", "streetwear aesthetic",
    "vintage style", "retro style",
]

SIGNAL_TIER_BOOSTS = {
    "TIER_S": 35,
    "TIER_A": 15,
    "TIER_B": 0,
    "TIER_C": -40,
}

TIER_PRIORITY = {
    "TIER_S": 4,
    "TIER_A": 3,
    "TIER_B": 2,
    "TIER_C": 1,
}

ENGINE_PRIORITY = {
    "GRAIL": 3,
    "BRAND": 2,
    "CHAOS": 1,
}

DESIRABLE_OUTDOOR = [
    "gore-tex", "goretex", "gtx", "summit series", "hyvent",
    "dryvent", "nuptse", "mountain jacket", "shell jacket",
    "technical jacket",
    "softshell", "hard shell", "windstopper", "polartec",
]

DESIRABLE_NIKE = [
    "acg", "nike acg", "tn", "air max 95", "air max plus",
    "shox", "vintage nike", "90s nike", "00s nike",
    "center swoosh", "mini swoosh", "spellout", "nylon jacket",
]

DESIRABLE_ADIDAS = [
    "spezial", "samba", "gazelle", "equipment", "eqt",
    "adidas adventure", "adidas originals", "trefoil",
    "football shirt", "track jacket", "vintage adidas", "90s adidas",
]

DESIRABLE_DENIM = [
    "bootcut", "flare", "flared", "low rise", "baggy",
    "selvedge", "raw denim", "made in usa", "big e",
    "orange tab", "japanese denim", "jorts",
]

DESIRABLE_VINTAGE = [
    "single stitch", "made in usa", "all over print", "aop",
    "screen stars", "brockum", "giant tag", "liquid blue",
    "fruit of the loom usa", "hanes beefy", "deadstock",
    "tour", "back print", "cracked print", "paper thin",
]

DESIRABLE_HARLEY = [
    "sturgis", "daytona", "bike week", "flame", "skull",
    "eagle", "3d emblem", "waffle", "thermal", "longsleeve",
    "single stitch", "made in usa", "faded", "distressed",
]

HARLEY_STRONG_ITEM_SIGNALS = [
    "waffle", "thermal", "longsleeve", "long sleeve",
    "sturgis", "daytona", "bike week",
    "flame", "skull", "eagle", "3d emblem",
    "single stitch", "made in usa",
    "faded", "distressed", "back print",
    "embroidered", "embroidery",
]

HARLEY_WEAK_GENERIC_TYPES = [
    "women", "women's", "womens", "damska", "damski",
    "top", "tank", "v neck", "button up", "button-up",
    "shirt", "tee", "t-shirt", "koszulka",
]

CARHARTT_HIGH_VALUE_MODELS = [
    "detroit", "active jacket", "active jac", "michigan coat",
    "chore coat", "santa fe", "duck jacket", "duck canvas",
    "double knee", "aviation pant", "simple pant", "master pant",
    "cargo pant", "carpenter pant", "work pant",
]

DESIRABLE_DESIGNER = [
    "made in italy", "archive", "runway", "sample",
    "mesh", "asymmetrical", "all over print", "aop",
    "silk", "leather", "mohair", "wool", "cashmere",
    "gaultier", "helmut lang", "jil sander", "margiela",
    "cavalli", "dolce gabbana", "d&g", "yohji", "issey miyake",
    "comme des garcons", "vivienne westwood",
]

GENERIC_LOW_DESIRABILITY = [
    "basic", "plain", "simple", "casual", "regular fit",
    "everyday", "soft girl", "clean girl", "coquette",
    "aesthetic", "vintage style", "retro style",
    "ordinary", "classic basic",
]

CONDITIONAL_STRONG_BRANDS = [
    "nike", "adidas", "asics",
    "the north face", "tnf", "columbia",
    "helly hansen", "puma", "reebok",
]

DESIRABLE_CARHARTT = [
    "detroit", "detroit jacket", "active jacket", "active jac",
    "michigan coat", "chore coat", "santa fe", "duck canvas",
    "duck jacket", "duck vest", "workwear jacket", "double knee",
    "double knees", "single knee", "aviation pant", "simple pant",
    "master pant", "cargo pant", "cargo pants", "carpenter pant",
    "carpenter pants", "painter pant", "painter pants", "work pant",
    "work pants", "vest", "hoodie", "crewneck", "sweatshirt",
    "zip hoodie", "half zip", "quarter zip",
]

CARHARTT_WEAK_ITEMS = [
    "t-shirt", "tshirt", "tee", "koszulka",
    "basic tee", "basic t-shirt", "basic tshirt",
]

CARHARTT_GOOD_WAIST_SIZES = [
    "w30", "w31", "w32", "w33", "w34", "w36",
    "30x30", "30x32", "31x30", "31x32",
    "32x30", "32x32", "32x34",
    "33x30", "33x32", "33x34",
    "34x30", "34x32", "34x34",
    "36x30", "36x32", "36x34",
]

CARHARTT_GOOD_ALPHA_SIZES = [
    "m", "medium", "l", "large", "xl", "x-large", "extra large",
]

CARHARTT_BAD_SMALL_SIZES = [
    "xs", "extra small", "s", "small",
    "w24", "w25", "w26", "w27", "w28", "w29",
    "24x", "25x", "26x", "27x", "28x", "29x",
]

VINTAGE_SPORTS_SIGNALS = [
    "world series", "super bowl", "final four", "march madness",
    "rose bowl", "nba finals", "stanley cup", "mlb", "nfl",
    "nba", "nhl", "ncaa", "college", "university", "varsity",
    "athletics", "rebels", "yankees", "raiders", "bulls",
    "dodgers", "red sox", "vikings", "minnesota vikings",
    "los angeles dodgers", "athletics vs reds",
]

COLLEGE_SIGNALS = [
    "unlv", "ucla", "usc", "michigan", "notre dame",
    "harvard", "yale", "georgetown", "duke", "north carolina",
    "tar heels", "rebels", "college", "university",
]

VINTAGE_BLANK_TAGS = [
    "hanes heavy weight", "hanes heavyweight", "hanes beefy",
    "fruit of the loom", "fruit of the loom usa", "screen stars",
    "russell athletic", "jerzees", "tultex", "oneita", "anvil",
    "galt sand", "nutmeg", "made in usa", "made in u.s.a",
    "made in america",
]

HARLEY_DEALER_LOCATION_SIGNALS = [
    "county", "camden", "collingswood", "new jersey", "nj",
    "california", "texas", "florida", "dealer", "motor cycles",
    "motorcycles", "cycles", "front print", "back print",
    "big logo", "panther", "biker", "chopper", "garage",
]

TASTE_BIKER_EVENT_SIGNALS = [
    "daytona", "bikerfest", "biker fest", "bike week",
    "motorcycle", "motorcycles", "motor cycles", "devil cycles",
    "flame", "flames", "skull", "eagle", "panther", "chopper",
    "rally", "sturgis", "dealer", "garage",
]

RALPH_LAUREN_DESIRABLE_SIGNALS = [
    "eagle", "spellout", "spell out", "big logo", "polo sport",
    "polo jeans", "rl 67", "indian head", "bear", "stadium",
    "snow beach", "country", "outdoor goods", "fine quality",
    "western", "americana", "aztec", "southwestern", "indigo",
    "chambray",
]

RRL_DOUBLE_RL_SIGNALS = [
    "rrl", "double rl", "double r l", "double ralph lauren",
    "ralph lauren rrl", "polo rrl", "rrl ralph lauren",
]

RRL_DOUBLE_RL_PATTERNS = [
    r"\brrl\b",
    r"\bdouble\s+rl\b",
    r"\bdouble\s+r\s*l\b",
    r"\bdouble\s+ralph\s+lauren\b",
    r"\bralph\s+lauren\s+rrl\b",
    r"\bpolo\s+rrl\b",
    r"\brrl\s+ralph\s+lauren\b",
]

RRL_STYLE_SIGNALS = [
    "western", "cowboy", "denim western", "workwear", "americana",
    "flannel", "native", "aztec", "southwestern", "indigo",
    "selvedge", "chambray", "duck canvas", "corduroy",
    "leather patch", "vintage wash",
]

LEE_DESIRABLE_SIGNALS = [
    "lee riders", "storm rider", "blanket lined", "cord collar",
    "corduroy collar", "trucker jacket", "chore jacket",
    "work jacket", "denim jacket", "vintage lee", "made in usa",
]

WORKWEAR_COMPANY_STRONG_SIGNALS = [
    "old dominion", "freight line", "company jacket",
    "work jacket", "worker jacket", "uniform jacket",
    "embroidered logo", "embroidered name", "duck canvas",
    "made in usa",
]

WORKWEAR_COMPANY_SIGNALS = WORKWEAR_COMPANY_STRONG_SIGNALS

TASTE_POP_CULTURE_SIGNALS = [
    "warner bros", "warner brothers", "taz", "tasmanian devil",
    "looney tunes", "lego", "star wars", "boba fett",
    "darth vader", "yoda", "marvel", "dc comics", "batman",
    "spiderman", "simpsons", "south park", "pokemon", "nintendo",
    "playstation", "xbox",
]

TASTE_METAL_FANTASY_BAND_SIGNALS = [
    "manowar", "slayer", "megadeth", "iron maiden", "pantera",
    "black sabbath", "ozzy", "judas priest", "motörhead",
    "motorhead", "fantasy graphic", "dragon", "warrior",
    "battle", "world tour",
]

TASTE_STREETWEAR_CHEAP_SIGNALS = [
    "stussy", "stüssy", "supreme", "palace", "bape", "xlarge",
    "fuct", "obey", "realtree", "mossy oak",
]

TASTE_VISUAL_SIGNALS = [
    "big print", "large print", "front print", "back print",
    "sleeve print", "all over print", "aop", "flame sleeves",
    "embroidered", "embroidery", "graphic", "spellout",
    "spell out",
]

TASTE_ERA_SIGNALS = [
    "70s", "80s", "90s", "00s", "1988", "1990", "1991",
    "1992", "1993", "1994", "1995", "1996", "1997",
    "1998", "1999", "2000", "2001", "2002", "2004", "2007",
]

TASTE_META_SIGNALS = {
    "taste_price_<=30",
    "taste_price_<=50",
    "taste_price_<=80",
    "taste_good_resale_size",
    "taste_ok_resale_size",
    "taste_fresh_low_price_style",
}


def _has_real_taste_signal(signals) -> bool:
    return any(str(sig) not in TASTE_META_SIGNALS for sig in (signals or []))


def _clip_score(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _keyword_hits_lower(title_l: str, keywords: list[str]) -> list[str]:
    return [k for k in keywords if k.lower() in title_l]

def normalize_text(text: str) -> str:
    text_l = str(text or "").lower()
    text_l = re.sub(r"[^a-z0-9]+", " ", text_l)
    return re.sub(r"\s+", " ", text_l).strip()


def contains_exact_token(text: str, token: str) -> bool:
    normalized = normalize_text(text)
    token_n = normalize_text(token)
    if not token_n:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(token_n)}(?![a-z0-9])", normalized) is not None


def contains_phrase(text: str, phrase: str) -> bool:
    normalized = normalize_text(text)
    phrase_n = normalize_text(phrase)
    if not phrase_n:
        return False
    pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(part) for part in phrase_n.split()) + r"(?![a-z0-9])"
    return re.search(pattern, normalized) is not None


def contains_any_phrase(text: str, phrases: list[str]) -> bool:
    return any(contains_phrase(text, phrase) for phrase in phrases)


def _token_or_phrase_hit(title_l: str, keyword: str) -> bool:
    kw_l = keyword.lower()
    if len(kw_l) <= 2 and kw_l.isalpha():
        return contains_exact_token(title_l, kw_l)
    if kw_l.endswith("x"):
        return re.search(rf"(?<![a-z0-9]){re.escape(kw_l)}\d*", title_l) is not None
    return contains_phrase(title_l, kw_l)


def _first_hit(title_l: str, keywords: list[str]) -> str | None:
    for keyword in keywords:
        if _token_or_phrase_hit(title_l, keyword):
            return keyword
    return None


def _add_unique(target: list[str], values: list[str]):
    for value in values:
        if value not in target:
            target.append(value)

def _item_search_text(item: dict, result: dict | None = None) -> str:
    result = result or {}
    parts = [
        item.get("title"),
        item.get("description"),
        item.get("desc"),
        item.get("brand"),
        item.get("size"),
        result.get("brand"),
        result.get("brand_detected"),
        result.get("category"),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _taste_item_type(title_l: str, category: str | None) -> bool:
    category = category or ""
    return bool(
        category in ("tshirt", "shirt", "hoodie", "jacket", "coat")
        or any(k in title_l for k in [
            "tee", "t-shirt", "tshirt", "koszulka", "longsleeve",
            "long sleeve", "sweatshirt", "crewneck", "hoodie",
            "zip hoodie", "bluza", "jacket", "kurtka",
        ])
    )


def _taste_size_bucket(item: dict, title_l: str) -> str:
    size_l = str(item.get("size") or "").lower()
    text = f"{title_l} {size_l}"
    if re.search(r"(?<![a-z0-9])(xxl|2xl|xl|x-large|extra large|large|l)(?![a-z0-9])", text):
        return "large"
    if re.search(r"(?<![a-z0-9])(m|medium)(?![a-z0-9])", text):
        return "medium"
    return ""


def _taste_fast_fashion(text_l: str, brand_l: str) -> bool:
    return bool((brand_l and brand_l in FAST_FASHION_BRANDS) or _first_hit(text_l, list(FAST_FASHION_BRANDS)))


def _first_rrl_match(text_l: str) -> str | None:
    normalized = normalize_text(text_l)
    for pattern in RRL_DOUBLE_RL_PATTERNS:
        if re.search(pattern, normalized):
            return pattern
    return None


def _lee_taste_hit(text_l: str, brand_l: str) -> str | None:
    if normalize_text(brand_l) == "lee":
        return "brand:lee"
    lee_patterns = [
        "lee riders", "lee storm rider", "storm rider",
        "vintage lee", "lee jacket", "lee denim",
        "lee chore", "lee trucker",
    ]
    return _first_hit(text_l, lee_patterns)


def _sports_taste_hit(text_l: str) -> str | None:
    strong_sports = [
        "world series", "super bowl", "final four", "march madness",
        "rose bowl", "nba finals", "stanley cup", "mlb", "nfl",
        "nba", "nhl", "ncaa", "college", "university", "varsity",
        "rebels", "yankees", "raiders", "bulls", "dodgers",
        "red sox", "vikings", "minnesota vikings",
        "los angeles dodgers", "athletics vs reds",
    ]
    hit = _first_hit(text_l, strong_sports + COLLEGE_SIGNALS)
    if hit:
        return hit
    if contains_exact_token(text_l, "athletics"):
        context = bool(
            _first_hit(text_l, ["mlb", "nba", "nfl", "nhl", "ncaa", "world series", "super bowl", "final four", "rose bowl"])
            or _first_hit(text_l, ["yankees", "raiders", "bulls", "dodgers", "red sox", "vikings", "reds", "eric davis"])
            or _first_hit(text_l, TASTE_ERA_SIGNALS)
        )
        if context:
            return "athletics"
    return None


def _market_entry_for_signal(db: MarketDB, brand: str | None, category: str | None) -> dict | None:
    candidates = []
    if brand and category:
        candidates.append(f"{brand}_{category}")
    if category:
        candidates.extend([f"chaos_{category}", f"vintage_{category}", f"{category}_unknown"])
    for key in candidates:
        entry = db.lookup(key)
        if entry and entry.get("count", 0) >= 2:
            return entry
    if brand:
        return db.lookup_brand_category(brand, category)
    return None


def build_signal_profile(result: dict, db: MarketDB) -> dict:
    item = result.get("item", {}) or {}
    title = str(item.get("title") or "")
    title_l = title.lower()
    features = extract_item_features(item)

    brand = result.get("brand") or result.get("brand_detected") or features.get("brand")
    category = result.get("category") or features.get("category")
    band = result.get("band") or features.get("band") or detect_band(title)
    profit = float(result.get("profit", 0) or result.get("estimated_profit", 0) or 0)
    confidence = float(result.get("confidence", 0) or 0)
    pattern_score = int(result.get("pattern_score", 0) or 0)
    estimated_value = float(
        result.get("estimated_value")
        or result.get("market_price")
        or result.get("median_price")
        or 0
    )
    price = float(item.get("price") or 0)
    market_entry = _market_entry_for_signal(db, brand, category)
    market_count = int((market_entry or {}).get("count", 0) or 0)
    deal_tag = result.get("deal_tag") or (market_entry or {}).get("last_deal") or "NO_DATA"

    auth_hits = _keyword_hits_lower(title_l, AUTHENTICITY_SIGNALS)
    rarity_hits = _keyword_hits_lower(title_l, RARITY_KEYWORDS + VINTAGE_SIGNALS + [
        "archive", "tour", "single stitch", "made in usa", "faded",
        "embroidered", "all over print", "licensed", "season",
    ])
    aesthetic_hits = _keyword_hits_lower(title_l, AESTHETIC_SPAM_KEYWORDS)
    penalty_phrase_hits = _keyword_hits_lower(title_l, AUTHENTICITY_PENALTY_PHRASES)
    fast_fashion = bool(
        (brand and brand.lower() in FAST_FASHION_BRANDS)
        or any(ff in title_l for ff in FAST_FASHION_BRANDS)
    )
    strong_brand = bool(brand and brand in STRONG_BRANDS)
    grail_brand = bool(brand and brand in GRAIL_ELIGIBLE_BRANDS)
    is_band = bool(band)

    if market_count >= 12:
        market_strength = 88
    elif market_count >= 6:
        market_strength = 74
    elif market_count >= 3:
        market_strength = 60
    elif estimated_value > 0 and (strong_brand or grail_brand or is_band):
        market_strength = 52
    else:
        market_strength = 30
    if deal_tag == "STRONG":
        market_strength += 8
    elif deal_tag == "GOOD":
        market_strength += 4
    if market_entry and market_entry.get("p25") and market_entry.get("p75"):
        p25 = float(market_entry.get("p25") or 0)
        p75 = float(market_entry.get("p75") or 0)
        if p25 > 0 and p75 / p25 <= 2.2:
            market_strength += 6
    market_strength = _clip_score(market_strength)

    rarity_strength = 10 + len(set(rarity_hits)) * 11 + max(0, pattern_score) * 5
    if grail_brand:
        rarity_strength += 12
    if is_band:
        rarity_strength += 8
    rarity_strength = _clip_score(rarity_strength)

    vintage_authenticity = 18 + len(set(auth_hits)) * 22
    if features.get("is_vintage"):
        vintage_authenticity += 14
    if fast_fashion:
        vintage_authenticity -= 55
    if penalty_phrase_hits:
        vintage_authenticity -= 25
    vintage_authenticity = _clip_score(vintage_authenticity)

    visual_uniqueness = 25 + max(0, pattern_score) * 9
    if any(k in title_l for k in ["all over print", "aop", "embroidered", "faded", "cracked print"]):
        visual_uniqueness += 24
    if aesthetic_hits and not strong_brand:
        visual_uniqueness -= 20
    visual_uniqueness = _clip_score(visual_uniqueness)

    if strong_brand:
        brand_strength_score = 82
    elif grail_brand or is_band:
        brand_strength_score = 72
    elif brand:
        brand_strength_score = 48
    else:
        brand_strength_score = 22
    if fast_fashion:
        brand_strength_score = min(brand_strength_score, 18)

    if estimated_value > 0 and price > 0:
        discount_ratio = max(0.0, 1.0 - (price / estimated_value))
        price_advantage = _clip_score(discount_ratio * 140)
    elif profit > 0 and price > 0:
        price_advantage = _clip_score((profit / price) * 65)
    else:
        price_advantage = 0

    signal_quality = (
        market_strength * 0.25
        + rarity_strength * 0.20
        + vintage_authenticity * 0.20
        + visual_uniqueness * 0.15
        + brand_strength_score * 0.10
        + price_advantage * 0.10
    )

    cap_confidence = None
    cap_signal_quality = None
    max_tier = None
    protection_reasons = []

    if fast_fashion:
        cap_confidence = 5.5
        cap_signal_quality = 40
        max_tier = "TIER_C"
        protection_reasons.append("fast_fashion_auth_penalty")

    if penalty_phrase_hits:
        cap_signal_quality = min(cap_signal_quality or 100, 55)
        protection_reasons.append("style_phrase_auth_penalty")

    if is_band and len(set(auth_hits)) < 2:
        cap_confidence = min(cap_confidence or 10.0, 6.0)
        cap_signal_quality = min(cap_signal_quality or 100, 45)
        max_tier = "TIER_C"
        rarity_strength = min(rarity_strength, 45)
        protection_reasons.append("band_tee_auth_signals_lt_2")

    if aesthetic_hits and not strong_brand:
        max_tier = "TIER_B" if max_tier is None else max_tier
        cap_signal_quality = min(cap_signal_quality or 100, 69)
        protection_reasons.append("low_quality_aesthetic_cap")

    if cap_signal_quality is not None:
        signal_quality = min(signal_quality, cap_signal_quality)

    signal_quality = round(_clip_score(signal_quality), 2)

    if signal_quality >= 85:
        tier = "TIER_S"
    elif signal_quality >= 70:
        tier = "TIER_A"
    elif signal_quality >= 55:
        tier = "TIER_B"
    else:
        tier = "TIER_C"

    if max_tier == "TIER_B" and tier == "TIER_S":
        tier = "TIER_A"
    if max_tier == "TIER_B" and tier == "TIER_A" and signal_quality < 70:
        tier = "TIER_B"
    if max_tier == "TIER_C":
        tier = "TIER_C"

    market_validated = bool(
        market_count >= 3
        or deal_tag in ("GOOD", "STRONG")
        or (estimated_value > 0 and (strong_brand or grail_brand) and profit > 0)
    )
    auth_state = "strong" if len(set(auth_hits)) >= 2 else ("weak" if auth_hits else "missing")
    market_state = "validated" if market_validated else ("thin" if estimated_value > 0 else "missing")

    await_reasons = []
    if 45 <= signal_quality < 60:
        await_reasons.append("signal_quality_45_60")
    if confidence < 5.5 and signal_quality < 70:
        await_reasons.append("weak_confidence")
    if not market_validated and signal_quality < 70:
        await_reasons.append("market_unvalidated")
    if is_band and len(set(auth_hits)) < 2:
        await_reasons.append("band_auth_unconfirmed")
    await_state = {
        "hold": bool(await_reasons),
        "reasons": await_reasons,
        "needs": [
            "sold_comps" if not market_validated else None,
            "authenticity_signals" if is_band and len(set(auth_hits)) < 2 else None,
            "rarity_confirmation" if signal_quality < 60 else None,
        ],
    }
    await_state["needs"] = [n for n in await_state["needs"] if n]

    return {
        "signal_quality_score": signal_quality,
        "signal_tier": tier,
        "signal_subscores": {
            "market_strength": round(market_strength, 2),
            "rarity_strength": round(rarity_strength, 2),
            "vintage_authenticity": round(vintage_authenticity, 2),
            "visual_uniqueness": round(visual_uniqueness, 2),
            "brand_strength": round(brand_strength_score, 2),
            "price_advantage": round(price_advantage, 2),
        },
        "await_state": await_state,
        "auth_state": auth_state,
        "authenticity_hits": sorted(set(auth_hits)),
        "market_state": market_state,
        "market_evidence": {
            "validated": market_validated,
            "count": market_count,
            "deal_tag": deal_tag,
            "historical_matches": market_count >= 3,
        },
        "cap_confidence": cap_confidence,
        "remove_grail_status": bool(is_band and len(set(auth_hits)) < 2),
        "protection_reasons": protection_reasons,
        "rarity_score": round(rarity_strength, 2),
        "is_low_quality_aesthetic": bool(aesthetic_hits and not strong_brand),
    }


def apply_signal_profile(result: dict, profile: dict) -> dict:
    result.update(profile)
    if profile.get("cap_confidence") is not None:
        result["confidence"] = min(float(result.get("confidence", 0) or 0), profile["cap_confidence"])
    if profile.get("remove_grail_status"):
        result["is_grail"] = False
        result["grail_score"] = min(int(result.get("grail_score", 0) or 0), 2)
    result["tier"] = profile.get("signal_tier", result.get("tier"))
    result.setdefault("ranking_penalty", 0)
    result.setdefault("cluster_penalty", 0)
    result.setdefault("tier_bonus", SIGNAL_TIER_BOOSTS.get(result.get("tier"), 0))
    return result


def compute_desirability_score(item: dict, result: dict) -> dict:
    item = item or {}
    result = result or {}
    title = str(item.get("title") or "")
    title_l = title.lower()
    features = extract_item_features(item)
    brand = (result.get("brand") or result.get("brand_detected") or features.get("brand") or "")
    brand_l = brand.lower()
    category = result.get("category") or features.get("category") or ""
    price = float(item.get("price") or 0)
    pattern_score = int(result.get("pattern_score", 0) or 0)
    signal_quality = float(result.get("signal_quality_score", 0) or 0)
    auth_hits = result.get("authenticity_hits") or []
    rarity_score = float(result.get("rarity_score", 0) or 0)

    score = 10
    desirable_signals: list[str] = []
    generic_penalties: list[str] = []

    def add_signal(name: str, points: int):
        nonlocal score
        score += points
        if name not in desirable_signals:
            desirable_signals.append(name)

    def add_penalty(name: str, points: int):
        nonlocal score
        score -= points
        if name not in generic_penalties:
            generic_penalties.append(name)

    is_shirt_category = bool(
        category in ("tshirt", "shirt", "top")
        or any(k in title_l for k in ["t-shirt", "tshirt", "tee", "koszulka", "top"])
    )

    outdoor_brands = {"the north face", "tnf", "columbia", "helly hansen", "patagonia"}
    denim_brands = {"levi's", "levis", "levi", "diesel", "wrangler", "carhartt", "true religion", "g-star", "g star"}
    designer_brands = LUXURY_BRANDS | {"gaultier", "helmut lang", "jil sander", "margiela", "cavalli", "dolce gabbana", "d&g", "yohji", "issey miyake", "comme des garcons", "vivienne westwood"}

    if brand_l in outdoor_brands:
        hits = _keyword_hits_lower(title_l, DESIRABLE_OUTDOOR)
        if hits:
            add_signal(f"outdoor:{hits[0]}", 30)
            add_signal("strong_brand_desirable_category", 10)
    if brand_l == "nike":
        hits = _keyword_hits_lower(title_l, DESIRABLE_NIKE)
        if hits:
            add_signal(f"nike:{hits[0]}", 30)
            add_signal("real_model_line", 20)
    if brand_l == "adidas":
        hits = _keyword_hits_lower(title_l, DESIRABLE_ADIDAS)
        if hits:
            add_signal(f"adidas:{hits[0]}", 30)
            add_signal("real_model_line", 20)
    if brand_l in denim_brands or category in ("jeans", "cargo"):
        hits = _keyword_hits_lower(title_l, DESIRABLE_DENIM)
        if hits:
            add_signal(f"denim:{hits[0]}", 30)
    vintage_hits = _keyword_hits_lower(title_l, DESIRABLE_VINTAGE)
    if vintage_hits or auth_hits:
        add_signal(f"vintage:{(vintage_hits or auth_hits)[0]}", 20)
    if "harley" in brand_l or "harley" in title_l:
        hits = _keyword_hits_lower(title_l, DESIRABLE_HARLEY)
        if hits:
            add_signal(f"harley:{hits[0]}", 30)
        strong_hits = _keyword_hits_lower(title_l, HARLEY_STRONG_ITEM_SIGNALS)
        if len(set(strong_hits)) >= 2:
            add_signal("harley_strong_item_signal", 25)
            result["pattern_score"] = pattern_score = pattern_score + 2
            if DEBUG_ALERTS:
                print(f"  [HARLEY_SIGNAL_BOOST] signals={strong_hits} "
                      f"desirability={_clip_score(score):.0f} pattern={pattern_score} "
                      f"title={title[:60]}")
        if (
            ("waffle" in title_l or "thermal" in title_l)
            and ("longsleeve" in title_l or "long sleeve" in title_l)
        ):
            add_signal("harley_waffle_thermal_longsleeve", 20)
            if DEBUG_ALERTS:
                print(f"  [HARLEY_SIGNAL_BOOST] signals=['waffle/thermal_longsleeve'] "
                      f"desirability={_clip_score(score):.0f} pattern={pattern_score} "
                      f"title={title[:60]}")
    if brand_l in designer_brands or any(d in title_l for d in DESIRABLE_DESIGNER):
        hits = _keyword_hits_lower(title_l, DESIRABLE_DESIGNER)
        if hits:
            add_signal(f"designer:{hits[0]}", 30)
            add_signal("designer_material_archive", 20)

    if rarity_score >= 55 or _keyword_hits_lower(title_l, RARITY_KEYWORDS):
        add_signal("rarity_signal", 15)

    generic_hits = _keyword_hits_lower(title_l, GENERIC_LOW_DESIRABILITY)
    for hit in generic_hits[:2]:
        add_penalty(f"generic:{hit}", 30)

    fast_fashion = bool(
        (brand_l and brand_l in FAST_FASHION_BRANDS)
        or any(ff in title_l for ff in FAST_FASHION_BRANDS)
    )
    if fast_fashion:
        add_penalty("fast_fashion", 25)

    # Carhartt-specific desirability.
    is_carhartt = "carhartt" in brand_l or "carhartt" in title_l
    carhartt_is_pants = bool(is_carhartt and (
        category in ("jeans", "cargo")
        or any(k in title_l for k in ["pant", "pants", "trouser", "trousers", "spodnie", "cargo", "jeans", "work pant", "carpenter"])
    ))
    carhartt_is_hoodie = bool(is_carhartt and any(k in title_l for k in [
        "hoodie", "crewneck", "sweatshirt", "zip hoodie", "half zip", "quarter zip", "bluza",
    ]))
    carhartt_is_basic_tee = bool(is_carhartt and any(k in title_l for k in CARHARTT_WEAK_ITEMS))

    if is_carhartt:
        model_hit = _first_hit(title_l, DESIRABLE_CARHARTT)
        if model_hit:
            add_signal("carhartt_desirable_item", 25)

        if carhartt_is_basic_tee and not model_hit:
            add_penalty("carhartt_basic_tee", 25)

        if carhartt_is_pants:
            small_hit = _first_hit(title_l, CARHARTT_BAD_SMALL_SIZES)
            waist_hit = _first_hit(title_l, CARHARTT_GOOD_WAIST_SIZES)
            alpha_hit = _first_hit(title_l, CARHARTT_GOOD_ALPHA_SIZES)
            if small_hit:
                generic_penalties.append("carhartt_small_pants_size")
                result["carhartt_size_skip"] = True
                result["carhartt_size_hit"] = small_hit
                if DEBUG_ALERTS:
                    print(f"  [CARHARTT_SIZE_SKIP] size_hit={small_hit} reason=small_size title={title[:60]}")
            elif waist_hit:
                add_signal("carhartt_good_waist_size", 20)
                add_signal("carhartt_good_pants_size", 0)
                result["carhartt_size_type"] = "waist"
                result["carhartt_size_hit"] = waist_hit
                if DEBUG_ALERTS:
                    print(f"  [CARHARTT_SIZE_PASS] size_type=waist size_hit={waist_hit} boost=20 title={title[:60]}")
            elif alpha_hit:
                add_signal("carhartt_good_alpha_size", 18)
                add_signal("carhartt_good_pants_size", 0)
                result["carhartt_size_type"] = "alpha"
                result["carhartt_size_hit"] = alpha_hit
                if DEBUG_ALERTS:
                    print(f"  [CARHARTT_SIZE_PASS] size_type=alpha size_hit={alpha_hit} boost=18 title={title[:60]}")
            elif DEBUG_ALERTS:
                print(f"  [CARHARTT_SIZE_PASS] size_type=none size_hit=None boost=0 title={title[:60]}")

        if carhartt_is_hoodie:
            if price <= 140:
                add_signal("carhartt_hoodie_good_price", 15)
            elif price > 250:
                add_penalty("carhartt_hoodie_price_too_high", 10)

        if DEBUG_ALERTS:
            print(f"  [CARHARTT_SCORE] desirability={_clip_score(score):.0f} "
                  f"signals={desirable_signals} penalties={generic_penalties} title={title[:60]}")

    if brand_l in STRONG_BRANDS and not desirable_signals:
        add_penalty("strong_brand_no_desirable_signal", 20)

    conditional_brand = brand_l in CONDITIONAL_STRONG_BRANDS
    is_generic_strong_brand = bool(conditional_brand and not desirable_signals)
    has_auth_or_rarity_signal = bool(
        auth_hits
        or result.get("auth_state") == "strong"
        or result.get("has_rarity")
        or rarity_score >= 45
        or _keyword_hits_lower(title_l, DESIRABLE_VINTAGE)
        or _keyword_hits_lower(title_l, RARITY_KEYWORDS)
    )
    generic_conditional_brand_shirt = bool(
        conditional_brand
        and is_shirt_category
        and pattern_score == 0
        and not desirable_signals
        and not has_auth_or_rarity_signal
    )
    if is_generic_strong_brand:
        add_penalty("conditional_strong_brand_no_desirable_signal", 20)
        score = min(score, 45)
    elif brand_l in STRONG_BRANDS and desirable_signals:
        add_signal("strong_brand_desirable_category", 10)

    if generic_conditional_brand_shirt:
        score = min(score, 35)

    score = round(_clip_score(score), 2)
    if DEBUG_ALERTS:
        print(f"  [DESIRABILITY] score={score:.0f} signals={desirable_signals} "
              f"generic={generic_penalties} conditional_brand={conditional_brand} "
              f"brand={brand or '-'} category={category or '-'} title={title[:60]}")

    return {
        "desirability_score": score,
        "desirable_signals": desirable_signals,
        "generic_penalties": generic_penalties,
        "is_generic_strong_brand": is_generic_strong_brand,
        "conditional_strong_brand": conditional_brand,
        "generic_conditional_brand_shirt": generic_conditional_brand_shirt,
        "has_auth_or_rarity_signal": has_auth_or_rarity_signal,
        "carhartt_is_basic_tee": carhartt_is_basic_tee,
        "carhartt_is_pants": carhartt_is_pants,
        "carhartt_is_hoodie": carhartt_is_hoodie,
        "carhartt_size_skip": bool(result.get("carhartt_size_skip")),
        "carhartt_size_hit": result.get("carhartt_size_hit"),
        "carhartt_size_type": result.get("carhartt_size_type"),
    }


def apply_desirability_profile(result: dict, profile: dict) -> dict:
    result.update(profile)
    item = result.get("item", {}) or {}
    title = str(item.get("title") or "")
    title_l = title.lower()
    category = result.get("category") or ""
    brand = (result.get("brand") or result.get("brand_detected") or "").lower()
    signals = result.get("desirable_signals", []) or []
    signal_text = " ".join(str(s).lower() for s in signals)
    is_shirt_category = bool(
        category in ("tshirt", "shirt", "top")
        or any(k in title_l for k in ["t-shirt", "tshirt", "tee", "koszulka", "top"])
    )

    def _raise_desirability_floor(floor: float, reason: str) -> None:
        old = float(result.get("desirability_score", 0) or 0)
        if old < floor:
            result["desirability_score"] = floor
            if DEBUG_ALERTS:
                print(f"  [POSITIVE_SIGNAL_FLOOR] old={old:.0f} new={floor:.0f} "
                      f"signals={signals} reason={reason} title={title[:60]}")

    strong_signal_hits = []
    strong_signal_needles = [
        "carhartt_desirable_item",
        "carhartt_good_pants_size",
        "harley_strong_item_signal",
        "harley_waffle_thermal_longsleeve",
        "vintage:single stitch",
        "vintage:made in usa",
        "vintage:made in the usa",
        "denim:bootcut",
        "denim:flare",
        "denim:flared",
        "denim:made in usa",
        "designer:archive",
        "designer:made in italy",
        "nike:acg",
        "outdoor:goretex",
        "outdoor:gore-tex",
        "outdoor:acg",
        "outdoor:summit",
    ]
    for needle in strong_signal_needles:
        if needle in signal_text:
            strong_signal_hits.append(needle)
    if strong_signal_hits:
        _raise_desirability_floor(70 if len(set(strong_signal_hits)) >= 2 else 60, "strong_desirable_signal")

    if ("carhartt" in brand or "carhartt" in title_l) and "carhartt_desirable_item" in signals:
        old_des = float(result.get("desirability_score", 0) or 0)
        old_quality = float(result.get("signal_quality_score", 0) or 0)
        model_hit = _first_hit(title_l, CARHARTT_HIGH_VALUE_MODELS)
        result["desirability_score"] = max(old_des, 65.0)
        result["signal_quality_score"] = max(old_quality, 58.0)
        if model_hit:
            result["desirability_score"] = max(float(result.get("desirability_score", 0) or 0), 70.0)
            result["signal_quality_score"] = max(float(result.get("signal_quality_score", 0) or 0), 60.0)
            result["pattern_score"] = max(int(result.get("pattern_score", 0) or 0), 3)
        if result.get("carhartt_is_hoodie") and float(item.get("price") or 0) <= 140:
            result["desirability_score"] = max(float(result.get("desirability_score", 0) or 0), 60.0)
        if DEBUG_ALERTS:
            print(f"  [CARHARTT_POSITIVE_FLOOR] model={model_hit or 'desirable_item'} "
                  f"old_desirability={old_des:.0f} new_desirability={float(result.get('desirability_score', 0) or 0):.0f} "
                  f"old_quality={old_quality:.0f} new_quality={float(result.get('signal_quality_score', 0) or 0):.0f} "
                  f"title={title[:60]}")

    is_harley = bool("harley davidson" in title_l or "harley-davidson" in title_l or "harley" in title_l or "harley" in brand)
    if is_harley:
        harley_hits = _keyword_hits_lower(title_l, HARLEY_STRONG_ITEM_SIGNALS)
        old_des = float(result.get("desirability_score", 0) or 0)
        old_quality = float(result.get("signal_quality_score", 0) or 0)
        old_pattern = int(result.get("pattern_score", 0) or 0)
        boosted = False
        if len(set(harley_hits)) >= 2:
            result["desirability_score"] = max(old_des, 70.0)
            result["signal_quality_score"] = max(old_quality, 62.0)
            result["pattern_score"] = max(old_pattern, 4)
            if "harley_strong_item_signal" not in signals:
                signals.append("harley_strong_item_signal")
            boosted = True
        if (
            ("waffle" in title_l or "thermal" in title_l)
            and ("longsleeve" in title_l or "long sleeve" in title_l)
        ):
            result["desirability_score"] = max(float(result.get("desirability_score", 0) or 0), 75.0)
            result["signal_quality_score"] = max(float(result.get("signal_quality_score", 0) or 0), 65.0)
            result["pattern_score"] = max(int(result.get("pattern_score", 0) or 0), 5)
            if "harley_waffle_thermal_longsleeve" not in signals:
                signals.append("harley_waffle_thermal_longsleeve")
            boosted = True
        result["desirable_signals"] = signals
        if boosted and DEBUG_ALERTS:
            print(f"  [HARLEY_SIGNAL_BOOST] signals={harley_hits} "
                  f"desirability={float(result.get('desirability_score', 0) or 0):.0f} "
                  f"quality={float(result.get('signal_quality_score', 0) or 0):.0f} "
                  f"pattern={int(result.get('pattern_score', 0) or 0)} title={title[:60]}")

    band = result.get("band") or detect_band(title)
    band_signal_hits = _keyword_hits_lower(title_l, [
        "made in usa", "made in the usa", "single stitch", "90s", "80s",
        "tour", "rare", "deadstock", "giant tag", "brockum",
        "screen stars", "fruit of the loom usa",
    ])
    if band and len(set(band_signal_hits)) >= 2:
        result["desirability_score"] = max(float(result.get("desirability_score", 0) or 0), 65.0)
        result["signal_quality_score"] = max(float(result.get("signal_quality_score", 0) or 0), 60.0)
        if "band_authenticity_combo" not in signals:
            signals.append("band_authenticity_combo")
            result["desirable_signals"] = signals
        if DEBUG_ALERTS:
            print(f"  [BAND_AUTH_BOOST] band={band} signals={band_signal_hits} "
                  f"desirability={float(result.get('desirability_score', 0) or 0):.0f} "
                  f"quality={float(result.get('signal_quality_score', 0) or 0):.0f} "
                  f"title={title[:60]}")

    if result.get("is_generic_strong_brand"):
        old_conf = float(result.get("confidence", 0) or 0)
        cap = 5.5 if is_shirt_category else 6.0
        result["confidence"] = min(old_conf, cap)
        result["signal_quality_score"] = min(float(result.get("signal_quality_score", 0) or 0), 60.0)
        result["desirability_score"] = min(float(result.get("desirability_score", 0) or 0), 45.0)
        if DEBUG_ALERTS:
            print(f"  [CONDITIONAL_BRAND_CONF_CAP] brand={result.get('brand') or result.get('brand_detected') or '-'} "
                  f"old_conf={old_conf:.1f} new_conf={result['confidence']:.1f} "
                  f"reason=no_desirable_signal title={title[:60]}")
    if result.get("generic_conditional_brand_shirt"):
        old_conf = float(result.get("confidence", 0) or 0)
        result["confidence"] = min(old_conf, 5.5)
        result["signal_quality_score"] = min(float(result.get("signal_quality_score", 0) or 0), 45.0)
        result["desirability_score"] = min(float(result.get("desirability_score", 0) or 0), 35.0)
        if DEBUG_ALERTS:
            print(f"  [CONDITIONAL_BRAND_CONF_CAP] brand={result.get('brand') or result.get('brand_detected') or '-'} "
                  f"old_conf={old_conf:.1f} new_conf={result['confidence']:.1f} "
                  f"reason=generic_conditional_brand_shirt title={title[:60]}")
    return result


def compute_manual_taste_profile(item: dict, result: dict) -> dict:
    item = item or {}
    result = result or {}
    title = str(item.get("title") or "")
    text_l = _item_search_text(item, result)
    category = result.get("category") or detect_category(title) or ""
    brand_l = str(result.get("brand") or result.get("brand_detected") or item.get("brand") or "").lower()
    price = float(item.get("price") or 0)
    item_type_ok = _taste_item_type(text_l, category)
    is_jacket = category in ("jacket", "coat") or any(k in text_l for k in ["jacket", "kurtka", "coat", "chore"])
    is_sweat = any(k in text_l for k in ["sweatshirt", "crewneck", "hoodie", "bluza", "longsleeve", "long sleeve"])
    size_bucket = _taste_size_bucket(item, text_l)

    signals: list[str] = []
    buckets: set[str] = set()
    desirability_delta = 0
    quality_floor = 0.0
    pattern_floor = 0

    def add_signal(name: str, points: int = 0, bucket: str | None = None):
        nonlocal desirability_delta
        desirability_delta += points
        if name not in signals:
            signals.append(name)
        if bucket:
            buckets.add(bucket)

    era_hit = _first_hit(text_l, TASTE_ERA_SIGNALS)
    old_blank_hit = _first_hit(text_l, VINTAGE_BLANK_TAGS)
    visual_hit = _first_hit(text_l, TASTE_VISUAL_SIGNALS)
    sports_hit = _sports_taste_hit(text_l)
    pop_hit = _first_hit(text_l, TASTE_POP_CULTURE_SIGNALS)
    biker_hit = _first_hit(text_l, TASTE_BIKER_EVENT_SIGNALS)
    metal_hit = _first_hit(text_l, TASTE_METAL_FANTASY_BAND_SIGNALS)
    street_hit = _first_hit(text_l, TASTE_STREETWEAR_CHEAP_SIGNALS)
    harley_dealer_hit = _first_hit(text_l, HARLEY_DEALER_LOCATION_SIGNALS)
    ralph_hit = _first_hit(text_l, RALPH_LAUREN_DESIRABLE_SIGNALS)
    rrl_hit = _first_rrl_match(text_l)
    rrl_style_hit = _first_hit(text_l, RRL_STYLE_SIGNALS)
    lee_hit = _lee_taste_hit(text_l, brand_l)
    workwear_hit = _first_hit(text_l, WORKWEAR_COMPANY_STRONG_SIGNALS)

    if sports_hit and item_type_ok:
        add_signal("vintage_sports_college_signal", 25, "sports")
        if era_hit:
            add_signal("vintage_sports_era_signal", 15, "sports")
            pattern_floor = max(pattern_floor, 3)
        if price <= 120:
            add_signal("vintage_sports_good_price", 10, "sports")

    if old_blank_hit and item_type_ok:
        add_signal("vintage_blank_tag_signal", 25, "old_blank")
        quality_floor = max(quality_floor, 58.0)
        context_hit = bool(sports_hit or pop_hit or biker_hit or metal_hit or visual_hit or any(k in text_l for k in ["military", "army", "navy", "naval", "graphic"]))
        if context_hit:
            add_signal("vintage_blank_graphic_combo", 0, "old_blank")
            pattern_floor = max(pattern_floor, 4)
            result["desirability_score"] = max(float(result.get("desirability_score", 0) or 0), 65.0)

    is_harley = "harley" in text_l or "harley" in brand_l
    if is_harley and item_type_ok and harley_dealer_hit:
        add_signal("harley_dealer_location_graphic", 20, "biker")
        pattern_floor = max(pattern_floor, 3)
        if price <= 80:
            add_signal("harley_graphic_good_price", 10, "biker")

    if biker_hit and item_type_ok:
        add_signal("biker_event_graphic_signal", 20, "biker")
        if old_blank_hit or era_hit:
            add_signal("biker_event_vintage_combo", 0, "biker")
            pattern_floor = max(pattern_floor, 4)
            result["desirability_score"] = max(float(result.get("desirability_score", 0) or 0), 65.0)

    is_ralph = any(k in text_l or k in brand_l for k in ["ralph lauren", "polo ralph lauren", "polo"])
    if is_ralph and not rrl_hit and ralph_hit:
        add_signal("ralph_lauren_graphic_spellout", 25, "heritage")
        if is_sweat and price <= 80:
            add_signal("ralph_lauren_good_price", 10, "heritage")

    if rrl_hit:
        add_signal("rrl_double_rl_mega_signal", 0, "heritage")
        result["desirability_score"] = max(float(result.get("desirability_score", 0) or 0), 80.0)
        quality_floor = max(quality_floor, 70.0)
        pattern_floor = max(pattern_floor, 5)
        if rrl_style_hit:
            add_signal("rrl_western_heritage_signal", 0, "heritage")
            result["desirability_score"] = max(float(result.get("desirability_score", 0) or 0), 88.0)
            quality_floor = max(quality_floor, 75.0)
            pattern_floor = max(pattern_floor, 6)
        if price <= 250:
            add_signal("rrl_good_price", 10, "heritage")
        if price <= 150:
            add_signal("rrl_very_good_price", 15, "heritage")

    if lee_hit and is_jacket:
        add_signal("lee_vintage_workwear_jacket", 25, "workwear")
        if price <= 130:
            add_signal("lee_jacket_good_price", 10, "workwear")

    workwear_brand = bool(_first_hit(f"{brand_l} {text_l}", ["carhartt", "dickies", "red kap"]) or _lee_taste_hit(text_l, brand_l))
    workwear_category = bool(is_jacket or category in ("jacket", "coat", "vest") or "workwear" in text_l)
    if (workwear_category or workwear_brand) and workwear_hit:
        add_signal("workwear_company_jacket_signal", 15, "workwear")
        if "carhartt" in brand_l or "carhartt" in text_l or normalize_text(brand_l) == "lee":
            add_signal("workwear_heritage_brand_signal", 10, "workwear")
            quality_floor = max(quality_floor, 60.0)

    if pop_hit and item_type_ok:
        add_signal("pop_culture_graphic_signal", 20, "pop_culture")
        if era_hit:
            add_signal("pop_culture_year_signal", 15, "pop_culture")
            pattern_floor = max(pattern_floor, 3)
        if price <= 80:
            add_signal("pop_culture_good_price", 10, "pop_culture")

    if metal_hit and item_type_ok:
        add_signal("metal_fantasy_band_signal", 25, "metal")
        if any(k in text_l for k in ["longsleeve", "long sleeve", "sleeve print"]):
            add_signal("metal_longsleeve_sleeveprint_signal", 10, "metal")
        if price <= 120:
            add_signal("metal_fantasy_good_price", 10, "metal")

    if street_hit and price <= 50:
        add_signal("cheap_style_signal", 20, "streetwear")
    if street_hit and price <= 30:
        add_signal("very_cheap_style_signal", 30, "streetwear")

    if signals:
        if size_bucket == "large":
            add_signal("good_resale_size", 8)
        elif size_bucket == "medium":
            add_signal("ok_resale_size", 4)

    bucket = "none"
    for preferred in ("heritage", "workwear", "sports", "old_blank", "biker", "pop_culture", "metal", "streetwear"):
        if preferred in buckets:
            bucket = preferred
            break

    return {
        "manual_taste_match": bool(signals),
        "manual_taste_signals": signals,
        "manual_taste_bucket": bucket,
        "manual_taste_desirability_delta": desirability_delta,
        "manual_taste_quality_floor": quality_floor,
        "manual_taste_pattern_floor": pattern_floor,
        "manual_taste_price": price,
        "manual_taste_rrl_pattern": rrl_hit,
    }


def apply_manual_taste_profile(result: dict, profile: dict) -> dict:
    result.update(profile)
    if not profile.get("manual_taste_match"):
        return result
    old_des = float(result.get("desirability_score", 0) or 0)
    old_quality = float(result.get("signal_quality_score", 0) or 0)
    old_pattern = int(result.get("pattern_score", 0) or 0)
    result["desirability_score"] = _clip_score(old_des + float(profile.get("manual_taste_desirability_delta", 0) or 0))
    result["signal_quality_score"] = max(old_quality, float(profile.get("manual_taste_quality_floor", 0) or 0))
    result["pattern_score"] = max(old_pattern, int(profile.get("manual_taste_pattern_floor", 0) or 0))
    signals = result.get("desirable_signals", []) or []
    _add_unique(signals, profile.get("manual_taste_signals", []) or [])
    result["desirable_signals"] = signals
    if "rrl_double_rl_mega_signal" in signals:
        result["rrl_double_rl_signal"] = True
        if float(profile.get("manual_taste_price", 0) or 0) <= 300:
            result["tier"] = result["signal_tier"] = "TIER_A"
            if result.get("engine") in ("GRAIL", "BRAND"):
                result["send"] = result["send_alert"] = True
                result["is_grail"] = result.get("engine") == "GRAIL"
                result["grail_score"] = max(int(result.get("grail_score", 0) or 0), 3)
        if DEBUG_ALERTS:
            title = str((result.get("item") or {}).get("title") or "")[:60]
            print(f"  [RRL_BOOST] matched_pattern={profile.get('manual_taste_rrl_pattern')} "
                  f"signals={[s for s in signals if s.startswith('rrl_')]} "
                  f"desirability={result.get('desirability_score', 0):.0f} "
                  f"quality={result.get('signal_quality_score', 0):.0f} "
                  f"pattern={result.get('pattern_score', 0)} "
                  f"price={profile.get('manual_taste_price', 0):.0f} title={title}")
    if DEBUG_ALERTS:
        title = str((result.get("item") or {}).get("title") or "")[:60]
        print(f"  [MANUAL_TASTE_MATCH] signals={profile.get('manual_taste_signals', [])} "
              f"desirability={result.get('desirability_score', 0):.0f} "
              f"quality={result.get('signal_quality_score', 0):.0f} "
              f"price={profile.get('manual_taste_price', 0):.0f} title={title}")
    return result


def compute_taste_watch_score(item: dict, result: dict) -> dict:
    item = item or {}
    result = result or {}
    title = str(item.get("title") or "")
    text_l = _item_search_text(item, result)
    brand_l = str(result.get("brand") or result.get("brand_detected") or item.get("brand") or "").lower()
    category = result.get("category") or detect_category(title) or ""
    price = float(item.get("price") or 0)
    age = item_age_minutes(item)
    size_bucket = _taste_size_bucket(item, text_l)
    clothing_ok = _taste_item_type(text_l, category)
    taste_signals: list[str] = []
    taste_penalties: list[str] = []
    buckets: set[str] = set()
    score = 0

    def add(name: str, points: int, bucket: str | None = None):
        nonlocal score
        score += points
        if name not in taste_signals:
            taste_signals.append(name)
        if bucket:
            buckets.add(bucket)

    def penalty(name: str, points: int):
        nonlocal score
        score -= points
        if name not in taste_penalties:
            taste_penalties.append(name)

    visual_hit = _first_hit(text_l, TASTE_VISUAL_SIGNALS)
    era_hit = _first_hit(text_l, TASTE_ERA_SIGNALS)
    street_hit = _first_hit(text_l, TASTE_STREETWEAR_CHEAP_SIGNALS)
    if _sports_taste_hit(text_l):
        add("taste_vintage_sports", 30, "sports")
    if _first_hit(text_l, VINTAGE_BLANK_TAGS):
        add("taste_old_blank_tag", 30, "old_blank")
    rrl_taste_hit = _first_rrl_match(text_l)
    if rrl_taste_hit:
        add("taste_rrl_double_rl", 30, "heritage")
        if _first_hit(text_l, RRL_STYLE_SIGNALS):
            add("taste_rrl_western_heritage", 20, "heritage")
        if price <= 250:
            add("taste_rrl_good_price", 15, "heritage")
    if _first_hit(text_l, TASTE_BIKER_EVENT_SIGNALS + HARLEY_DEALER_LOCATION_SIGNALS):
        add("taste_biker_event", 25, "biker")
    if "harley" in text_l and _first_hit(text_l, HARLEY_DEALER_LOCATION_SIGNALS):
        add("taste_harley_dealer_graphic", 20, "biker")
    if _first_hit(text_l, TASTE_METAL_FANTASY_BAND_SIGNALS):
        add("taste_metal_fantasy_band", 25, "metal")
    lee_taste_hit = _lee_taste_hit(text_l, brand_l)
    workwear_taste_hit = _first_hit(text_l, WORKWEAR_COMPANY_STRONG_SIGNALS)
    workwear_taste_ok = bool(
        category in ("jacket", "coat", "vest")
        or any(k in text_l for k in ["jacket", "coat", "vest", "workwear", "duck canvas"])
        or any(k in brand_l for k in ["carhartt", "dickies", "red kap"])
        or lee_taste_hit
    )
    if lee_taste_hit or (workwear_taste_hit and workwear_taste_ok):
        add("taste_workwear_heritage", 25, "workwear")
        if lee_taste_hit and price <= 130:
            add("taste_lee_good_price", 15, "workwear")
    ralph_taste_hit = _first_hit(text_l, RALPH_LAUREN_DESIRABLE_SIGNALS)
    if ralph_taste_hit and any(k in text_l or k in brand_l for k in ["ralph", "polo"]):
        add("taste_ralph_graphic_spellout", 25, "heritage")
        if price <= 80:
            add("taste_ralph_good_price", 15, "heritage")
    if _first_hit(text_l, TASTE_POP_CULTURE_SIGNALS):
        add("taste_pop_culture", 20, "pop_culture")
    if street_hit:
        add("taste_cheap_streetwear", 20, "streetwear")
        if price <= 30:
            add("taste_very_cheap_streetwear", 15, "streetwear")
    if visual_hit:
        add("taste_visual_graphic", 15)
    if era_hit:
        add("taste_year_era", 15)
    if size_bucket == "large":
        add("taste_good_resale_size", 10)
    elif size_bucket == "medium":
        add("taste_ok_resale_size", 5)
    if price <= 30:
        add("taste_price_<=30", 20)
    elif price <= 50:
        add("taste_price_<=50", 15)
    elif price <= 80:
        add("taste_price_<=80", 10)

    fast_fashion = _taste_fast_fashion(text_l, brand_l)
    if fast_fashion:
        penalty("fast_fashion", 40)
    if any(k in text_l for k in ["fake", "inspired", "unofficial", "replica"]):
        penalty("fake_inspired_unofficial", 30)
    if any(k in text_l for k in ["very poor", "destroyed", "holes", "stained", "plamy", "dziury"]):
        penalty("very_poor_condition", 25)
    has_context = _has_real_taste_signal(taste_signals)
    if any(k in text_l for k in ["blank", "plain", "basic"]) and not visual_hit and not has_context:
        penalty("generic_blank_no_context", 30)
    if brand_l in CONDITIONAL_STRONG_BRANDS and not visual_hit and not has_context:
        penalty("generic_brand_no_visual_context", 25)

    bucket = "none"
    for preferred in ("heritage", "workwear", "sports", "old_blank", "biker", "pop_culture", "metal", "streetwear"):
        if preferred in buckets:
            bucket = preferred
            break
    score = round(_clip_score(score), 2)
    hard_reason = ""
    if fast_fashion or "fake_inspired_unofficial" in taste_penalties:
        hard_reason = "fake_or_fast_fashion"
    elif result.get("carhartt_size_skip"):
        hard_reason = "small_carhartt_pants"
    elif result.get("generic_conditional_brand_shirt"):
        hard_reason = "generic_conditional_brand_shirt_block"
    elif result.get("is_low_quality_aesthetic"):
        hard_reason = "low_quality_aesthetic_hard_block"
    elif not clothing_ok:
        hard_reason = "non_clothing_style_watch_block"

    real_taste_signal = _has_real_taste_signal(taste_signals)
    if age <= 30 and score >= 55 and price <= 50 and real_taste_signal and not hard_reason:
        old_score = score
        score = min(100, score + 10)
        signals = result.get("desirable_signals", []) or []
        if "fresh_low_price_style" not in signals:
            signals.append("fresh_low_price_style")
        result["desirable_signals"] = signals
        if "taste_fresh_low_price_style" not in taste_signals:
            taste_signals.append("taste_fresh_low_price_style")
        if DEBUG_ALERTS:
            print(f"  [TASTE_FRESH_BOOST] old={old_score:.0f} new={score:.0f} "
                  f"price={price:.0f} age={age} title={title[:60]}")

    if taste_signals and not hard_reason:
        old_score = score
        if len(taste_signals) >= 2:
            score = max(score, 50)
        else:
            score = max(score, 30)
        if DEBUG_ALERTS and score != old_score:
            print(f"  [TASTE_SCORE_FLOOR] old={old_score:.0f} new={score:.0f} "
                  f"signals={taste_signals} title={title[:60]}")

    streetwear_size_ok = bool(street_hit and price <= 30 and size_bucket in ("medium", "large") and not fast_fashion)
    candidate = bool(
        TASTE_WATCH_ENABLED
        and not hard_reason
        and (
            (score >= 60 and price <= 160 and real_taste_signal)
            or (score >= 50 and price <= 50 and len(taste_signals) >= 2)
            or streetwear_size_ok
        )
    )
    if TASTE_WATCH_ENABLED:
        print(f"  [TASTE_WATCH] score={score:.0f} bucket={bucket} "
              f"signals={taste_signals} price={price:.0f} title={title[:60]}")
        if candidate:
            print(f"  [TASTE_WATCH_CANDIDATE] score={score:.0f} bucket={bucket} "
                  f"signals={taste_signals} price={price:.0f} title={title[:60]}")
        elif hard_reason and score > 0:
            print(f"  [TASTE_WATCH_BLOCK] reason={hard_reason} score={score:.0f} "
                  f"signals={taste_signals} title={title[:60]}")

    return {
        "taste_watch_score": score,
        "taste_signals": taste_signals,
        "taste_penalties": taste_penalties,
        "taste_watch_candidate": candidate,
        "taste_bucket": bucket,
        "taste_watch_hard_block_reason": hard_reason,
    }


def apply_taste_watch_profile(result: dict, profile: dict) -> dict:
    result.update(profile)
    if profile.get("taste_watch_candidate"):
        result["watch_candidate"] = True
        result["taste_watch_candidate"] = True
        result["watch_reason"] = "taste_watch_match"
    return result


def enforce_signal_quality(result: dict) -> dict:
    """
    Final hard gate after Signal Await profile is applied.
    Can only block/downgrade; it never promotes a non-send result.
    """
    item = result.get("item", {}) or {}
    full_title = str(item.get("title") or "")
    title = full_title[:60]
    quality = float(result.get("signal_quality_score", 0) or 0)
    tier = result.get("tier") or result.get("signal_tier") or "TIER_C"
    profit = float(result.get("profit", 0) or result.get("estimated_profit", 0) or 0)
    price = float(item.get("price") or 0)
    confidence = float(result.get("confidence", 0) or 0)
    engine = result.get("engine", "") or ""
    await_state = result.get("await_state", {}) or {}
    protection = result.get("protection_reasons", []) or []
    desirability = float(result.get("desirability_score", 0) or 0)
    desirable_signals = result.get("desirable_signals", []) or []
    generic_penalties = result.get("generic_penalties", []) or []
    pattern_score = int(result.get("pattern_score", 0) or 0)
    brand = result.get("brand") or result.get("brand_detected") or ""
    title_l = full_title.lower()
    brand_l = str(brand or "").lower()

    result["tier"] = tier
    result["signal_tier"] = result.get("signal_tier") or tier

    hard_watch_blockers = {
        "carhartt_pants_small_size_skip",
        "generic_conditional_brand_shirt_block",
        "low_quality_aesthetic_blocked",
        "protected_signal_blocked",
    }

    def _can_watch(reason: str) -> bool:
        hard_penalty = (
            reason in hard_watch_blockers
            or result.get("carhartt_size_skip")
            or result.get("is_low_quality_aesthetic")
            or any(p in protection for p in ("fast_fashion_auth_penalty", "fast_fashion", "foreign_title_block", "foreign_low_value"))
            or any("fast_fashion" in str(p) for p in generic_penalties)
            or any(token in str(result.get("reason", "")) for token in ("foreign_low_value", "foreign_language", "fake_vintage_fast_fashion"))
            or any(token in str(result.get("_skip_reason", "")) for token in ("foreign_language", "low_value_item"))
        )
        watch_signal = (
            (quality >= 50 and desirability >= 40 and profit >= 50)
            or (tier == "TIER_B" and profit >= 40)
            or (pattern_score >= 3 and profit >= 35)
            or (bool(desirable_signals) and profit >= 35)
            or bool(result.get("taste_watch_candidate"))
        )
        if reason == "weak_harley_generic_top":
            watch_signal = bool(result.get("taste_watch_candidate")) or (profit >= 60 and quality >= 50)
        return bool(
            not hard_penalty
            and watch_signal
        )

    def _block(reason: str) -> dict:
        result["send"] = False
        result["send_alert"] = False
        result["quality_pass"] = False
        result["_quality_block_reason"] = reason
        if _can_watch(reason):
            result["watch_candidate"] = True
            result["_watch_original_reason"] = reason
            result["_quality_block_reason"] = "watch_only_candidate"
            if DEBUG_ALERTS:
                print(f"  [WATCH_CANDIDATE] engine={engine} quality={quality:.0f} "
                      f"desirability={desirability:.0f} profit={profit:.0f} "
                      f"pattern={pattern_score} signals={desirable_signals} "
                      f"block_reason={reason} title={title}")
        else:
            result["watch_candidate"] = False
            if result.get("taste_watch_candidate"):
                result["taste_watch_candidate"] = False
                if DEBUG_ALERTS:
                    print(f"  [TASTE_WATCH_BLOCK] reason={reason} "
                          f"score={result.get('taste_watch_score',0):.0f} "
                          f"signals={result.get('taste_signals', [])} title={title}")
        if DEBUG_ALERTS:
            print(f"  [SIGNAL_BLOCK] reason={result.get('_quality_block_reason', reason)} "
                  f"engine={engine} tier={tier} "
                  f"quality={quality:.0f} profit={profit:.0f} conf={confidence:.1f} "
                  f"await={await_state.get('hold', False)} protection={protection} "
                  f"title={title}")
        return result

    def _desirability_block(reason: str) -> dict:
        if DEBUG_ALERTS:
            print(f"  [DESIRABILITY_BLOCK] reason={reason} brand={brand or '-'} "
                  f"score={desirability:.0f} signals={desirable_signals} title={title}")
        return _block(reason)

    if result.get("carhartt_size_skip"):
        return _desirability_block("carhartt_pants_small_size_skip")

    if result.get("generic_conditional_brand_shirt"):
        return _desirability_block("generic_conditional_brand_shirt_block")

    is_harley = bool("harley davidson" in title_l or "harley-davidson" in title_l or "harley" in title_l or "harley" in brand_l)
    if is_harley:
        harley_hits = _keyword_hits_lower(title_l, HARLEY_STRONG_ITEM_SIGNALS)
        harley_auth_hits = _keyword_hits_lower(title_l, [
            "single stitch", "made in usa", "made in the usa", "90s",
            "80s", "3d emblem", "sturgis", "daytona",
        ])
        weak_type_hit = _first_hit(title_l, HARLEY_WEAK_GENERIC_TYPES)
        weak_harley_top = bool(
            (tier == "TIER_C" or engine == "GRAIL" or result.get("is_grail"))
            and (result.get("category") in ("tshirt", "shirt", "top") or weak_type_hit)
            and len(set(harley_hits)) < 2
            and pattern_score < 4
            and not harley_auth_hits
        )
        if weak_harley_top:
            result["is_grail"] = False
            result["grail_score"] = min(int(result.get("grail_score", 0) or 0), 2)
            result["confidence"] = min(float(result.get("confidence", 0) or 0), 6.5)
            result["signal_quality_score"] = min(float(result.get("signal_quality_score", 0) or 0), 58.0)
            confidence = float(result.get("confidence", 0) or 0)
            quality = float(result.get("signal_quality_score", 0) or 0)
            if DEBUG_ALERTS:
                print(f"  [WEAK_HARLEY_DOWNGRADE] reason=generic_top_no_strong_signal title={title}")
            if engine != "CHAOS":
                return _block("weak_harley_generic_top")

    if result.get("carhartt_is_basic_tee"):
        strong_auth = bool(
            result.get("auth_state") == "strong"
            or result.get("authenticity_hits")
            or any(v in title.lower() for v in DESIRABLE_VINTAGE)
        )
        if not (pattern_score >= 5 or quality >= 80 or (price <= 40 and strong_auth)):
            if DEBUG_ALERTS:
                print(f"  [CARHARTT_BASIC_TEE_BLOCK] reason=basic_tee_no_strong_pattern title={title}")
            return _desirability_block("carhartt_basic_tee_blocked")

    if result.get("is_generic_strong_brand"):
        if not (profit >= 100 and quality >= 75 and desirability >= 60):
            return _desirability_block("generic_strong_brand_blocked")

    if generic_penalties and not desirable_signals:
        strong_pattern_exception = bool(
            engine == "GRAIL"
            and pattern_score >= 5
            and profit >= 50
            and quality >= 60
            and not any("fast_fashion" in str(p) for p in generic_penalties)
        )
        if not strong_pattern_exception:
            return _desirability_block("generic_item_no_desirable_signal")

    if pattern_score == 0 and desirability < 60:
        grail_brand_borderline = bool(
            engine == "GRAIL"
            and brand_l in GRAIL_ELIGIBLE_BRANDS
            and profit >= 60
            and quality >= 60
            and desirability >= 45
            and not any(p in protection for p in ("fast_fashion_auth_penalty", "band_tee_auth_signals_lt_2"))
        )
        if not ((engine == "GRAIL" and tier in ("TIER_S", "TIER_A")) or grail_brand_borderline):
            return _desirability_block("no_pattern_low_desirability")

    if engine == "CHAOS":
        chaos_tier_b_allow = bool(
            tier == "TIER_B"
            and profit >= 80
            and quality >= 60
            and desirability >= 55
            and pattern_score >= 3
        )
        if not (desirability >= 65 or pattern_score >= 5 or tier == "TIER_S" or chaos_tier_b_allow):
            return _desirability_block("chaos_low_desirability")

    if tier == "TIER_C":
        return _block("tier_c_blocked")

    if result.get("is_low_quality_aesthetic"):
        return _block("low_quality_aesthetic_blocked")

    if engine == "CHAOS" and any("low_effort" in p for p in result.get("matched_patterns", [])):
        return _block("chaos_low_effort_blocked")

    protected = any(p in protection for p in (
        "fast_fashion_auth_penalty",
        "band_tee_auth_signals_lt_2",
    ))
    if protected:
        result["is_grail"] = False
        result["grail_score"] = min(int(result.get("grail_score", 0) or 0), 2)
        if not (engine == "CHAOS" and quality >= 65 and profit >= 50):
            return _block("protected_signal_blocked")

    if await_state.get("hold"):
        if not (tier in ("TIER_S", "TIER_A") and quality >= 70 and profit >= 50):
            return _block("await_hold_blocked")

    if engine == "CHAOS":
        if quality < 60 or profit < 40 or confidence < 6.0:
            return _block("chaos_quality_floor")
    elif engine == "BRAND":
        if quality < 55 or profit < 25:
            return _block("brand_quality_floor")
    elif engine == "GRAIL":
        fake_or_fast_fashion = bool(
            any(p in protection for p in ("fast_fashion_auth_penalty", "band_tee_auth_signals_lt_2"))
            or any("fast_fashion" in str(p) for p in generic_penalties)
        )
        hard_protection = fake_or_fast_fashion or result.get("is_low_quality_aesthetic")
        tier_c_ok = tier != "TIER_C" or (pattern_score >= 6 and profit >= 80)
        harley_strong = bool(
            "harley_strong_item_signal" in desirable_signals
            or (
                ("harley" in brand_l or "harley" in title_l)
                and len(set(_keyword_hits_lower(title_l, HARLEY_STRONG_ITEM_SIGNALS))) >= 2
            )
        )
        band_name = result.get("band") or detect_band(title)
        band_auth_ok = bool(band_name and len(set(result.get("authenticity_hits") or [])) >= 2)
        rrl_strong = bool(
            result.get("rrl_double_rl_signal")
            and price <= 300
            and quality >= 70
            and desirability >= 80
        )
        grail_allowed = bool(
            tier_c_ok
            and not hard_protection
            and (
                (quality >= 65 and profit >= 50)
                or (pattern_score >= 5 and profit >= 50 and quality >= 60)
                or (brand_l in GRAIL_ELIGIBLE_BRANDS and profit >= 60 and quality >= 60 and desirability >= 45)
                or (harley_strong and profit >= 50 and quality >= 60)
                or (band_auth_ok and profit >= 50 and quality >= 60)
                or rrl_strong
            )
        )
        grail_exception = tier == "TIER_S" and profit >= 40
        if not (grail_allowed or grail_exception):
            return _block("grail_quality_floor")

    if DEBUG_ALERTS and result.get("send_alert"):
        print(f"  [DESIRABILITY_PASS] brand={brand or '-'} score={desirability:.0f} "
              f"signals={desirable_signals} title={title}")

    return result


_TEE_TYPES    = ["tee", "t-shirt", "tshirt", "shirt", "koszulka"]
_DENIM_TYPES  = ["jeans", "denim", "dżinsy", "pants", "trousers", "spodnie"]
_HOODIE_TYPES = ["hoodie", "zip", "bluza", "sweatshirt", "crewneck"]

def compute_pattern_score(title: str, brand: str | None, band: str | None) -> tuple[int, list[str]]:
    """
    Compute pattern_score from keyword combinations.
    Returns (total_score, matched_pattern_names).
    Category enforcement: patterns only trigger if item type matches.

    +3  vintage_signal + tee
    +4  band + (tour OR 90s OR single stitch OR made in usa)
    +5  band + tour + vintage_signal
    +4  harley + (flame OR skull OR eagle) + vintage
    +3  denim brand + (faded OR bootcut OR usa)
    +2  rarity + brand
    -2  LOW_EFFORT keywords (penalty)
    """
    t       = title.lower()
    score   = 0
    matched: list[str] = []

    is_tee    = any(tp in t for tp in _TEE_TYPES)
    is_denim  = any(dp in t for dp in _DENIM_TYPES)

    # +3: vintage_signal + tee (category enforced)
    if is_tee and any(vs in t for vs in VINTAGE_SIGNALS):
        score += 3
        hit = next(vs for vs in VINTAGE_SIGNALS if vs in t)
        matched.append(f"vintage_signal_tee({hit})(+3)")

    # Band patterns (category: tee or hoodie preferred but not enforced — band merch is always a tee)
    if band:
        # +4: band + (tour OR 90s OR single stitch OR made in usa)
        _band_boosters = ["tour", "90s", "single stitch", "made in usa",
                          "vintage", "deadstock", "80s", "70s"]
        _hits = [b for b in _band_boosters if b in t]
        if _hits:
            # +5 if ALSO has vintage_signal (stronger combo)
            has_vs = any(vs in t for vs in VINTAGE_SIGNALS)
            if "tour" in _hits and has_vs:
                score += 5
                matched.append(f"band_tour_vintage({band})(+5)")
            else:
                score += 4
                matched.append(f"band_context({band},{_hits[0]})(+4)")

    # +4: harley + (flame OR skull OR eagle) + vintage (category: not enforced, moto merch)
    _harley_present = any(h in t for h in ["harley davidson", "harley-davidson", "harley"])
    _harley_imagery = ["flame", "skull", "eagle", "sturgis", "daytona", "bike week"]
    _harley_era     = ["90s", "80s", "vintage", "2000s"]
    if _harley_present:
        _img_hit = next((h for h in _harley_imagery if h in t), None)
        _era_hit = next((e for e in _harley_era if e in t), None)
        if _img_hit and _era_hit:
            score += 4
            matched.append(f"harley_imagery_vintage({_img_hit},{_era_hit})(+4)")
        elif _img_hit:
            # Harley safeguard: imagery alone without era → +2 only
            score += 2
            matched.append(f"harley_imagery({_img_hit})(+2)")
        # else: plain harley mention without imagery → no pattern bonus

    # +3: denim brand + (faded OR bootcut OR usa) — category enforced: jeans/pants
    _denim_brand_variants = [d.strip() for d in DENIM_KEYWORDS]
    if is_denim and any(db in t for db in _denim_brand_variants):
        _denim_q = ["faded", "bootcut", "made in usa", "wash", "distressed",
                    "raw denim", "selvedge", "usa made"]
        _dq_hit = next((d for d in _denim_q if d in t), None)
        if _dq_hit:
            _brand_hit = next(db for db in _denim_brand_variants if db in t)
            score += 3
            matched.append(f"denim_premium({_brand_hit},{_dq_hit})(+3)")

    # +2: rarity keyword present (bonus for any item with rarity signal + quality context)
    _rar_hit = next((r for r in RARITY_KEYWORDS if r in t), None)
    if _rar_hit:
        # +2 always when rarity present (brand amplifies value)
        # Even no-brand items with deadstock/rare/nos deserve the signal
        if brand or band or any(vs in t for vs in VINTAGE_SIGNALS):
            score += 2
            matched.append(f"rarity_signal({brand or band or 'vintage'},{_rar_hit})(+2)")

    # LOW_EFFORT penalty (-2 from confidence, returned as negative score)
    _le_hit = next((le for le in LOW_EFFORT if le in t), None)
    if _le_hit:
        score -= 2
        matched.append(f"low_effort({_le_hit})(-2)")

    return score, matched


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
        no_market_data = not bool(market_price)
        real_signal_hits = [
            sig for sig in [
                "single stitch", "made in usa", "made in u.s.a", "80s", "90s", "00s",
                "official", "licensed", "copyright", "tour", "race", "racing",
                "movie promo", "back print", "front print", "double sided",
                "big print", "large graphic", "sturgis", "daytona", "bike week",
                "skull", "flame", "eagle", "rrl", "double rl", "nascar",
                "warner bros", "taz motorcycle",
            ]
            if sig in title.lower()
        ]

        estimated_value = market_price if market_price else price
        profit          = (estimated_value - price) if market_price else 0

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

        # ── PATTERN SCORING (core system) ─────────────────
        pattern_score, matched_patterns = compute_pattern_score(title, brand, band)

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

        # Pattern score → confidence boost (positive patterns only)
        pos_pattern = max(0, pattern_score)   # exclude LOW_EFFORT penalty from boost
        if pos_pattern >= 5:  confidence += 2.0
        elif pos_pattern >= 3: confidence += 1.0
        elif pos_pattern >= 1: confidence += 0.5

        # LOW_EFFORT penalty (spec: -2.0 confidence)
        if any("low_effort" in p for p in matched_patterns):
            confidence -= 2.0

        confidence = round(min(max(confidence, 0.0), 10.0), 2)
        if no_market_data and len(real_signal_hits) < 3:
            confidence = min(confidence, 5.5)
            if DEBUG_ALERTS:
                log_no_market_data_cap(title, real_signal_hits)

        if profit < 10 and anomaly_score == 0 and pattern_score <= 0:
            return {**base, "_skip_reason": "low_profit_no_anomaly",
                    "confidence": confidence, "profit": round(profit, 2),
                    "pattern_score": pattern_score, "matched_patterns": matched_patterns}

        # CHAOS send rule (spec thresholds: profit>=40, conf>=6)
        is_strong_brand     = brand in STRONG_BRANDS
        is_band             = bool(features.get("band"))
        is_strong_band_feat = features.get("is_strong_band", False)

        send = (
                # Spec: CHAOS profit >= 40 AND conf >= 6
                (profit >= 40 and confidence >= 6.0)
                # Pattern shortcut: high pattern score unlocks lower profit threshold
                or (pattern_score >= 5 and profit >= 30 and confidence >= 5.5)
                # Strong brand — lower profit bar
                or (profit >= 30 and is_strong_brand and confidence >= 5.0)
                # Band brand + vintage
                or (profit >= 20 and is_band and is_strong_band_feat and confidence >= 5.0)
                # Anomaly + brand
                or (profit >= 20 and anomaly_score >= 2 and is_strong_brand)
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

        # Task 6 — debug log with pattern info
        if DEBUG_ALERTS:
            action = "📤 ALERT" if send else "⏭  SKIP"
            print(f"  {action}: conf={confidence:.1f} profit={profit:.0f} "
                  f"pattern_score={pattern_score} anomaly={anomaly_score} "
                  f"brand={brand or '—'} strong={is_strong_brand}")
            if matched_patterns:
                print(f"    matched_patterns={matched_patterns}")

        return {
            **base,
            "send_alert":       send,
            "profit":           round(profit, 2),
            "estimated_value":  round(estimated_value, 2),
            "market_price":     round(market_price, 2) if market_price else None,
            "no_market_data":   no_market_data,
            "real_signal_hits": real_signal_hits,
            "confidence":       confidence,
            "anomaly_score":    anomaly_score,
            "pattern_score":    pattern_score,
            "matched_patterns": matched_patterns,
            "brand":            brand,
            "category":         cat,
            "is_strong_brand":  is_strong_brand,
            "age_min":          age,
            "deal_tag":         deal_tag,
            "_skip_reason":     None if send else "below_threshold",
        }


# Heurystyczne ceny rynkowe per brand+category (gdy brak DB)
_HEURISTIC_PRICES: dict[str, dict[str, float]] = {
    "patagonia":     {"jacket": 500, "hoodie": 350, "default": 280},
    "supreme":       {"jacket": 600, "hoodie": 350, "tshirt": 280, "default": 300},
    "palace":        {"jacket": 500, "hoodie": 300, "tshirt": 250, "default": 250},
    "stussy":        {"jacket": 350, "hoodie": 250, "tshirt": 180, "default": 200},
    "corteiz":       {"jacket": 500, "hoodie": 300, "tshirt": 200, "default": 250},
    "carhartt":      {"jacket": 350, "hoodie": 220, "tshirt": 130, "default": 180},
    "dickies":       {"jacket": 200, "cargo": 150, "default": 120},
    "helly hansen":  {"jacket": 350, "hoodie": 220, "default": 200},
    "asics":         {"sneakers": 200, "default": 150},
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
    "harley tee":      {"tshirt": 200, "default": 180},
    # Band brands — mid-tier pricing (priced for vintage era originals)
    "nirvana":        {"tshirt": 280, "hoodie": 200, "default": 220},
    "metallica":      {"tshirt": 250, "hoodie": 180, "default": 200},
    "pink floyd":     {"tshirt": 220, "hoodie": 160, "default": 180},
    "acdc":           {"tshirt": 200, "hoodie": 150, "default": 160},
    "ac/dc":          {"tshirt": 200, "hoodie": 150, "default": 160},
    "ramones":        {"tshirt": 200, "hoodie": 150, "default": 160},
    "grateful dead":  {"tshirt": 350, "hoodie": 250, "default": 280},
    "led zeppelin":   {"tshirt": 220, "hoodie": 160, "default": 180},
    "rolling stones": {"tshirt": 200, "hoodie": 150, "default": 160},
    "black sabbath":  {"tshirt": 200, "hoodie": 150, "default": 160},
    "iron maiden":    {"tshirt": 200, "hoodie": 150, "default": 160},
    "slipknot":       {"tshirt": 180, "hoodie": 140, "default": 150},
    # Vintage tag brands
    "hanes beefy":    {"tshirt": 100, "default": 80},
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
    "ac/dc", "acdc",
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

        # Fix 2 — Band brand boost score
        if is_band:
            score += 2   # band = traktowany jak grail-eligible brand

        # ── PATTERN SCORING ────────────────────────────────
        pattern_score, matched_patterns = compute_pattern_score(title, brand, band)

        # LOW_EFFORT → grail = False (spec rule)
        has_low_effort = any("low_effort" in p for p in matched_patterns)
        if has_low_effort:
            if DEBUG_ALERTS:
                print(f"  [QUALITY] skip_reason=low_effort_grail_blocked | {title[:50]}")
            return {**base, "_skip_reason": "low_effort_grail_blocked",
                    "pattern_score": pattern_score, "matched_patterns": matched_patterns}

        # Grail scoring (classic keywords)
        score   = 0
        kw_hits = sum(1 for k in _GRAIL_KEYWORDS if k in t)
        if kw_hits >= 1:   score += 2
        if kw_hits >= 2:   score += 1

        if kw(title, _GRAIL_BRANDS):   score += 2
        if "tour"          in t: score += 1
        if "single stitch" in t: score += 1
        if "band" in t and ("tee" in t or "shirt" in t or "tour" in t): score += 1
        if "bootleg"       in t: score += 1
        if features["is_vintage"]:     score += 1
        if is_band:                    score += 2   # band = grail-eligible

        # Pattern score feeds into grail score
        pos_ps = max(0, pattern_score)
        score += pos_ps // 2   # +1 per 2 pattern points (no double counting)

        # ── SPEC GRAIL LOGIC ───────────────────────────────
        # ALLOW grail if: pattern_score >= 5 AND (rarity OR brand in STRONG_BRANDS)
        #              OR: brand in GRAIL_BRANDS AND rarity
        # BLOCK grail if: only LOW_EFFORT, generic Y2K, no real pattern
        has_rarity_hit  = any(r in t for r in RARITY_KEYWORDS)
        has_grail_brand = brand in GRAIL_ELIGIBLE_BRANDS if brand else False

        if pattern_score >= 5 and (has_rarity_hit or brand in STRONG_BRANDS or is_band):
            is_grail_qualified = True   # spec CASE 1: pattern>=5 + quality signal
        elif has_grail_brand and has_rarity_hit:
            is_grail_qualified = score >= 3   # spec CASE 2: grail brand + rarity
        elif is_band and (has_rarity_hit or has_rarity):
            is_grail_qualified = score >= 3
        elif is_band and pattern_score >= 4:
            is_grail_qualified = score >= 3   # band + strong pattern (tour+vintage)
        elif has_rarity and kw_hits >= 2:
            is_grail_qualified = score >= 4
        else:
            is_grail_qualified = False

        estimated = self._estimate_value(title, price, score)
        profit    = estimated - price

        # Undervaluation
        anomaly_score = 0
        if estimated > 0 and price < estimated * 0.70:
            anomaly_score = 2
            if is_grail_qualified: score += 2
        elif estimated > 0 and price < estimated * 0.85:
            anomaly_score = 1
            if is_grail_qualified: score += 1

        is_grail = is_grail_qualified and score >= 3
        conf     = float(score) * 1.2 + freshness_boost(age) * 0.4
        if has_grail_brand:
            conf = max(conf, brand_strength(brand))
        # LOW_EFFORT penalty on confidence
        if has_low_effort:
            conf -= 2.0
        conf = round(min(max(conf, 0.0), 10.0), 2)

        # Spec threshold: GRAIL profit >= 50 AND pattern_score >= 5
        send = (
                # Spec: GRAIL profit >= 50 AND pattern_score >= 5
                (is_grail and profit >= 50 and pattern_score >= 5)
                # OR: grail + high profit even without full pattern
                or (is_grail and profit >= 30 and anomaly_score >= 2)
            )

        # DB learning
        if cat:
            self.db.add_sample(f"grail_{cat}", price)
            self.db.add_sample(f"chaos_{cat}", price)
        if features["has_brand"] and cat:
            self.db.add_sample(f"{brand}_{cat}", price)
        elif cat:
            self.db.add_sample(f"{cat}_unknown", price)

        # Task 6 — debug log with pattern info
        if DEBUG_ALERTS:
            action = "📤 ALERT" if send else "⏭  SKIP"
            print(f"  {action}: conf={conf:.1f} profit={profit:.0f} "
                  f"grail_score={score} pattern_score={pattern_score} "
                  f"grail={is_grail} rarity={has_rarity_hit} | {title[:40]}")
            if matched_patterns:
                print(f"    matched_patterns={matched_patterns}")

        return {
            **base,
            "send_alert":       send,
            "is_grail":         is_grail,
            "grail_score":      score,
            "profit":           round(profit, 2),
            "estimated_value":  round(estimated, 2),
            "confidence":       conf,
            "anomaly_score":    anomaly_score,
            "pattern_score":    pattern_score,
            "matched_patterns": matched_patterns,
            "brand":            brand,
            "category":         cat,
            "is_grail_brand":   has_grail_brand,
            "has_rarity":       has_rarity_hit,
            "age_min":          age,
            "_skip_reason":     None if send else ("not_grail" if not is_grail else "low_profit_pattern"),
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
    """Formatuje alert Telegram. GRAIL/BRAND/CHAOS + Task 7 spec output."""
    engine   = result.get("engine", "?")
    item     = result.get("item", {})
    title    = item.get("title", "")
    price    = item.get("price", 0)
    profit   = result.get("profit", 0) or result.get("estimated_profit", 0)
    conf     = result.get("confidence", 0)
    brand    = result.get("brand") or result.get("brand_detected") or ""
    category = result.get("category") or ""
    age_min  = result.get("age_min", 0) or 0
    is_grail = result.get("is_grail", False)
    est_val  = result.get("estimated_value") or result.get("median_price") or 0

    # Task 7 spec fields
    pattern_score    = result.get("pattern_score", 0)
    matched_patterns = result.get("matched_patterns", [])
    final_score      = result.get("final_score", 0)
    rank_pos         = result.get("ranking_position")
    flags            = result.get("flags", {})
    has_vintage      = flags.get("vintage_signal", False)
    has_rarity       = flags.get("rarity", False)
    is_low_effort    = flags.get("low_effort", False)
    fast_snipe       = flags.get("fast_snipe", False) or result.get("fast_snipe", False)
    quality_pass     = flags.get("quality_pass", True) or result.get("quality_pass", True)

    clean = re.sub(r',?\s*(marka|stan|rozmiar|brand|size|condition):.*',
                   '', title, flags=re.IGNORECASE).strip()

    # Header — sniper gets ⚡ prefix
    snipe_prefix = "⚡ SNIPER  · " if fast_snipe else ""
    rank_str     = f"#{rank_pos}  · " if rank_pos else ""

    if is_grail:
        header = f"{snipe_prefix}{rank_str}💎 GRAIL  · score={result.get('grail_score',0)} pattern={pattern_score}"
    elif result.get("is_soft_grail"):
        header = f"{snipe_prefix}{rank_str}✨ SOFT GRAIL  · pattern={pattern_score}"
    elif result.get("band"):
        header = f"{snipe_prefix}{rank_str}🎸 BAND  · {result.get('band','').upper()}  · pattern={pattern_score}"
    elif engine == "CHAOS":
        header = f"{snipe_prefix}{rank_str}🔵 CHAOS FLIP  · pattern={pattern_score}"
    elif engine == "BRAND":
        header = f"{snipe_prefix}{rank_str}🟣 BRAND DEAL  · pattern={pattern_score}"
    else:
        header = f"{snipe_prefix}{rank_str}⚪ DEAL  · pattern={pattern_score}"

    style_watch_alert = bool(
        result.get("style_watch_sent")
        or (
            result.get("taste_watch_candidate")
            and result.get("_quality_block_reason") == "watch_only_candidate"
        )
    )

    if result.get("watch_candidate") and not style_watch_alert:
        header = f"👀 WATCH  Â· {header}"

    if style_watch_alert:
        header = f"\U0001F440 STYLE WATCH  - {header}"

    age_str = f"{age_min}min" if age_min and age_min < 360 else "?"

    if style_watch_alert:
        taste_signals = (result.get("taste_signals") or [])[:6]
        link = item.get("url") or item.get("link") or ""
        lines = [
            "\U0001F440 STYLE WATCH",
            f"score={result.get('taste_watch_score', 0):.0f}",
            f"bucket={result.get('taste_bucket', 'none')}",
            f"price={price:.0f} PLN",
            f"age={age_str}",
            f"signals={', '.join(taste_signals) if taste_signals else '-'}",
            "",
            clean[:120],
        ]
        if link:
            lines.extend(["", "Open link:", str(link)])
        return "\n".join(lines)

    lines = [
        "━" * 32,
        f"{header}  · conf={conf:.1f}/10",
        f"final_score={final_score:.0f}  · quality={'✅' if quality_pass else '⚠️'}",
        "━" * 32,
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

    if result.get("taste_watch_candidate"):
        taste_signals = (result.get("taste_signals") or [])[:5]
        lines.append(f"taste_score={result.get('taste_watch_score', 0):.0f}  "
                     f"bucket={result.get('taste_bucket', 'none')}")
        if taste_signals:
            lines.append(f"taste_signals={', '.join(taste_signals)}")

    # Flags line
    flag_parts = []
    if fast_snipe:     flag_parts.append("⚡ fast_snipe")
    if has_vintage:    flag_parts.append("🕹 vintage")
    if has_rarity:     flag_parts.append("💎 rarity")
    if is_low_effort:  flag_parts.append("⚠️ low_effort")
    if flag_parts:
        lines.append("  ·  ".join(flag_parts))

    # Top 2 matched patterns (no low_effort clutter)
    top_patterns = [p for p in matched_patterns if "low_effort" not in p][:2]
    if top_patterns:
        lines.append(f"🎯  {', '.join(top_patterns)}")

    meta = []
    if brand:          meta.append(f"🏷 {brand}")
    if category:       meta.append(f"📂 {category}")
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
        return self.run_cycle_strict(items, market_prices)

    def run_cycle_legacy(self, items: list[dict], market_prices: dict | None = None) -> list[dict]:
        """Old direct-engine cycle kept for compatibility/debugging."""
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
        _skip_base = {
            "profit": 0, "confidence": 0, "item": item,
            "send_alert": False, "send": False, "engine": None,
            "pattern_score": 0, "matched_patterns": [],
            "brand_detected": None, "estimated_profit": 0,
            "flags": {"rarity": False, "vintage_signal": False, "low_effort": False},
        }
        for trash in _HARD_TRASH:
            if trash in tl:
                return {**_skip_base, "reason": f"hard_filter:{trash}"}

        if is_foreign_title(title):
            return {**_skip_base, "reason": "foreign_language"}

        # ── Task 1: BLOCKED_BRANDS — immediate reject ─────────────────────
        _detected_brand_early = detect_brand(title)
        if _detected_brand_early in BLOCKED_BRANDS:
            return {**_skip_base,
                    "reason": f"blocked_brand:{_detected_brand_early}",
                    "brand_detected": _detected_brand_early}

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

        # ── Task 1: LOW_ROI_BRANDS adjustments ───────────────────────────
        _pattern_score_early = best.get("pattern_score", 0)
        if brand_name in LOW_ROI_BRANDS:
            confidence = max(0.0, confidence - 2.0)
            best["confidence"] = confidence
            # Reject immediately if no pattern compensates
            if _pattern_score_early == 0:
                if DEBUG_ALERTS:
                    print(f"  [QUALITY] skip_reason=low_roi_no_pattern brand={brand_name}")
                return {
                    **_skip_base,
                    "reason": f"low_roi_no_pattern:{brand_name}",
                    "brand_detected": brand_name,
                    "confidence": confidence,
                }

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

        # ── FAKE VINTAGE DETECTION (before final decision) ────────────────
        try:
            _fv_features = extract_item_features(item)
        except Exception:
            _fv_features = {}
        band_detected = best.get("band") or _fv_features.get("band")
        fake_result   = detect_fake_vintage(
            title         = title,
            brand         = brand_name,
            band          = band_detected,
            confidence    = confidence,
            pattern_score = best.get("pattern_score", 0),
            is_grail      = is_grail,
        )

        if fake_result["reject"]:
            # confidence dropped below 5 after penalty → hard reject
            return {
                **_skip_base,
                "reason":          fake_result["reason"],
                "confidence":      fake_result["confidence"],
                "is_fake_vintage": True,
                "band":            band_detected,
            }

        # Apply adjustments from fake vintage check
        if fake_result["is_fake_vintage"] or fake_result["reason"]:
            confidence    = fake_result["confidence"]
            is_grail      = fake_result["is_grail"]
            best["confidence"]    = confidence
            best["is_grail"]      = is_grail
            best["pattern_score"] = fake_result["pattern_score"]
            best["is_fake_vintage"] = fake_result["is_fake_vintage"]
            best["fake_reason"]     = fake_result["reason"]

            # Cap engine tier if required (band tee without auth signal)
            if fake_result["cap_engine"] == "CHAOS":
                best_name     = "CHAOS"
                best["engine"] = "CHAOS"
                confidence    = fake_result["cap_confidence"] or confidence
                best["confidence"] = confidence

        # ── FINAL DECISION RULES (spec: single decision, strict hierarchy) ──
        pattern_score   = best.get("pattern_score", 0)
        matched_patterns= best.get("matched_patterns", [])
        send   = False
        reason = "below_threshold"

        # Production thresholds always; DEBUG_ALERTS only controls logging.
        if is_grail and profit >= 50 and pattern_score >= 5:
            send   = True
            reason = f"grail(score={best.get('grail_score',0)},pattern={pattern_score},profit={profit:.0f})"
        elif is_grail and profit >= 30 and best.get("anomaly_score", 0) >= 2:
            send   = True
            reason = f"grail_anomaly(profit={profit:.0f},anomaly={best.get('anomaly_score',0)})"
        elif is_strong and profit >= 40:
            send   = True
            reason = f"brand_strong(profit={profit:.0f},conf={confidence:.1f})"
        elif best_name == "BRAND" and not is_strong and profit >= 25 and confidence >= 5.5:
            send   = True
            reason = f"brand_deal(profit={profit:.0f},conf={confidence:.1f})"
        elif best_name == "CHAOS" and profit >= 40 and confidence >= 6.0:
            send   = True
            reason = f"chaos_flip(profit={profit:.0f},conf={confidence:.1f})"
        elif best_name == "CHAOS" and pattern_score >= 5 and profit >= 30 and confidence >= 5.5:
            send   = True
            reason = f"chaos_pattern(pattern={pattern_score},profit={profit:.0f})"
        elif confidence > 0:
            reason = f"fallback_candidate(conf={confidence:.1f},profit={profit:.0f},pattern={pattern_score})"

        # Task 6 — Debug log with pattern_score + matched_patterns
        if DEBUG_ALERTS:
            action = "📤 SEND" if send else "⏭  SKIP"
            print(f"  [{best_name}] {action} | "
                  f"conf={confidence:.1f} profit={profit:.0f} "
                  f"pattern_score={pattern_score} "
                  f"grail={is_grail} brand={brand_name or '—'} "
                  f"strong={is_strong} | reason={reason}")
            if matched_patterns:
                print(f"    matched_patterns={matched_patterns}")

        # Task 4 — Sniper flag (age<=10 AND profit>=70)
        _age_val    = best.get("age_min", 999) or 999
        _fast_snipe = bool(_age_val <= 10 and profit >= 70)

        # Mandatory output format (spec)
        return {
            **best,
            "send":             send,
            "send_alert":       send,
            "reason":           reason,
            "engine":           best_name,
            "fast_snipe":       _fast_snipe,
            "quality_pass":     send,
            # Spec output fields
            "brand_detected":   brand_name,
            "estimated_profit": round(profit, 2),
            "pattern_score":    pattern_score,
            "matched_patterns": matched_patterns,
            "flags": {
                "rarity":         bool(best.get("has_rarity") or any("rarity" in p for p in matched_patterns)),
                "vintage_signal": bool(best.get("is_vintage") or any(vs in title.lower() for vs in VINTAGE_SIGNALS)),
                "low_effort":     bool(any("low_effort" in p for p in matched_patterns)),
                "fast_snipe":     _fast_snipe,
                "quality_pass":   send,
            },
        }

    def run_cycle_strict(self, items: list[dict], market_prices: dict | None = None) -> list[dict]:
        """
        Ranking & Selection Layer — post-processing po evaluate_and_decide.

        Pipeline:
          1. Evaluate every item
          2. Build candidate_pool (profit>=30, conf>=5) + fallback pool
          3. Compute final_score per candidate
          4. Dynamic profit threshold (pool>15 → min_profit=50)
          5. Anti-spam: near-duplicate removal
          6. Cluster by brand+category+pattern (max 2/cluster, max 4 if GRAIL)
          7. Sort: GRAIL > BRAND > CHAOS, then final_score DESC
          8. Dynamic TOP-N selection
          9. Debug output
        """
        market_prices = market_prices or {}
        reset_no_market_data_cap_stats()
        total     = len(items)
        processed = 0
        all_scored: list[dict] = []   # wszystkie wyniki z evaluate_and_decide

        # ── Step 1: evaluate every item ─────────────────────────────────
        for item in items:
            try:
                r = self.evaluate_and_decide(item, market_prices)
                processed += 1
                all_scored.append(r)
            except Exception as e:
                processed += 1
                title = str(item.get("title", "?"))[:80] if isinstance(item, dict) else "?"
                print(f"  ❌ ITEM ERROR: {e} | {title}")

        print(f"  📊 Processed: {processed}/{total} | Scored: {len(all_scored)}")

        # ── Step 2: STRICT QUALITY GATE (Task 2) ────────────────────────
        # Reject before ranking if ANY condition fails
        for r in all_scored:
            profile = build_signal_profile(r, self.db)
            apply_signal_profile(r, profile)
            desirability = compute_desirability_score(r.get("item", {}), r)
            apply_desirability_profile(r, desirability)
            manual_taste = compute_manual_taste_profile(r.get("item", {}), r)
            apply_manual_taste_profile(r, manual_taste)
            taste_watch = compute_taste_watch_score(r.get("item", {}), r)
            apply_taste_watch_profile(r, taste_watch)
            enforce_signal_quality(r)

        def _quality_pass(r: dict) -> tuple[bool, str]:
            """Returns (passes, reject_reason). Task 2 spec."""
            eng    = r.get("engine", "CHAOS")
            profit = r.get("profit", 0) or r.get("estimated_profit", 0)
            conf   = r.get("confidence", 0)
            ps     = r.get("pattern_score", 0)
            brand  = r.get("brand") or r.get("brand_detected")
            sq     = float(r.get("signal_quality_score", 0) or 0)
            tier   = r.get("signal_tier", "TIER_C")
            desirability = float(r.get("desirability_score", 0) or 0)
            await_state = r.get("await_state", {}) or {}
            tier_b_allowed = bool(
                tier == "TIER_B"
                and (
                    (eng == "GRAIL" and profit >= 50 and sq >= 60 and desirability >= 45)
                    or (eng == "CHAOS" and profit >= 80 and sq >= 60 and desirability >= 55 and ps >= 3)
                    or (ps >= 5 and profit >= 45 and sq >= 55)
                )
            )

            if r.get("_quality_block_reason"):
                return False, r.get("_quality_block_reason")
            if tier == "TIER_C" or sq < 45:
                return False, f"signal_quality_low({sq:.0f})"
            if profit < 20 and tier == "TIER_S":
                return False, f"tier_s_profit<20({profit:.0f})"
            if profit < 30 and tier == "TIER_A":
                return False, f"tier_a_profit<30({profit:.0f})"
            if profit < 40 and tier == "TIER_B" and not tier_b_allowed:
                return False, f"tier_b_profit<40({profit:.0f})"
            if conf < 5.5 and tier in ("TIER_S", "TIER_A"):
                return False, f"conf<5.5({conf:.1f})"
            if conf < 6.0 and tier == "TIER_B" and not tier_b_allowed:
                return False, f"conf<6.0({conf:.1f})"
            if eng == "CHAOS" and ps == 0 and not brand:
                return False, "chaos_no_pattern_no_brand"
            if eng == "CHAOS":
                is_strong = brand in STRONG_BRANDS if brand else False
                market_ok = (r.get("market_evidence") or {}).get("validated", False)
                if sq < 60:
                    return False, f"chaos_signal<60({sq:.0f})"
                if profit < 50 and not is_strong:
                    return False, f"chaos_profit<50_not_strong({profit:.0f})"
                if not market_ok and not is_strong and tier != "TIER_S":
                    return False, "chaos_market_unvalidated"
            return True, "ok"

        candidate_pool = []
        fallback_pool  = []
        for r in all_scored:
            passes, reject_reason = _quality_pass(r)
            r["quality_pass"]    = passes
            r["quality_reason"]  = reject_reason
            if r.get("send_alert") and passes:
                candidate_pool.append(r)
            elif r.get("confidence", 0) > 0:
                fallback_pool.append(r)
                if DEBUG_ALERTS:
                    reason = r.get("_quality_block_reason") or reject_reason or r.get("reason", "not_sendable")
                    title = str(r.get("item", {}).get("title", ""))[:60]
                    print(f"  [FALLBACK_BLOCK] reason={reason} "
                          f"quality={r.get('signal_quality_score',0):.0f} "
                          f"tier={r.get('tier') or r.get('signal_tier')} title={title}")

        print(f"  📋 Quality gate: {len(candidate_pool)} pass | "
              f"{len(fallback_pool)} fallback | "
              f"{len(all_scored)-len(candidate_pool)-len(fallback_pool)} rejected")

        # Fallback: zero candidates → top-1 relaxed
        def _print_quality_summary(sent_count: int = 0) -> None:
            blocked_by_reason: dict[str, int] = {}
            watch_by_reason: dict[str, int] = {}
            taste_buckets: dict[str, int] = {}
            watch_count = 0
            taste_watch_candidates = 0
            manual_taste_matches = 0
            passed_count = 0
            blocked_count = 0
            passed_quality: list[float] = []
            blocked_quality: list[float] = []
            passed_desirability: list[float] = []
            blocked_desirability: list[float] = []
            for rr in all_scored:
                if rr.get("manual_taste_match"):
                    manual_taste_matches += 1
                    bucket = rr.get("manual_taste_bucket") or rr.get("taste_bucket") or "none"
                    if bucket != "none":
                        taste_buckets[bucket] = taste_buckets.get(bucket, 0) + 1
                if rr.get("taste_watch_candidate"):
                    taste_watch_candidates += 1
                if rr.get("quality_pass") and rr.get("send_alert") and not rr.get("watch_candidate"):
                    passed_count += 1
                    passed_quality.append(float(rr.get("signal_quality_score", 0) or 0))
                    passed_desirability.append(float(rr.get("desirability_score", 0) or 0))
                    continue
                reason = (
                    rr.get("_watch_original_reason")
                    or rr.get("_quality_block_reason")
                    or rr.get("quality_reason")
                    or rr.get("reason")
                    or "not_sendable"
                )
                if rr.get("watch_candidate"):
                    watch_count += 1
                    watch_reason = rr.get("_quality_block_reason") or "watch_only_candidate"
                    watch_by_reason[watch_reason] = watch_by_reason.get(watch_reason, 0) + 1
                    original = rr.get("_watch_original_reason")
                    if original:
                        watch_by_reason[original] = watch_by_reason.get(original, 0) + 1
                    if int(rr.get("pattern_score", 0) or 0) >= 3:
                        watch_by_reason["borderline_pattern"] = watch_by_reason.get("borderline_pattern", 0) + 1
                    if rr.get("desirable_signals"):
                        watch_by_reason["desirable_but_low_quality"] = watch_by_reason.get("desirable_but_low_quality", 0) + 1
                if reason != "ok":
                    blocked_count += 1
                    blocked_quality.append(float(rr.get("signal_quality_score", 0) or 0))
                    blocked_desirability.append(float(rr.get("desirability_score", 0) or 0))
                    blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1
            avg_q_pass = (sum(passed_quality) / len(passed_quality)) if passed_quality else 0
            avg_q_block = (sum(blocked_quality) / len(blocked_quality)) if blocked_quality else 0
            avg_d_pass = (sum(passed_desirability) / len(passed_desirability)) if passed_desirability else 0
            avg_d_block = (sum(blocked_desirability) / len(blocked_desirability)) if blocked_desirability else 0
            print(f"  [QUALITY_SUMMARY] scored={len(all_scored)} passed={passed_count} "
                  f"blocked={blocked_count} watch={watch_count} sent={sent_count} "
                  f"blocked_by_reason={blocked_by_reason} "
                  f"watch_by_reason={watch_by_reason} "
                  f"taste_watch_candidates={taste_watch_candidates} "
                  f"manual_taste_matches={manual_taste_matches} "
                  f"taste_buckets={taste_buckets} "
                  f"avg_quality_passed={avg_q_pass:.1f} avg_quality_blocked={avg_q_block:.1f} "
                  f"avg_desirability_passed={avg_d_pass:.1f} avg_desirability_blocked={avg_d_block:.1f}")

        def _print_style_watch_preview() -> None:
            preview = sorted(
                [rr for rr in all_scored if rr.get("taste_watch_candidate")],
                key=lambda rr: (
                    rr.get("taste_watch_score", 0),
                    rr.get("desirability_score", 0),
                    rr.get("signal_quality_score", 0),
                ),
                reverse=True,
            )[:3]
            if not preview:
                return
            for idx, rr in enumerate(preview, start=1):
                item = rr.get("item") or {}
                print(f"  [STYLE_WATCH_PREVIEW] #{idx} "
                      f"score={rr.get('taste_watch_score',0):.0f} "
                      f"bucket={rr.get('taste_bucket','none')} "
                      f"price={float(item.get('price') or 0):.0f} "
                      f"signals={(rr.get('taste_signals') or [])[:5]} "
                      f"title={str(item.get('title') or '')[:60]}")

        if not candidate_pool and not (
            (WATCH_ALERTS_ENABLED and any(r.get("watch_candidate") for r in fallback_pool))
            or (TASTE_WATCH_SEND_ENABLED and any(r.get("taste_watch_candidate") for r in fallback_pool))
        ):
            held = sum(1 for r in fallback_pool if (r.get("await_state") or {}).get("hold"))
            print(f"  [AWAIT] no sendable candidates | held={held} fallback={len(fallback_pool)}")
            _print_quality_summary(sent_count=0)
            _print_style_watch_preview()
            print_no_market_data_cap_summary()
            self.db.save(force=True)
            return []


        # ── Step 3: FINAL_SCORE with multipliers (Task 3) ───────────────
        def _final_score(r: dict) -> float:
            profit  = r.get("profit", 0) or r.get("estimated_profit", 0)
            pattern = r.get("pattern_score", 0)
            conf    = r.get("confidence", 0)
            eng     = r.get("engine", "CHAOS")
            is_le   = any("low_effort" in p for p in r.get("matched_patterns", []))

            base = profit * 1.0 + pattern * 8 + conf * 3

            # Task 3 — multipliers
            if pattern == 0:
                base *= 0.7                    # no pattern penalty
            if is_le:
                base *= 0.5                    # low effort heavy penalty
            if eng == "GRAIL":
                base *= 1.25                   # GRAIL priority boost
            if pattern >= 4:
                base *= 1.15                   # high pattern reward

            return round(base, 2)

        def _final_score_v2(r: dict) -> float:
            profit = r.get("profit", 0) or r.get("estimated_profit", 0)
            conf = r.get("confidence", 0)
            signal = r.get("signal_quality_score", 0)
            rarity = r.get("rarity_score", r.get("grail_score", 0) * 10)
            desirability = r.get("desirability_score", 0)
            tier = r.get("signal_tier", r.get("tier", "TIER_C"))
            tier_bonus = SIGNAL_TIER_BOOSTS.get(tier, -40)
            score = (
                profit * 0.25
                + (conf * 10) * 0.15
                + signal * 0.30
                + rarity * 0.15
                + desirability * 0.15
                + tier_bonus
            )
            r["tier_bonus"] = tier_bonus
            r["anomaly_bonus"] = 0
            return round(score, 2)

        for r in candidate_pool:
            # Task 4 — SNIPER MODE: age <=10 AND profit >= 70
            age         = r.get("age_min", 999)
            profit_val  = r.get("profit", 0)
            fast_snipe  = (age <= 10 and profit_val >= 70)
            r["fast_snipe"] = fast_snipe

            score = _final_score_v2(r)
            if fast_snipe:
                score *= 1.3       # Task 4 multiplier
            r["final_score"] = round(score, 2)

            if DEBUG_ALERTS:
                title = str(r.get("item", {}).get("title", ""))[:60]
                print(f"  [SIGNAL_PASS] engine={r.get('engine','?')} "
                      f"tier={r.get('tier') or r.get('signal_tier')} "
                      f"quality={r.get('signal_quality_score',0):.0f} "
                      f"desirability={r.get('desirability_score',0):.0f} "
                      f"profit={profit_val:.0f} conf={r.get('confidence',0):.1f} "
                      f"final={r.get('final_score',0):.0f} title={title}")

            if fast_snipe and DEBUG_ALERTS:
                print(f"  ⚡ SNIPER: age={age}m profit={profit_val:.0f} "
                      f"final_score={r['final_score']:.0f} | "
                      f"{r.get('item',{}).get('title','?')[:40]}")

        # ── Step 4: dynamic profit threshold ────────────────────────────
        min_profit = 50 if len(candidate_pool) > 15 else 40
        candidate_pool = [r for r in candidate_pool if r.get("profit", 0) >= min_profit]
        if not candidate_pool and not (
            (WATCH_ALERTS_ENABLED and any(r.get("watch_candidate") for r in fallback_pool))
            or (TASTE_WATCH_SEND_ENABLED and any(r.get("taste_watch_candidate") for r in fallback_pool))
        ):
            preview = sorted(
                fallback_pool,
                key=lambda rr: (
                    rr.get("final_score", 0),
                    rr.get("signal_quality_score", 0),
                    rr.get("desirability_score", 0),
                ),
                reverse=True,
            )[:1]
            if preview:
                item = preview[0].get("item") or {}
                print(f"  [ENGINE_TOP1_WATCH_ONLY] reason=no_sendable_candidates "
                      f"title={str(item.get('title') or '')[:60]} "
                      f"score={preview[0].get('final_score', 0)}")
            _print_quality_summary(sent_count=0)
            _print_style_watch_preview()
            print_no_market_data_cap_summary()
            self.db.save(force=True)
            return []
        print(f"  🎚 min_profit={min_profit} → {len(candidate_pool)} candidates")

        # ── Step 5: anti-spam / near-duplicate removal ───────────────────
        def _title_similarity(a: str, b: str) -> float:
            ta = set(a.lower().split())
            tb = set(b.lower().split())
            if not ta or not tb:
                return 0.0
            return len(ta & tb) / max(len(ta), len(tb))

        deduped: list[dict] = []
        for r in candidate_pool:
            r_title = str(r.get("item", {}).get("title", ""))
            r_price = float(r.get("item", {}).get("price", 0) or 0)
            r_brand = r.get("brand") or ""
            is_dup  = False
            for kept in deduped:
                k_title = str(kept.get("item", {}).get("title", ""))
                k_price = float(kept.get("item", {}).get("price", 0) or 0)
                k_brand = kept.get("brand") or ""
                sim         = _title_similarity(r_title, k_title)
                price_close = k_price > 0 and abs(r_price - k_price) / k_price <= 0.10
                same_brand  = r_brand and r_brand == k_brand
                if sim >= 0.80 and price_close and same_brand:
                    is_dup = True
                    break
            if not is_dup:
                deduped.append(r)

        removed_dups = len(candidate_pool) - len(deduped)
        if removed_dups > 0:
            print(f"  🧹 Anti-spam removed {removed_dups} near-duplicates")
        candidate_pool = deduped

        # ── Step 6: clustering (Task 5 — max 2 per cluster) ─────────────
        def _cluster_key(r: dict) -> str:
            brand    = (r.get("brand") or "unknown").lower().replace(" ", "_")
            category = (r.get("category") or "other").lower()
            patterns = r.get("matched_patterns", [])
            main_pat = patterns[0].split("(")[0] if patterns else "generic"
            key      = f"{brand}__{category}__{main_pat}"
            r["cluster_key"] = key
            return key

        cluster_counts: dict[str, int] = {}
        clustered: list[dict] = []

        for r in candidate_pool:
            _cluster_key(r)
        cluster_total_counts: dict[str, int] = {}
        for r in candidate_pool:
            ck = r.get("cluster_key", "unknown__other__generic")
            cluster_total_counts[ck] = cluster_total_counts.get(ck, 0) + 1
        for r in candidate_pool:
            ck = r.get("cluster_key", "unknown__other__generic")
            penalty = cluster_total_counts.get(ck, 0) * 8 if cluster_total_counts.get(ck, 0) > 2 else 0
            r["cluster_penalty"] = penalty
            r["final_score"] = round(r.get("final_score", 0) - penalty, 2)

        diversity_seen: dict[str, int] = {}
        for r in sorted(candidate_pool, key=lambda x: -x.get("final_score", 0)):
            brand_key = (r.get("brand") or r.get("brand_detected") or "").lower()
            penalty = 0
            if brand_key:
                if diversity_seen.get(brand_key, 0) >= 2:
                    penalty = 25
                diversity_seen[brand_key] = diversity_seen.get(brand_key, 0) + 1
            r["ranking_penalty"] = penalty
            r["diversity_penalty"] = penalty
            if penalty:
                r["final_score"] = round(r.get("final_score", 0) - penalty, 2)

        candidate_pool.sort(key=lambda r: (
            TIER_PRIORITY.get(r.get("tier") or r.get("signal_tier"), 0),
            ENGINE_PRIORITY.get(r.get("engine"), 0),
            r.get("final_score", 0),
        ), reverse=True)

        for r in candidate_pool:
            ck      = _cluster_key(r)
            # Task 5 spec: max 2 per cluster (grails also capped at 2)
            max_per = 2
            if cluster_counts.get(ck, 0) < max_per:
                cluster_counts[ck] = cluster_counts.get(ck, 0) + 1
                clustered.append(r)

        print(f"  🔗 After clustering: {len(clustered)} (from {len(candidate_pool)})")

        # ── Step 7: sort — GRAIL > BRAND > CHAOS, then final_score DESC ─
        clustered.sort(key=lambda r: (
            TIER_PRIORITY.get(r.get("tier") or r.get("signal_tier"), 0),
            ENGINE_PRIORITY.get(r.get("engine"), 0),
            r.get("final_score", 0),
        ), reverse=True)

        # ── Step 8: TOP-5 HARD LIMIT (Task 6) ───────────────────────────
        # NEVER exceed 5 items per cycle
        MAX_OUTPUT = 5
        selected: list[dict] = []
        top_brand_counts: dict[str, int] = {}
        for r in clustered:
            brand_key = (r.get("brand") or r.get("brand_detected") or "").lower()
            if brand_key and top_brand_counts.get(brand_key, 0) >= 2:
                r["ranking_penalty"] = max(r.get("ranking_penalty", 0), 25)
                r["diversity_penalty"] = r["ranking_penalty"]
                continue
            selected.append(r)
            if brand_key:
                top_brand_counts[brand_key] = top_brand_counts.get(brand_key, 0) + 1
            if len(selected) >= MAX_OUTPUT:
                break
        print(f"  🎯 TOP-{MAX_OUTPUT} selection: {len(selected)} items")

        # ── Step 9: assign ranking_position + session dedup ─────────────
        added_watch_ids: set[str] = set()
        if TASTE_WATCH_SEND_ENABLED:
            style_hard_reasons = {
                "fake_or_fast_fashion",
                "small_carhartt_pants",
                "carhartt_pants_small_size_skip",
                "generic_conditional_brand_shirt_block",
                "low_quality_aesthetic_hard_block",
                "low_quality_aesthetic_blocked",
                "non_clothing_style_watch_block",
            }

            def _style_watch_sendable(r: dict) -> bool:
                item = r.get("item") or {}
                text_l = _item_search_text(item, r)
                brand_l = str(r.get("brand") or r.get("brand_detected") or item.get("brand") or "").lower()
                category = r.get("category") or detect_category(str(item.get("title") or "")) or ""
                reason = r.get("_quality_block_reason") or r.get("_watch_original_reason") or ""
                if not r.get("taste_watch_candidate"):
                    return False
                if reason in style_hard_reasons:
                    return False
                if float(r.get("taste_watch_score", 0) or 0) < 60:
                    return False
                if not _has_real_taste_signal(r.get("taste_signals") or []):
                    return False
                if not _taste_item_type(text_l, category):
                    return False
                if _taste_fast_fashion(text_l, brand_l):
                    return False
                if r.get("carhartt_size_skip") or r.get("generic_conditional_brand_shirt") or r.get("is_low_quality_aesthetic"):
                    return False
                return True

            taste_pool = [r for r in fallback_pool if _style_watch_sendable(r)]
            taste_pool.sort(key=lambda r: (
                r.get("taste_watch_score", 0),
                -float((r.get("item") or {}).get("price") or 0),
                -int(r.get("age_min", item_age_minutes(r.get("item") or {})) or 999),
                len(r.get("taste_signals") or []),
            ), reverse=True)
            added_taste = taste_pool[:max(TASTE_WATCH_MAX_PER_CYCLE, 0)]
            for taste_rank, r in enumerate(added_taste, start=1):
                r["final_score"] = _final_score_v2(r)
                r["send_alert"] = True
                r["send"] = True
                r["style_watch_sent"] = True
                key = str((r.get("item") or {}).get("id") or (r.get("item") or {}).get("url") or "")
                if key:
                    added_watch_ids.add(key)
                print(f"  [STYLE_WATCH_SEND] rank={taste_rank} "
                      f"score={r.get('taste_watch_score',0):.0f} "
                      f"bucket={r.get('taste_bucket','none')} "
                      f"price={float((r.get('item') or {}).get('price') or 0):.0f} "
                      f"age={r.get('age_min', item_age_minutes(r.get('item') or {}))} "
                      f"signals={(r.get('taste_signals') or [])[:5]} "
                      f"title={str((r.get('item') or {}).get('title') or '')[:60]}")
            selected.extend(added_taste)
        else:
            for r in fallback_pool:
                if r.get("taste_watch_candidate") or r.get("style_watch_sent"):
                    r["send_alert"] = False
                    r["send"] = False
                    r["style_watch_sent"] = False
                    print(f"  [TASTE_WATCH_SEND_DISABLED] title={str((r.get('item') or {}).get('title') or '')[:60]} "
                          f"reason=watch_not_alert")

        if WATCH_ALERTS_ENABLED:
            watch_pool = []
            for r in fallback_pool:
                key = str((r.get("item") or {}).get("id") or (r.get("item") or {}).get("url") or "")
                if r.get("watch_candidate") and key not in added_watch_ids:
                    watch_pool.append(r)
            for r in watch_pool:
                r["final_score"] = _final_score_v2(r)
            watch_pool.sort(key=lambda r: (
                TIER_PRIORITY.get(r.get("tier") or r.get("signal_tier"), 0),
                ENGINE_PRIORITY.get(r.get("engine"), 0),
                r.get("final_score", 0),
            ), reverse=True)
            added_watch = watch_pool[:max(WATCH_MAX_PER_CYCLE, 0)]
            for r in added_watch:
                r["send_alert"] = False
                r["send"] = False
                print(f"  [WATCH_SEND_BLOCK] title={str((r.get('item') or {}).get('title') or '')[:60]} "
                      f"source=ENGINE reason=watch_not_alert")
            if added_watch:
                print(f"  [WATCH_SEND] enabled=1 watch_only={len(added_watch)} max={WATCH_MAX_PER_CYCLE}")

        brand_counts: dict[str, int] = {}
        sent_ids: set[str] = set()
        final: list[dict]  = []

        for pos, r in enumerate(selected, start=1):
            item_id  = str(r.get("item", {}).get("id", ""))
            is_grail = r.get("is_grail", False)
            if r.get("watch_candidate") and not r.get("send_alert"):
                print(f"  [WATCH_SEND_BLOCK] title={str((r.get('item') or {}).get('title') or '')[:60]} "
                      f"source=ENGINE_FINAL reason=watch_not_alert")
                r["send"] = False
                r["send_alert"] = False
                continue

            # Session-level dedup
            if item_id and item_id in sent_ids:
                continue
            if item_id and item_id in self._alerted_ids and not is_grail:
                continue

            # Brand cap (max 2 per brand per cycle, grails exempt)
            brand = r.get("brand") or ""
            if brand and not is_grail:
                if brand_counts.get(brand, 0) >= 2:
                    continue
                brand_counts[brand] = brand_counts.get(brand, 0) + 1

            # Ensure all Task 7 output fields are present
            r["ranking_position"] = pos
            r["send"]             = r["send_alert"] = True
            r.setdefault("final_score",    0.0)
            r.setdefault("pattern_score",  0)
            r.setdefault("matched_patterns", [])
            r.setdefault("brand_detected", r.get("brand"))
            r.setdefault("estimated_profit", r.get("profit", 0))
            r.setdefault("cluster_key",    "unknown__other__generic")
            r.setdefault("quality_pass",   True)
            r.setdefault("fast_snipe",     False)
            r.setdefault("flags", {
                "rarity":         bool(r.get("has_rarity")),
                "vintage_signal": bool(r.get("is_vintage") or any(
                    vs in str(r.get("item", {}).get("title", "")).lower()
                    for vs in VINTAGE_SIGNALS)),
                "low_effort":     any("low_effort" in p
                                      for p in r.get("matched_patterns", [])),
                "fast_snipe":     r.get("fast_snipe", False),
                "quality_pass":   r.get("quality_pass", True),
            })

            if item_id:
                sent_ids.add(item_id)
                self._alerted_ids.add(item_id)
            final.append(r)

        # Task 7 — mandatory debug output
        if DEBUG_ALERTS:
            print(f"\n  {'═'*60}")
            print(f"  RANKING SUMMARY — sending {len(final)}/{len(selected)} items")
            print(f"  {'═'*60}")
            for r in final:
                title    = str(r.get("item", {}).get("title", ""))[:38]
                flags    = r.get("flags", {})
                snipe_tag = " ⚡SNIPE" if flags.get("fast_snipe") else ""
                le_tag    = " ⚠️LE" if flags.get("low_effort") else ""
                print(f"  #{r['ranking_position']:2d} [{r.get('engine','?'):5s}]{snipe_tag}{le_tag} "
                      f"final={r.get('final_score',0):.0f} "
                      f"profit={r.get('profit',0):.0f} "
                      f"conf={r.get('confidence',0):.1f} "
                      f"pattern={r.get('pattern_score',0)} "
                      f"brand={r.get('brand_detected') or '—'} "
                      f"cluster={r.get('cluster_key','?')[:25]}")
                print(f"         {title}")
                await_state = r.get("await_state", {}) or {}
                market_ev = r.get("market_evidence", {}) or {}
                print(f"         [SIGNAL] quality={r.get('signal_quality_score',0):.0f} "
                      f"tier={r.get('signal_tier','?')} await={await_state.get('hold', False)} "
                      f"auth={r.get('auth_state','?')} market={r.get('market_state','?')} "
                      f"diversity_penalty={r.get('diversity_penalty',0)} "
                      f"cluster_penalty={r.get('cluster_penalty',0)}")
                print(f"         [RANK] final={r.get('final_score',0):.0f} "
                      f"tier_bonus={r.get('tier_bonus',0)} "
                      f"anomaly_bonus={r.get('anomaly_bonus',0)} "
                      f"market_count={market_ev.get('count',0)}")
                print(f"         [RANK] #{r.get('ranking_position')} "
                      f"engine={r.get('engine','?')} tier={r.get('tier') or r.get('signal_tier')} "
                      f"final={r.get('final_score',0):.0f} "
                      f"quality={r.get('signal_quality_score',0):.0f} "
                      f"desirability={r.get('desirability_score',0):.0f} "
                      f"brand={r.get('brand_detected') or r.get('brand') or '-'} "
                      f"cluster={r.get('cluster_key','?')[:25]} title={title}")
                if r.get("matched_patterns"):
                    print(f"         patterns={r['matched_patterns'][:2]}")
            print(f"  {'═'*60}\n")

        if len(self._alerted_ids) > 10_000:
            self._alerted_ids = set(list(self._alerted_ids)[-5_000:])

        _print_quality_summary(sent_count=len(final))
        _print_style_watch_preview()
        print_no_market_data_cap_summary()

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
        est   = r.get("estimated_value", 0) or r.get("median_price", 0) or price
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


# Re-export extract_item_features so bot.py can import it directly
__all__ = [
    "Engine", "MarketDB", "ChaosEngine", "BrandEngine", "GrailEngine",
    "format_alert", "extract_item_features",
    "detect_brand", "detect_category", "is_foreign_title",
]
