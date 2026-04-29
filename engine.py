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
_DATA_DIR     = os.getenv("DATA_DIR", "/tmp/vinted_bot")
os.makedirs(_DATA_DIR, exist_ok=True)

DB_FILE       = os.path.join(_DATA_DIR, "market_db.json")

DEBUG_ALERTS  = True

# Part 6 — zmienione z 15 → 60 min
MAX_ITEM_AGE_MINUTES = 60


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
    Uproszczona baza cen rynkowych.
    Part 5: NIE blokuje chaos data (brand NOT required).
    """
    MAX_SAMPLES   = 50
    MAX_AGE_HOURS = 48

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

    def add_sample(self, key: str, price: float):
        """Part 5 — przechowuje próbkę. Klucz może być kategorią lub tytułem."""
        if not key or price < 10:
            return
        now = time.time()
        if key not in self.db:
            self.db[key] = {
                "median": price, "avg": price, "p25": price,
                "count": 0, "updated": now, "_samples": [],
            }
        entry   = self.db[key]
        samples = entry.get("_samples", [])
        samples.append({"price": price, "ts": now})
        samples = [s for s in samples if now - s["ts"] < self.MAX_AGE_HOURS * 3600]
        samples = samples[-self.MAX_SAMPLES:]
        prices  = sorted(s["price"] for s in samples)
        n       = len(prices)
        if n >= 2:
            med = statistics.median(prices)
            entry.update({
                "median":  round(med, 2),
                "avg":     round(sum(prices) / n, 2),
                "p25":     round(prices[max(0, n // 4 - 1)], 2),
                "p75":     round(prices[min(n - 1, (n * 3) // 4)], 2),
                "min":     round(prices[0], 2),
                "max":     round(prices[-1], 2),
                "count":   n,
                "updated": now,
            })
        entry["_samples"] = samples
        self.db[key] = entry

    def lookup(self, key: str) -> dict | None:
        return self.db.get(key)

    def lookup_brand_category(self, brand: str, category: str | None) -> dict | None:
        """Szuka po brand+category lub samym brand."""
        if category:
            key = f"{brand}_{category}"
            if key in self.db:
                return self.db[key]
        for k, v in self.db.items():
            if brand in k and v.get("count", 0) >= 3:
                return v
        return None


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

    def run(self, items: list[dict]) -> list[dict]:
        self._sent = self._skipped = 0
        results = []
        for item in items:
            r = self._evaluate(item)
            if r["send_alert"]:
                results.append(r)
                self._sent += 1
            else:
                self._skipped += 1
        if DEBUG_ALERTS:
            print(f"  [CHAOS] sent={self._sent} skipped={self._skipped}")
        return results

    def _evaluate(self, item: dict) -> dict:
        title = item.get("title", "")
        price = item.get("price", 0) or 0

        base = {"engine": "CHAOS", "item": item, "send_alert": False,
                "tier": "CHAOS", "profit": 0, "confidence": 0}

        if kw(title, _CHAOS_TRASH):
            return {**base, "_skip_reason": "trash"}
        if price > 120 or price < 18:
            return {**base, "_skip_reason": "price_out_of_range"}

        age = item_age_minutes(item)
        if age > MAX_ITEM_AGE_MINUTES * 6:
            return {**base, "_skip_reason": "stale"}

        # Profit logic (Part 2)
        estimated_value = price * 1.6
        profit          = estimated_value - price   # = price * 0.6

        # Scoring
        score = 0.0
        if _is_vintage(title):          score += 1.0
        if kw(title, _CHAOS_STYLE_KW):  score += 1.0
        if kw(title, _CHAOS_VINTAGE_KW): score += 2.0
        if detect_brand(title):          score += 1.0
        if 20 <= price <= 50:            score += 1.0
        elif 50 < price <= 80:           score += 0.5
        score += freshness_boost(age) * 0.3

        # Send rule
        send = (price <= 80 and profit >= 15 and score >= 1.0)

        # DB learning (Part 5 — chaos też uczy DB)
        cat = detect_category(title)
        brand = detect_brand(title)
        if cat:
            self.db.add_sample(f"chaos_{cat}", price)
        if brand and cat:
            self.db.add_sample(f"{brand}_{cat}", price)

        if DEBUG_ALERTS and send:
            print(f"  ⚡ [CHAOS] {title[:55]} | {price}zł | profit≈{profit:.0f}zł | score={score:.1f}")

        return {
            **base,
            "send_alert":      send,
            "profit":          round(profit, 2),
            "estimated_value": round(estimated_value, 2),
            "confidence":      round(min(score * 1.5, 10.0), 2),
            "brand":           brand,
            "category":        cat,
            "age_min":         age,
            "score":           round(score, 2),
            "_skip_reason":    None if send else "score_too_low",
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

    def run(self, items: list[dict], market_prices: dict | None = None) -> list[dict]:
        self._sent = self._skipped = 0
        results = []
        market_prices = market_prices or {}
        for item in items:
            r = self._evaluate(item, market_prices)
            if r["send_alert"]:
                results.append(r)
                self._sent += 1
            else:
                self._skipped += 1
        if DEBUG_ALERTS:
            print(f"  [BRAND] sent={self._sent} skipped={self._skipped}")
        return results

    def _evaluate(self, item: dict, market_prices: dict) -> dict:
        title    = item.get("title", "")
        price    = item.get("price", 0) or 0
        brand    = detect_brand(title)
        category = detect_category(title)

        base = {"engine": "BRAND", "item": item, "send_alert": False,
                "tier": "BRAND", "profit": 0, "confidence": 0,
                "brand": brand, "category": category}

        if not brand:
            return {**base, "_skip_reason": "no_brand"}
        if not category:
            return {**base, "_skip_reason": "no_category"}

        age = item_age_minutes(item)
        if age > MAX_ITEM_AGE_MINUTES * 4:
            return {**base, "_skip_reason": "stale"}

        # Znajdź medianę (kolejność priorytetów)
        median_price = self._find_median(brand, category, market_prices)
        profit       = (median_price - price) if median_price else 0.0

        # Confidence scoring
        conf = 3.0   # brand +3
        if category:
            conf += 2.0   # category +2

        if median_price and median_price > 0:
            ratio = price / median_price
            if ratio < 0.50:   conf += 4.0
            elif ratio < 0.60: conf += 3.0
            elif ratio < 0.70: conf += 2.0   # good price +2
            elif ratio < 0.80: conf += 1.0
            else:              conf -= 1.0

        conf += freshness_boost(age) * 0.4

        # Luxury fake guard
        if brand in LUXURY_BRANDS and price < 100:
            conf -= 3.0

        # Send rule: price < median * 0.7 AND profit >= 25
        send = bool(
            median_price and
            median_price > 0 and
            price < median_price * 0.7 and
            profit >= 25 and
            conf >= 5.0
        )

        # DB learning
        if category:
            self.db.add_sample(f"{brand}_{category}", price)

        if DEBUG_ALERTS and send:
            print(f"  🟣 [BRAND] {title[:55]} | brand={brand} | "
                  f"{price}zł (med={median_price:.0f}zł) | profit≈{profit:.0f}zł | conf={conf:.1f}")

        return {
            **base,
            "send_alert":    send,
            "profit":        round(profit, 2),
            "median_price":  round(median_price, 2) if median_price else None,
            "estimated_value": round(median_price, 2) if median_price else 0,
            "confidence":    round(min(conf, 10.0), 2),
            "age_min":       age,
            "_skip_reason":  None if send else "below_threshold",
        }

    def _find_median(self, brand: str, category: str, market_prices: dict) -> float | None:
        # 1. bot.py market_prices (Vinted endpoint)
        for mp_key, mp_val in market_prices.items():
            if brand.lower() in mp_key.lower() and mp_val:
                return float(mp_val)
        # 2. MarketDB
        db_data = self.db.lookup_brand_category(brand, category)
        if db_data:
            v = db_data.get("median") or db_data.get("avg")
            if v:
                return float(v)
        # 3. Heurystyczna cena
        brand_prices = _HEURISTIC_PRICES.get(brand)
        if brand_prices:
            return float(brand_prices.get(category, brand_prices["default"]))
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🟡 GRAIL ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_GRAIL_KEYWORDS = [
    "single stitch", "made in usa", "90s", "80s", "70s",
    "tour", "promo", "band", "band tee", "movie", "film",
    "rap tee", "harley davidson", "bootleg", "concert tee",
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

    def run(self, items: list[dict]) -> list[dict]:
        self._sent = self._skipped = 0
        results = []
        for item in items:
            r = self._evaluate(item)
            if r["send_alert"]:
                results.append(r)
                self._sent += 1
            else:
                self._skipped += 1
        if DEBUG_ALERTS:
            print(f"  [GRAIL] sent={self._sent} skipped={self._skipped}")
        return results

    def _evaluate(self, item: dict) -> dict:
        title = item.get("title", "")
        price = item.get("price", 0) or 0
        t     = title.lower()

        base = {"engine": "GRAIL", "item": item, "send_alert": False,
                "tier": "GRAIL", "profit": 0, "confidence": 0,
                "is_grail": False, "grail_score": 0}

        age = item_age_minutes(item)
        if age > MAX_ITEM_AGE_MINUTES * 6:
            return {**base, "_skip_reason": "stale"}

        # Grail scoring (Part 4)
        score = 0

        kw_hits = sum(1 for k in _GRAIL_KEYWORDS if k in t)
        if kw_hits >= 1:   score += 2
        if kw_hits >= 2:   score += 1   # bonus za kombinację

        if kw(title, _GRAIL_BRANDS):   score += 2

        # Extra signals
        if "tour"           in t: score += 1
        if "single stitch"  in t: score += 1
        if "band" in t or "movie" in t: score += 1
        if "bootleg"        in t: score += 1

        # Heurystyczna wycena grail (Part 4)
        estimated = self._estimate_value(title, price, score)
        profit    = estimated - price

        # Underpriced → +2
        if estimated > 0 and price < estimated * 0.7:
            score += 2

        is_grail = score >= 3

        # Send rule: is_grail AND profit >= 10
        send     = is_grail and profit >= 10
        conf     = float(score) * 1.2 + freshness_boost(age) * 0.4

        # DB learning
        cat = detect_category(title)
        if cat:
            self.db.add_sample(f"grail_{cat}", price)

        if DEBUG_ALERTS and send:
            print(f"  💎 [GRAIL] {title[:55]} | {price}zł | score={score} | profit≈{profit:.0f}zł")

        return {
            **base,
            "send_alert":      send,
            "is_grail":        is_grail,
            "grail_score":     score,
            "profit":          round(profit, 2),
            "estimated_value": round(estimated, 2),
            "confidence":      round(min(conf, 10.0), 2),
            "brand":           detect_brand(title),
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

    # ── NOWY INTERFEJS (Part 1) ──────────────────────
    def run_cycle(self, items: list[dict], market_prices: dict | None = None) -> list[dict]:
        """
        Uruchamia wszystkie 3 silniki i zwraca deduplikowane wyniki.
        Part 1: chaos_items + brand_items + grail_items → all_items.
        """
        chaos_r = self.chaos.run(items)
        brand_r = self.brand.run(items, market_prices)
        grail_r = self.grail.run(items)
        all_r   = chaos_r + brand_r + grail_r

        # Deduplikacja po item_id (jeden item → max jeden silnik)
        seen_ids: set[str] = set()
        deduped = []
        for r in sorted(all_r, key=lambda x: -x.get("profit", 0)):
            item_id = str(r["item"].get("id", ""))
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            deduped.append(r)

        # Sesyjna deduplikacja
        final = []
        for r in deduped:
            item_id = str(r["item"].get("id", ""))
            if item_id and item_id in self._alerted_ids:
                continue
            if item_id:
                self._alerted_ids.add(item_id)
            final.append(r)

        if len(self._alerted_ids) > 10_000:
            self._alerted_ids = set(list(self._alerted_ids)[-5_000:])

        return final

    # ── STARY INTERFEJS (kompatybilność z bot.py) ────
    def evaluate(self, item: dict, search: dict, market_price: float | None) -> dict:
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
        return (
            f"🧠 Engine v2.0 stats:\n"
            f"  DB groups:   {len(self.db.db)}\n"
            f"  Raw items:   0 (chaos data in DB)\n"
            f"  AI cache:    0\n"
            f"  Clicked:     0\n"
            f"  Bought:      0"
        )

    def record_click(self, *args): pass
    def record_buy(self, *args):   pass
