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
from collections import defaultdict


# ─────────────────────────────────────────────────────
#  📁 PLIKI
# ─────────────────────────────────────────────────────
DB_FILE          = "market_db.json"
RAW_FILE         = "raw_items.json"
FEEDBACK_FILE    = "feedback.json"
AI_CACHE_FILE    = "ai_cache.json"

# ─────────────────────────────────────────────────────
#  ⚙️ PROGI
# ─────────────────────────────────────────────────────
CONFIDENCE_INSANE  = 8.5   # 🔴 INSANE DEAL
CONFIDENCE_GOOD    = 7.0   # 🟡 GOOD DEAL
CONFIDENCE_WATCH   = 5.5   # ⚪ WATCH

DB_MIN_SAMPLES     = 3     # min próbek żeby użyć DB
DB_BUILD_EVERY     = 150   # buduj DB co N nowych itemów
FLIP_MIN_PROFIT    = 30    # min zysk flip (PLN) żeby liczyć
FAKE_LUXURY_RATIO  = 0.35  # cena < 35% avg → podejrzenie fake

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


def detect_category(title: str) -> str:
    t = title.lower()
    for cat, keywords in CATEGORY_MAP.items():
        if any(kw in t for kw in keywords):
            return cat
    return "other"


def detect_brand(title: str) -> str | None:
    t = title.lower()
    all_brands = (
        list(LUXURY_BRANDS) + list(HYPE_BRANDS) +
        ["nike", "adidas", "puma", "reebok", "lego", "funko"]
    )
    for brand in sorted(all_brands, key=len, reverse=True):
        if brand in t:
            return brand
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
        """Grupuje surowe itemy i oblicza statystyki cenowe.
        FIX #2: Merguje nowe dane z istniejącą bazą (nie nadpisuje).
        FIX #3: Filtruje outlier'y przez IQR przed liczeniem statystyk.
        """
        groups: dict[str, list[float]] = defaultdict(list)
        group_history: dict[str, list[dict]] = defaultdict(list)

        for item in raw_items:
            key = normalize_title(item["title"])
            if key == "unknown":
                continue
            groups[key].append(item["price"])
            group_history[key].append({
                "price": item["price"],
                "ts": item.get("ts", 0),
            })

        new_db = {}
        for key, prices in groups.items():
            if len(prices) < DB_MIN_SAMPLES:
                continue

            # FIX #3 — IQR outlier filter
            prices = self._filter_outliers(prices)
            if len(prices) < DB_MIN_SAMPLES:
                continue

            history = sorted(group_history[key], key=lambda x: x["ts"])
            trend = self._detect_trend(history)

            new_entry = {
                "avg":    round(mean(prices), 2),
                "median": round(median(prices), 2),
                "min":    round(min(prices), 2),
                "max":    round(max(prices), 2),
                "std":    round(stdev(prices) if len(prices) > 1 else 0, 2),
                "count":  len(prices),
                "trend":  trend,
                "updated": time.time(),
            }

            # FIX #2 — merge z istniejącą bazą (weighted average)
            if key in self.db:
                old = self.db[key]
                old_count = old.get("count", 0)
                new_count = new_entry["count"]
                total = old_count + new_count
                if total > 0:
                    new_entry["avg"] = round(
                        (old["avg"] * old_count + new_entry["avg"] * new_count) / total, 2
                    )
                    new_entry["count"] = total
                    new_entry["min"] = min(old.get("min", new_entry["min"]), new_entry["min"])
                    new_entry["max"] = max(old.get("max", new_entry["max"]), new_entry["max"])
                    # Mediana: użyj nowej (z aktualnych danych)
                    # std: zachowaj nowe

            new_db[key] = new_entry

        # Zachowaj wpisy których nie ma w nowym buildzie (historyczne dane)
        for key, data in self.db.items():
            if key not in new_db:
                new_db[key] = data

        self.db = new_db
        self.save()
        print(f"  📊 MarketDB zbudowana: {len(self.db)} grup")
        return new_db

    def _filter_outliers(self, prices: list[float]) -> list[float]:
        """FIX #3 — usuwa ceny poza zakresem Q1*0.5 .. Q3*1.5."""
        if len(prices) < 4:
            return prices
        s = sorted(prices)
        n = len(s)
        q1 = s[n // 4]
        q3 = s[(n * 3) // 4]
        lo = q1 * 0.5
        hi = q3 * 1.5
        filtered = [p for p in s if lo < p < hi]
        return filtered if len(filtered) >= DB_MIN_SAMPLES else prices

    def _detect_trend(self, history: list[dict]) -> str:
        """Wykrywa trend cenowy na podstawie historii."""
        if len(history) < 4:
            return "stable"
        prices = [h["price"] for h in history[-6:]]  # ostatnie 6
        mid = len(prices) // 2
        avg_old = mean(prices[:mid])
        avg_new = mean(prices[mid:])
        if avg_new > avg_old * 1.15:
            return "rising"
        if avg_new < avg_old * 0.85:
            return "falling"
        return "stable"

    def lookup(self, title: str) -> dict | None:
        key = normalize_title(title)
        return self.db.get(key)

    def lookup_by_brand_category(self, brand: str, category: str) -> dict | None:
        """Fallback — znajdź dane dla marki+kategorii."""
        query = f"{brand}_{category}"
        # Szukaj najbliższego klucza
        for key, data in self.db.items():
            if brand in key and data.get("count", 0) >= 5:
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
def calculate_confidence(
    price: float,
    db_data: dict | None,
    ai_data: dict,
    market_price: float | None,
    brand: str | None,
    category: str,
    learner: FeedbackLearner,
) -> dict:
    """
    Oblicza confidence score (0–10) z trzech źródeł:
      - db_score   (40%) — porównanie z naszą bazą
      - market_score (30%) — porównanie z medianą Vinted
      - ai_score   (30%) — ocena AI

    Zwraca:
    {
        confidence, db_score, market_score, ai_score,
        fake_risk, flip_profit, trend
    }
    """

    # ── DB SCORE (0–10) ──────────────────────
    db_score = 5.0
    flip_profit = 0.0
    fake_risk = False
    trend = "stable"

    if db_data:
        avg = db_data["avg"]
        ratio = price / avg if avg > 0 else 1.0
        trend = db_data.get("trend", "stable")

        if ratio < 0.50:
            db_score = 10.0
        elif ratio < 0.60:
            db_score = 9.0
        elif ratio < 0.70:
            db_score = 8.0
        elif ratio < 0.80:
            db_score = 6.5
        elif ratio < 0.90:
            db_score = 5.0
        else:
            db_score = 3.0

        # Fake risk — luksus bardzo tani
        if brand in LUXURY_BRANDS and ratio < FAKE_LUXURY_RATIO:
            fake_risk = True
            db_score = max(db_score - 2.0, 0.0)

        # FIX #9 — silniejsza detekcja fake luxury: poniżej 30% avg
        if brand in LUXURY_BRANDS and ratio < 0.30:
            fake_risk = True
            db_score = max(db_score - 3.0, 0.0)  # dodatkowa kara -3

        # Flip profit
        estimated = ai_data.get("estimated_value", avg)
        flip_profit = max(estimated - price, 0.0)

        # Trend boost
        if trend == "rising":
            db_score = min(db_score + 0.5, 10.0)
        elif trend == "falling":
            db_score = max(db_score - 0.5, 0.0)

    # ── MARKET SCORE (0–10) ──────────────────
    market_score = 5.0
    if market_price and market_price > 0:
        # FIX #7 — market_price unreliable below 20 zł
        if market_price < 20:
            market_score = 5.0
        else:
            ratio = price / market_price
            if ratio < 0.50:
                market_score = 10.0
            elif ratio < 0.60:
                market_score = 9.0
            elif ratio < 0.70:
                market_score = 8.0
            elif ratio < 0.80:
                market_score = 6.5
            elif ratio < 0.90:
                market_score = 5.0
            else:
                market_score = 3.0

    # ── AI SCORE (0–10) ──────────────────────
    ai_score = float(ai_data.get("final_score", 5.0))

    # Hype bonus
    hype = ai_data.get("hype_score", 3)
    if hype >= 8:
        ai_score = min(ai_score + 1.0, 10.0)
    elif hype >= 6:
        ai_score = min(ai_score + 0.5, 10.0)

    # Rarity bonus
    rarity = ai_data.get("rarity", 3)
    if rarity >= 8:
        ai_score = min(ai_score + 1.0, 10.0)

    # Flip profit boost
    if flip_profit > FLIP_MIN_PROFIT:
        boost = min(flip_profit / 100.0, 1.5)
        ai_score = min(ai_score + boost, 10.0)

    # FIX #6 — flip profit bezpośrednio wpływa na confidence
    flip_confidence_bonus = 0.0
    if flip_profit > 500:
        flip_confidence_bonus = 2.0
    elif flip_profit > 200:
        flip_confidence_bonus = 1.0

    # ── WEIGHTED CONFIDENCE ───────────────────
    confidence = (
        db_score     * 0.40 +
        market_score * 0.30 +
        ai_score     * 0.30
    )

    # FIX #6 — flip profit bonus (po ważeniu)
    confidence += flip_confidence_bonus

    # ── SELF-LEARNING BONUS ───────────────────
    if brand:
        confidence += learner.get_brand_bonus(brand) * 0.3
    confidence += learner.get_category_bonus(category) * 0.2

    # FIX #6 — clamp do max 10
    confidence = min(confidence, 10.0)

    return {
        "confidence":   round(confidence, 2),
        "db_score":     round(db_score, 2),
        "market_score": round(market_score, 2),
        "ai_score":     round(ai_score, 2),
        "fake_risk":    fake_risk,
        "flip_profit":  round(flip_profit, 2),
        "trend":        trend,
    }


# ─────────────────────────────────────────────────────
#  🔔 ALERT TIER
# ─────────────────────────────────────────────────────
def get_alert_tier(confidence: float, ai_decision: str) -> str | None:
    """
    Zwraca tier alertu lub None jeśli nie wysyłać.
    """
    if confidence >= CONFIDENCE_INSANE or ai_decision == "BUY":
        return "INSANE"
    if confidence >= CONFIDENCE_GOOD:
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

        # 3. Lookup w bazie
        db_data = self.db.lookup(title)
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
        )

        # 6. Fake risk — zmniejsz confidence
        if scoring["fake_risk"]:
            # FIX #9 — silna kara za fake luxury
            scoring["confidence"] = max(scoring["confidence"] - 2.0, 0.0)

        # 7. Decyzja
        confidence   = scoring["confidence"]
        ai_decision  = ai_data.get("decision", "SKIP")
        flip_profit  = scoring["flip_profit"]

        # FIX #10 — confidence floor: poniżej 5 → zawsze SKIP
        if confidence < 5.0:
            ai_decision = "SKIP"

        # Dodatkowy warunek: cena < 50% avg DB → zawsze alert
        force_alert = (
            db_data is not None and
            price < db_data["avg"] * 0.50
        )

        tier = get_alert_tier(confidence, ai_decision)

        # FIX #5 — redukcja spamu: wyślij alert tylko gdy spełnione warunki
        raw_send = bool(tier) or force_alert
        spam_filtered = (
            confidence >= 6.5
            or ai_decision == "BUY"
            or (db_data is not None and price < db_data["avg"] * 0.50)
            # FIX #5: mainstream brand bez DB → obniż próg do 5.5
            # (nie do zera — wciąż filtrujemy śmieci)
            or (brand in MAINSTREAM_BRANDS and confidence >= 5.5)
        )

        # FIX #2 — deduplicacja: nie wysyłaj alertu dwa razy dla tego samego item_id
        item_id = str(item.get("id", ""))
        already_alerted = item_id and item_id in self._alerted_ids
        send_alert = raw_send and spam_filtered and not already_alerted
        if send_alert and item_id:
            self._alerted_ids.add(item_id)
            # Trzymaj max 10 000 ID w pamięci (ochrona przed wyciekiem)
            if len(self._alerted_ids) > 10_000:
                self._alerted_ids = set(list(self._alerted_ids)[-5_000:])

        return {
            "send_alert":  send_alert,
            "tier":        tier or ("GOOD" if force_alert else None),
            "confidence":  confidence,
            "scoring":     scoring,
            "ai_data":     ai_data,
            "db_data":     db_data,
            "brand":       brand,
            "category":    category,
            "flip_profit": flip_profit,
            "item":        item,
            "market_price": market_price,
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
        # Bez tego każdy item bez DB dostaje score=5 → conf≈5.6 → spam filter blokuje
        if brand in HYPE_BRANDS:
            base = 6.5   # hype brand bez DB → przekracza spam filter 6.5
        elif brand in LUXURY_BRANDS:
            base = 6.0   # luxury → wymaga jeszcze sygnału żeby przejść
        elif brand in MAINSTREAM_BRANDS:
            base = 5.8   # Nike, Adidas itd. → przejdą obniżony próg 5.5
        elif category in ("sneakers", "funko", "lego"):
            base = 5.8   # znana kategoria kolekcjonerska
        else:
            base = 5.0   # bez marki / nieznana kategoria

        avg = db_data["avg"] if db_data else price * 1.5
        underpriced = price < avg * 0.70
        estimated = avg * 1.1 if db_data else price * 1.5

        score = base
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
        flip      = result.get("flip_profit", 0)

        # Tytuł bez metadanych Vinted
        clean = re.sub(r',?\s*(marka|stan|rozmiar):.*', '', title, flags=re.IGNORECASE).strip()

        # Tier emoji
        if tier == "INSANE":
            header = "🔴 INSANE DEAL"
        elif tier == "GOOD":
            header = "🟡 GOOD DEAL"
        else:
            header = "⚪ WATCH"

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
            lines.append(f"💚  Flip profit: ~{flip:.0f} zł")

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
