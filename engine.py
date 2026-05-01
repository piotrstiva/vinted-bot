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

        feat = {
            "brand":      brand,
            "has_brand":  brand is not None,
            "is_vintage": is_vintage,
            "category":   category,
            "keywords":   tags,
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
    # Premium / hype
    "arc'teryx", "arcteryx", "stone island", "cp company", "patagonia",
    "supreme", "palace", "stussy", "bape", "fear of god", "essentials",
    "corteiz", "crtz", "broken planet", "denim tears", "represent",
    # Sportswear
    "nike", "adidas", "puma", "reebok", "new balance", "asics", "salomon",
    "vans", "converse", "timberland",
    # Workwear / denim
    "carhartt", "carhartt wip", "dickies", "wrangler", "levi's", "levis",
    "levi", "lee ", "ben davis",
    # Outdoor
    "the north face", "tnf", "columbia", "helly hansen",
    # Classic
    "ralph lauren", "lacoste", "fred perry", "champion",
    "tommy hilfiger", "calvin klein",
    # Football
    "umbro", "kappa", "lotto", "diadora", "hummel", "admiral",
    "le coq sportif",
    # Vintage basics
    "screen stars", "hanes", "fruit of the loom", "gildan", "delta",
    "brockum", "liquid blue", "nutmeg", "anvil", "tultex",
    "salem sportswear", "russell athletic", "starter",
    # Luxury
    "gucci", "louis vuitton", "prada", "hermes", "balenciaga",
    "versace", "burberry", "fendi", "dior", "off-white",
    "stone island", "moncler", "canada goose",
], key=len, reverse=True)

LUXURY_BRANDS = {
    "gucci", "louis vuitton", "prada", "hermes", "balenciaga",
    "versace", "burberry", "fendi", "dior", "off-white",
    "moncler", "canada goose",
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
    t = title.lower()
    for brand in _ALL_BRANDS:
        if brand in t:
            return brand.strip()
    return None


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
        # Part 1 — single source of truth
        features = extract_item_features(item)
        title    = item.get("title", "") or ""
        price    = float(item.get("price") or 0)

        base = {"engine": "CHAOS", "item": item, "send_alert": False,
                "tier": "CHAOS", "profit": 0, "confidence": 0,
                "anomaly_score": 0, "deal_tag": "NO_DATA"}

        # Hard filters (tylko prawdziwe śmieci)
        if is_foreign_title(title):
            return {**base, "_skip_reason": "foreign_language"}
        if kw(title, _CHAOS_TRASH):
            return {**base, "_skip_reason": "trash"}
        if price < 15 or price > 200:
            return {**base, "_skip_reason": "price_out_of_range"}

        age = item_age_minutes(item)
        if age > MAX_ITEM_AGE_MINUTES * 6:
            return {**base, "_skip_reason": "stale"}

        brand = features["brand"]
        cat   = features["category"]

        # ── Wycena rynkowa ──────────────────────────────
        # Priorytet: heurystyczna cena brandu > DB > price * 1.6
        market_price    = None
        brand_heuristic = None
        if brand and cat:
            bp = _HEURISTIC_PRICES.get(brand)
            if bp:
                brand_heuristic = bp.get(cat, bp["default"])
                market_price    = brand_heuristic
        if not market_price and cat:
            # Szukaj w DB (chaos_cat lub brand_cat)
            db_key  = f"{brand}_{cat}" if brand else f"chaos_{cat}"
            db_data = self.db.lookup(db_key)
            if db_data and db_data.get("count", 0) >= 3:
                market_price = db_data.get("median")
        if not market_price:
            # Fallback: 1.6x ceny (zawsze dostępne)
            market_price = price * 1.6

        estimated_value = market_price
        profit          = estimated_value - price

        # ── Part 5 — Confidence scoring ─────────────────
        # Part 1 FIX: brak brandu = soft penalty, NIE blok
        confidence = 4.0  # baseline
        if features["has_brand"]:
            confidence += 1.5
        else:
            confidence -= 1.5   # Part 1: soft penalty zamiast hard block

        if features["is_vintage"]:          confidence += 1.5
        if kw(title, _CHAOS_STYLE_KW):      confidence += 1.0
        if kw(title, _CHAOS_VINTAGE_KW):    confidence += 2.0
        if cat == "jacket":                 confidence += 1.0
        elif cat == "hoodie":               confidence += 0.5
        elif cat == "sneakers":             confidence -= 1.5
        elif cat == "tshirt" and not features["is_vintage"]:
            confidence -= 0.5
        if 20 <= price <= 50:               confidence += 0.5
        confidence += freshness_boost(age) * 0.3

        # ── Part 3 — Undervaluation detection ───────────
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

        # ── Filtr damskich koszulek sportowych ──────────
        _WOMENS_KW  = ["damska", "damski", "women", "woman", "damen",
                       "femme", "donna", "feminino"]
        _SPORT_ONLY = {"lotto", "kappa", "diadora", "hummel", "admiral",
                       "le coq sportif", "erima", "joma"}
        if kw(title, _WOMENS_KW) and brand in _SPORT_ONLY:
            return {**base, "_skip_reason": "womens_sport_brand"}

        _SPORT_ACT = ["rowerow", "kolarski", "cycling", "fitness",
                      "siłowni", "silowni", "running", "treningow"]
        if kw(title, _SPORT_ACT) and cat == "tshirt":
            return {**base, "_skip_reason": "sport_activity_tshirt"}

        # ── Part 6 — Soft filter (tylko oczywiste śmieci) ──
        if profit < 10 and anomaly_score == 0:
            return {**base, "_skip_reason": "low_profit_no_anomaly",
                    "confidence": confidence, "profit": round(profit, 2)}

        # ── Part 4 — Relaxed send rule ───────────────────
        if DEBUG_ALERTS:
            # Part 5 — debug mode: obniż próg żeby zobaczyć co przechodzi
            send = profit >= 15
        else:
            send = (
                (profit >= 25 and confidence >= 5.5)
                or (profit >= 15 and anomaly_score >= 2)
            )

        # ── Part 2 — DB learning: zawsze, brand NIE wymagany ──
        if cat:
            chaos_key = f"chaos_{cat}"
            self.db.add_sample(chaos_key, price)
        if brand and cat:
            self.db.add_sample(f"{brand}_{cat}", price)
        elif cat:
            # Part 2 FIX: category_unknown dla itemów bez brandu
            self.db.add_sample(f"{cat}_unknown", price)
        if features["is_vintage"] and cat:
            self.db.add_sample(f"vintage_{cat}", price)

        # Deal tag z DB
        deal_tag = "NO_DATA"
        if cat:
            db_key   = f"{brand}_{cat}" if brand else f"chaos_{cat}"
            deal_tag = self.db.get_deal_tag(db_key, price)

        # Part 5 — zawsze loguj przy DEBUG_ALERTS
        if DEBUG_ALERTS:
            action = "📤 ALERT" if send else "⏭  SKIP"
            print(f"  {action}: conf={confidence:.1f} profit={profit:.0f} "
                  f"anomaly={anomaly_score} brand={brand or '—'} | {title[:45]}")

        return {
            **base,
            "send_alert":      send,
            "profit":          round(profit, 2),
            "estimated_value": round(estimated_value, 2),
            "market_price":    round(market_price, 2) if market_price else None,
            "confidence":      confidence,
            "anomaly_score":   anomaly_score,
            "brand":           brand,
            "category":        cat,
            "age_min":         age,
            "deal_tag":        deal_tag,
            "_skip_reason":    None if send else "below_threshold",
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🟣 BRAND ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Heurystyczne ceny rynkowe per brand+category (gdy brak DB)
_HEURISTIC_PRICES: dict[str, dict[str, float]] = {
    "arc'teryx":    {"jacket": 700, "hoodie": 450, "sneakers": 500, "default": 400},
    "arcteryx":     {"jacket": 700, "hoodie": 450, "default": 400},
    "stone island": {"jacket": 800, "hoodie": 500, "default": 450},
    "cp company":   {"jacket": 600, "hoodie": 400, "default": 350},
    "patagonia":    {"jacket": 500, "hoodie": 350, "default": 280},
    "supreme":      {"jacket": 600, "hoodie": 350, "tshirt": 280, "default": 300},
    "palace":       {"jacket": 500, "hoodie": 300, "tshirt": 250, "default": 250},
    "stussy":       {"jacket": 350, "hoodie": 250, "tshirt": 180, "default": 200},
    "corteiz":      {"jacket": 500, "hoodie": 300, "tshirt": 200, "default": 250},
    "broken planet":{"hoodie": 400, "tshirt": 250, "default": 300},
    "carhartt":     {"jacket": 350, "hoodie": 220, "tshirt": 130, "default": 180},
    "carhartt wip": {"jacket": 400, "hoodie": 280, "default": 220},
    "dickies":      {"jacket": 200, "cargo": 150, "default": 120},
    "salomon":      {"sneakers": 380, "jacket": 450, "default": 280},
    "new balance":  {"sneakers": 220, "jacket": 220, "default": 160},
    "asics":        {"sneakers": 200, "default": 150},
    "nike":         {"sneakers": 250, "jacket": 220, "hoodie": 180, "tshirt": 120, "default": 160},
    "adidas":       {"sneakers": 220, "jacket": 200, "hoodie": 160, "tshirt": 110, "default": 140},
    "levi's":       {"jeans": 160, "jacket": 220, "default": 140},
    "levis":        {"jeans": 160, "jacket": 220, "default": 140},
    "levi":         {"jeans": 150, "jacket": 200, "default": 130},
    "wrangler":     {"jeans": 130, "jacket": 180, "default": 120},
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

        # Part 5 — używaj features["has_brand"] zamiast if brand
        if not features["has_brand"]:
            return {**base, "_skip_reason": "no_brand"}
        if not category:
            return {**base, "_skip_reason": "no_category"}

        age = item_age_minutes(item)
        if age > MAX_ITEM_AGE_MINUTES * 4:
            return {**base, "_skip_reason": "stale"}

        median_price = self._find_median(brand, category, market_prices)
        profit       = (median_price - price) if median_price else 0.0

        # Part 5 — scoring przez features
        conf = 3.0   # has_brand +3
        if category:
            conf += 2.0   # category +2

        if median_price and median_price > 0:
            ratio = price / median_price
            if ratio < 0.50:   conf += 4.0
            elif ratio < 0.60: conf += 3.0
            elif ratio < 0.70: conf += 2.0
            elif ratio < 0.80: conf += 1.0
            else:              conf -= 1.0

        conf += freshness_boost(age) * 0.4

        if brand in LUXURY_BRANDS and price < 100:
            conf -= 3.0

        # Part 3 — Undervaluation detection
        anomaly_score = 0
        if median_price and median_price > 0:
            if price < median_price * 0.70:
                anomaly_score = 2
                conf         += 1.5
            elif price < median_price * 0.85:
                anomaly_score = 1
                conf         += 0.5

        conf = round(min(max(conf, 0.0), 10.0), 2)

        # Part 4 — Relaxed send rule
        if DEBUG_ALERTS:
            send = profit >= 15
        else:
            send = (
                (profit >= 25 and conf >= 5.5)
                or (profit >= 15 and anomaly_score >= 2)
            )

        # Part 2 — DB learning zawsze
        if category:
            self.db.add_sample(f"{brand}_{category}", price)
            self.db.add_sample(f"chaos_{category}", price)   # cross-learn

        # Deal tag z DB
        db_key   = f"{brand}_{category}" if category else brand
        deal_tag = self.db.get_deal_tag(db_key, price)

        if DEBUG_ALERTS:
            action = "📤 ALERT" if send else "⏭  SKIP"
            print(f"  {action}: conf={conf:.1f} profit={profit:.0f} "
                  f"anomaly={anomaly_score} brand={brand} | {title[:45]}")

        return {
            **base,
            "send_alert":      send,
            "profit":          round(profit, 2),
            "median_price":    round(median_price, 2) if median_price else None,
            "estimated_value": round(median_price, 2) if median_price else 0,
            "confidence":      conf,
            "anomaly_score":   anomaly_score,
            "age_min":         age,
            "deal_tag":        deal_tag,
            "_skip_reason":    None if send else "below_threshold",
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
        # Part 1 — single source of truth
        features = extract_item_features(item)
        title    = item.get("title", "")
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

        # Grail scoring
        score    = 0
        kw_hits  = sum(1 for k in _GRAIL_KEYWORDS if k in t)
        if kw_hits >= 1:   score += 2
        if kw_hits >= 2:   score += 1

        if kw(title, _GRAIL_BRANDS):   score += 2

        # Extra signals
        if "tour"                       in t: score += 1
        if "single stitch"              in t: score += 1
        if "band" in t or "movie" in t      : score += 1
        if "bootleg"                    in t: score += 1

        # Part 1 — używaj features["is_vintage"]
        if features["is_vintage"]:   score += 1

        estimated = self._estimate_value(title, price, score)
        profit    = estimated - price

        # Part 3 — Undervaluation detection
        anomaly_score = 0
        if estimated > 0 and price < estimated * 0.70:
            anomaly_score = 2
            score        += 2   # underpriced → extra grail points
        elif estimated > 0 and price < estimated * 0.85:
            anomaly_score = 1
            score        += 1

        is_grail = score >= 3
        conf     = float(score) * 1.2 + freshness_boost(age) * 0.4
        conf     = round(min(max(conf, 0.0), 10.0), 2)

        # Part 4 — Relaxed send rule: grail OR undervalued
        if DEBUG_ALERTS:
            send = profit >= 10 and is_grail and not is_foreign_title(title)
        else:
            send = (
                (is_grail and profit >= 10)
                or (profit >= 15 and anomaly_score >= 2)
            )

        # Part 2 — DB learning: zawsze, bez brandu też
        cat = features["category"]
        if cat:
            self.db.add_sample(f"grail_{cat}", price)
            self.db.add_sample(f"chaos_{cat}", price)      # cross-learn
        if features["has_brand"] and cat:
            self.db.add_sample(f"{features['brand']}_{cat}", price)
        elif cat:
            self.db.add_sample(f"{cat}_unknown", price)   # Part 2 FIX

        if DEBUG_ALERTS:
            action = "📤 ALERT" if send else "⏭  SKIP"
            print(f"  {action}: conf={conf:.1f} profit={profit:.0f} "
                  f"anomaly={anomaly_score} grail={is_grail} | {title[:45]}")

        return {
            **base,
            "send_alert":      send,
            "is_grail":        is_grail,
            "grail_score":     score,
            "profit":          round(profit, 2),
            "estimated_value": round(estimated, 2),
            "confidence":      conf,
            "anomaly_score":   anomaly_score,
            "brand":           features["brand"],
            "category":        cat,
            "age_min":         age,
            "_skip_reason":    None if send else ("not_grail" if not is_grail else "low_profit"),
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📨 FORMAT ALERT — unified
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
        candidates = [
            ("GRAIL", g_result),
            ("BRAND", b_result),
            ("CHAOS", c_result),
        ]

        # Failsafe (Requirement 10): żaden silnik nie zwrócił nic
        if all(r.get("confidence", 0) == 0 for _, r in candidates):
            return {
                "send": False, "engine": None,
                "reason": "no_valid_score",
                "profit": 0, "confidence": 0,
                "item": item, "send_alert": False,
            }

        # Wybierz najlepszy wynik (max confidence, GRAIL ma priorytet)
        best_name, best = max(
            candidates,
            key=lambda x: (
                x[1].get("confidence", 0) +
                (3.0 if x[0] == "GRAIL" and x[1].get("is_grail") else 0)
            )
        )
        best = dict(best)
        best["engine"] = best_name

        profit     = best.get("profit", 0)
        confidence = best.get("confidence", 0)
        is_grail   = best.get("is_grail", False)
        brand_name = best.get("brand")

        # ── Requirement 5: FINAL DECISION RULES ───────────
        send   = False
        reason = "below_threshold"

        # CASE 2: grail override
        if is_grail and profit >= 10:
            send   = True
            reason = f"grail(score={best.get('grail_score',0)})"

        # CASE 1: standard flip
        elif profit >= 30 and confidence >= 6.0:
            send   = True
            reason = f"standard_flip(profit={profit:.0f},conf={confidence:.1f})"

        # CASE 3: strong brand deal
        elif best_name == "BRAND" and profit >= 25 and confidence >= 5.0:
            send   = True
            reason = f"brand_deal(profit={profit:.0f})"

        # Requirement 6: logging
        if DEBUG_ALERTS:
            action = "📤 SEND" if send else "⏭  SKIP"
            print(f"  [{best_name}] {action} | "
                  f"conf={confidence:.1f} profit={profit:.0f} "
                  f"grail={is_grail} brand={brand_name or '—'} | "
                  f"reason={reason} | {title[:40]}")

        return {
            **best,
            "send":       send,
            "send_alert": send,
            "reason":     reason,
            "engine":     best_name,
        }

    def run_cycle_strict(self, items: list[dict], market_prices: dict | None = None) -> list[dict]:
        """
        Requirement 1+6+8: Strict pipeline — każdy item przez evaluate_and_decide.
        Zwraca max 10 wyników posortowanych po profit DESC.
        """
        market_prices = market_prices or {}
        total = len(items)
        processed = 0
        results = []

        for item in items:
            try:
                r = self.evaluate_and_decide(item, market_prices)
                processed += 1
                if r.get("send"):
                    results.append(r)
            except Exception as e:
                processed += 1
                title = str(item.get("title", "?"))[:80] if isinstance(item, dict) else "?"
                print(f"  ❌ ITEM ERROR: {e} | {title}")

        # Requirement 9: sort by score DESC, limit 10
        results.sort(key=lambda r: -(r.get("profit", 0) + r.get("confidence", 0)))

        # Dedup by item_id + brand cap
        brand_counts: dict[str, int] = {}
        final = []
        for r in results:
            item_id  = str(r.get("item", {}).get("id", ""))
            is_grail = r.get("is_grail", False)
            if item_id and item_id in self._alerted_ids and not is_grail:
                continue
            brand = r.get("brand") or ""
            if brand and not is_grail:
                if brand_counts.get(brand, 0) >= 2:
                    continue
                brand_counts[brand] = brand_counts.get(brand, 0) + 1
            if item_id:
                self._alerted_ids.add(item_id)
            final.append(r)
            if len(final) >= 10:
                break

        # Requirement 2 — pipeline metrics
        print(f"  📊 Processed: {processed}/{total} | Sending: {len(final)}")

        if len(self._alerted_ids) > 10_000:
            self._alerted_ids = set(list(self._alerted_ids)[-5_000:])

        self.db.save()
        return final
        """
        Legacy evaluate() — deleguje do odpowiedniego silnika.
        Grail → Brand → Chaos (kolejność priorytetów).
        """
        title  = item.get("title", "")
        brand  = detect_brand(title)
        mps    = {search.get("name", ""): market_price} if market_price else {}

        # Grail ma priorytet
        g = self.grail._evaluate(item)
        if g["send_alert"]:
            return self._to_legacy(g)

        # Brand gdy jest brand
        if brand:
            b = self.brand._evaluate(item, mps)
            if b["send_alert"]:
                return self._to_legacy(b)

        # Chaos fallback
        c = self.chaos._evaluate(item)
        return self._to_legacy(c)

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


# Re-export extract_item_features so bot.py can import it directly
__all__ = [
    "Engine", "MarketDB", "ChaosEngine", "BrandEngine", "GrailEngine",
    "format_alert", "extract_item_features",
    "detect_brand", "detect_category", "is_foreign_title",
]
