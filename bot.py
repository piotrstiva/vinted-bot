import requests
import time
import os
import json
import re
import base64
import random
import unicodedata
import sys
from urllib.parse import quote_plus, urlparse
from statistics import median
from bs4 import BeautifulSoup

# ── Intelligence Engine ──────────────────
try:
    from engine import Engine, extract_item_features, detect_brand, detect_category
    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False
    print("⚠️  engine.py nie znaleziony — tryb podstawowy")
    def extract_item_features(item):
        return {"brand": None, "has_brand": False,
                "is_vintage": False, "category": None, "keywords": []}
    def detect_brand(title): return None
    def detect_category(title): return None

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
MAX_ALERTS_PER_SEARCH = 20  # więcej itemów do engine — silniki same filtrują jakość
DEBUG_ALERTS          = os.getenv("DEBUG_ALERTS", "1") == "1"  # FIX: loguj decyzje engine (conf, profit, grail)
DEBUG_PIPELINE        = os.getenv("DEBUG_PIPELINE", "0") == "1"  # verbose pipeline log
VERBOSE_ITEM_DEBUG = os.getenv("VERBOSE_ITEM_DEBUG", "0") == "1"
MAX_VERBOSE_LOGS_PER_CYCLE = int(os.getenv("MAX_VERBOSE_LOGS_PER_CYCLE", "200"))
TASTE_DISCOVERY_ENABLED = os.getenv("TASTE_DISCOVERY_ENABLED", "1") == "1"
TASTE_DISCOVERY_MAX_QUERIES_PER_CYCLE = int(os.getenv("TASTE_DISCOVERY_MAX_QUERIES_PER_CYCLE", "3"))
RAW_STYLE_SNIPER_ENABLED = os.getenv("RAW_STYLE_SNIPER_ENABLED", "1") == "1"
RAW_STYLE_SNIPER_MAX_PER_CYCLE = int(os.getenv("RAW_STYLE_SNIPER_MAX_PER_CYCLE", "3"))
RAW_STYLE_SNIPER_MAX_AGE_MIN = int(os.getenv("RAW_STYLE_SNIPER_MAX_AGE_MIN", "90"))
RAW_STYLE_SNIPER_MAX_PRICE = float(os.getenv("RAW_STYLE_SNIPER_MAX_PRICE", "160"))
NEGOTIATION_BUFFER_PLN = float(os.getenv("NEGOTIATION_BUFFER_PLN", "15"))
RAW_STYLE_MAX_VISIBLE_AGE_MIN = int(os.getenv("RAW_STYLE_MAX_VISIBLE_AGE_MIN", "180"))
DETAIL_AGE_VERIFY_ENABLED = os.getenv("DETAIL_AGE_VERIFY_ENABLED", "0") == "1"
MAX_DETAIL_SEND_AGE_MIN = int(os.getenv("MAX_DETAIL_SEND_AGE_MIN", "4320"))
ALLOW_UNVERIFIED_AGE_FOR_STRONG_GRAIL = os.getenv("ALLOW_UNVERIFIED_AGE_FOR_STRONG_GRAIL", "1") == "1"
SAFEGUARD_STRICT_PRESEND_ENABLED = os.getenv("SAFEGUARD_STRICT_PRESEND_ENABLED", "1") == "1"
SAFEGUARD_MAX_SEND_PER_CYCLE = int(os.getenv("SAFEGUARD_MAX_SEND_PER_CYCLE", "1"))
STARTUP_IMAGE_ENABLED = os.getenv("STARTUP_IMAGE_ENABLED", "1") == "1"
STARTUP_IMAGE_PATH = os.getenv("STARTUP_IMAGE_PATH", "assets/hidden_gem_logo.png")
STARTUP_IMAGE_URL = os.getenv("STARTUP_IMAGE_URL", "")
STARTUP_MESSAGE_COMPACT = os.getenv("STARTUP_MESSAGE_COMPACT", "1") == "1"
CANDIDATE_AUDIT_ENABLED = os.getenv("CANDIDATE_AUDIT_ENABLED", "1") == "1"
CANDIDATE_AUDIT_PATH = os.getenv("CANDIDATE_AUDIT_PATH", "/data/vinted_bot/candidate_audit.jsonl")
CANDIDATE_AUDIT_MAX_LINES_PER_CYCLE = int(os.getenv("CANDIDATE_AUDIT_MAX_LINES_PER_CYCLE", "300"))
CANDIDATE_AUDIT_TELEGRAM_SUMMARY = os.getenv("CANDIDATE_AUDIT_TELEGRAM_SUMMARY", "0") == "1"
AUDIT_WATCH_TITLES = os.getenv("AUDIT_WATCH_TITLES", "")
FRESH_DISCOVERY_ENABLED = os.getenv("FRESH_DISCOVERY_ENABLED", "1") == "1"
FRESH_DISCOVERY_PER_CYCLE = max(0, int(os.getenv("FRESH_DISCOVERY_PER_CYCLE", "1")))

if DETAIL_AGE_VERIFY_ENABLED:
    print("[DETAIL_AGE_VERIFY_ENABLED]")
else:
    print("[DETAIL_AGE_VERIFY_DISABLED]")

# ─────────────────────────────────────────
#  ⚡ SNIPER MODE
# ─────────────────────────────────────────
MAX_ITEM_AGE_MINUTES  = 15   # Part 1 — tylko świeże oferty 0–15 min
SLEEP_BETWEEN_CYCLES  = 45   # zwiększone z 15s — daj IP czas na reset rate-limitu

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
    # FIX #1 — LEGO clothing / akcesoria które nie są zestawami
    # (Vinted taguje je marką LEGO bo mają logo)
    "bluza lego", "lego bluza", "kurtka lego", "lego kurtka",
    "piżama lego", "lego piżama", "t-shirt lego", "lego t-shirt",
    "czapka lego", "lego czapka", "buty lego", "lego buty",
    "plecak lego", "lego plecak", "torba lego", "lego torba",
    "aparat lego", "lego aparat", "zegarek lego", "lego zegarek",
    "lego 128", "lego 92", "lego 98", "lego 104", "lego 116",  # rozmiary odzieży
    # FIX #1 — luzem klocki (nie kompletne zestawy)
    "luzem", "bulk", "loose", "mixed", "random klocki",
    "worek klocków", "klocki luzem", "mix klocków", "klocki mix",
    # FIX #1 — drukarki 3D / podstawki / akcesoria display
    "3d print", "3d druk", "druk 3d", "display stand", "display dla",
    "podstawka pod", "podstawka lego", "stand lego", "stand dla lego",
    "uchwyt lego", "ramka lego", "gablotka",
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🎯 SEARCH PROFILES — per-query filtering rules
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Each profile defines HOW items from a specific search query are filtered.
# key = search["name"] (must match exactly)
# strict=True → ALL required_phrases must appear in title
# strict=False → at least one required_phrase is enough

SEARCH_PROFILES: dict[str, dict] = {
    # ── Vintage tees ──────────────────────────────────
    "Single Stitch Vintage": {
        "required_phrases": ["single stitch"],
        "allowed_types":    ["t-shirt", "tee", "tshirt", "koszulka", "shirt", "top"],
        "exclude_phrases":  ["sukienka", "dress", "bluzka", "spodnie", "jeans",
                             "kurtka", "jacket", "bluza", "hoodie"],
        "exclude_brands":   ["zara", "h&m", "shein", "bershka", "sinsay", "reserved"],
        "strict":           True,
    },
    "Single Stitch": {
        "required_phrases": ["single stitch"],
        "allowed_types":    ["t-shirt", "tee", "tshirt", "koszulka", "shirt"],
        "exclude_brands":   ["zara", "h&m", "shein", "bershka"],
        "strict":           True,
    },
    "Band Tee Vintage Tour": {
        "required_phrases": ["band", "tour", "tee", "shirt"],
        "allowed_types":    ["t-shirt", "tee", "tshirt", "koszulka", "shirt"],
        "exclude_phrases":  ["sukienka", "dress", "bluzka", "spodnie"],
        "exclude_brands":   ["zara", "h&m", "shein", "bershka"],
        "strict":           False,   # at least 1 phrase
    },
    "Nirvana Shirt Vintage": {
        "required_phrases": ["nirvana"],
        "allowed_types":    ["t-shirt", "tee", "tshirt", "koszulka", "shirt"],
        "exclude_brands":   ["zara", "h&m", "shein", "bershka", "hm"],
        "strict":           True,
    },
    "Metallica Shirt Vintage": {
        "required_phrases": ["metallica"],
        "allowed_types":    ["t-shirt", "tee", "tshirt", "koszulka", "shirt"],
        "exclude_brands":   ["zara", "h&m", "shein", "bershka"],
        "strict":           True,
    },
    "Harley Davidson Vintage": {
        "required_phrases": ["harley"],
        "allowed_types":    ["t-shirt", "tee", "tshirt", "koszulka", "shirt",
                             "jacket", "kurtka", "hoodie", "bluza", "sweatshirt"],
        "exclude_brands":   ["zara", "h&m", "shein"],
        "strict":           True,
    },
    "Made In USA Vintage": {
        "required_phrases": ["made in usa", "made in u.s.a"],
        "allowed_types":    ["t-shirt", "tee", "tshirt", "koszulka", "shirt",
                             "jacket", "kurtka", "hoodie", "jeans", "bluza"],
        "exclude_brands":   ["zara", "h&m", "shein", "bershka"],
        "strict":           True,
    },
    "Rap Tee Vintage": {
        "required_phrases": ["rap", "hip hop", "hiphop", "hip-hop"],
        "allowed_types":    ["t-shirt", "tee", "tshirt", "koszulka", "shirt"],
        "exclude_brands":   ["zara", "h&m", "shein"],
        "strict":           False,
    },
    # ── Hype / streetwear ─────────────────────────────
    "Corteiz": {
        "required_phrases": ["corteiz", "crtz"],
        "exclude_brands":   ["zara", "h&m", "shein"],
        "strict":           False,
    },
    "Broken Planet": {
        "required_phrases": ["broken planet"],
        "exclude_brands":   ["zara", "h&m", "shein"],
        "strict":           True,
    },
    "Denim Tears": {
        "required_phrases": ["denim tears"],
        "strict":           True,
    },
    "Represent": {
        "required_phrases": ["represent"],
        "exclude_phrases":  ["represents", "reprezentuje", "reprezentacja"],
        "strict":           True,
    },
    "Essentials Fear of God": {
        "required_phrases": ["essentials", "fear of god", "fog"],
        "strict":           False,
    },
    "Stussy": {
        "required_phrases": ["stussy", "stüssy"],
        "exclude_brands":   ["zara", "h&m", "shein"],
        "strict":           False,
    },
    # ── Workwear / outdoor ────────────────────────────
    "Carhartt WIP": {
        "required_phrases": ["carhartt"],
        "exclude_phrases":  ["dziecięcy", "kids", "baby", "dziecko"],
        "strict":           True,
    },
    "Arc'teryx": {
        "required_phrases": ["arcteryx", "arc'teryx", "arc teryx"],
        "strict":           False,
    },
    "Arc'teryx Beta": {
        "required_phrases": ["arcteryx", "arc'teryx", "arc teryx"],
        "strict":           False,
    },
    "Salomon": {
        "required_phrases": ["salomon"],
        "exclude_phrases":  ["przepis", "salomona"],
        "strict":           True,
    },
    "Salomon XT-6": {
        "required_phrases": ["salomon"],
        "strict":           True,
    },
    # ── Footwear ──────────────────────────────────────
    "New Balance": {
        "required_phrases": ["new balance"],
        "allowed_types":    ["sneakers", "shoes", "buty", "trainers", "runners"],
        "strict":           True,
    },
    "New Balance 1906R": {
        "required_phrases": ["new balance", "1906"],
        "strict":           True,
    },
    "ASICS": {
        "required_phrases": ["asics"],
        "allowed_types":    ["sneakers", "shoes", "buty", "trainers", "gel"],
        "strict":           True,
    },
    # ── Vintage categories ────────────────────────────
    "Vintage T-Shirt": {
        "required_phrases": ["vintage"],
        "allowed_types":    ["t-shirt", "tee", "tshirt", "koszulka", "shirt"],
        "exclude_phrases":  ["sukienka", "dress", "bluzka", "spodnie", "legginsy",
                             "bikini", "bra", "stanik", "swimsuit"],
        "exclude_brands":   ["zara", "h&m", "shein", "bershka", "sinsay"],
        "strict":           True,
    },
    "Vintage Hoodie": {
        "required_phrases": ["vintage"],
        "allowed_types":    ["hoodie", "bluza", "sweatshirt", "crewneck", "zip"],
        "exclude_phrases":  ["sukienka", "dress", "bluzka"],
        "exclude_brands":   ["zara", "h&m", "shein", "bershka"],
        "strict":           True,
    },
    "Retro Jacket": {
        "required_phrases": [],
        "allowed_types":    ["jacket", "kurtka", "bomber", "varsity", "windbreaker",
                             "anorak", "windrunner", "parka"],
        "exclude_phrases":  ["sukienka", "bluzka", "spodnie", "legginsy"],
        "exclude_brands":   ["zara", "h&m", "shein", "bershka"],
        "strict":           False,
    },
    "Vintage Adidas": {
        "required_phrases": ["adidas"],
        "exclude_phrases":  ["kids", "dziecięcy", "baby"],
        "strict":           True,
    },
    "Vintage Nike": {
        "required_phrases": ["nike"],
        "exclude_phrases":  ["kids", "dziecięcy", "baby", "sukienka", "dress"],
        "strict":           True,
    },
    "90s Jacket": {
        "required_phrases": ["90s", "90", "lata 90"],
        "allowed_types":    ["jacket", "kurtka", "bomber", "windbreaker", "anorak"],
        "exclude_phrases":  ["sukienka", "bluzka", "legginsy"],
        "strict":           False,
    },
    "Baggy Jeans": {
        "required_phrases": ["baggy", "wide leg", "wide-leg"],
        "allowed_types":    ["jeans", "denim", "dżinsy", "spodnie"],
        "exclude_phrases":  ["sukienka", "bluzka", "top"],
        "strict":           False,
    },
    "Baggy Jeans Vintage": {
        "required_phrases": ["baggy", "vintage"],
        "allowed_types":    ["jeans", "denim", "dżinsy"],
        "strict":           False,
    },
    "Leather Jacket Vintage": {
        "required_phrases": ["leather", "skórzana", "skóra", "skorzana"],
        "allowed_types":    ["jacket", "kurtka"],
        "strict":           False,
    },
    "Shearling Jacket": {
        "required_phrases": ["shearling", "kożuch", "kożuszek", "baranek"],
        "allowed_types":    ["jacket", "kurtka", "coat", "płaszcz"],
        "strict":           False,
    },
    "Varsity Jacket": {
        "required_phrases": ["varsity", "college", "baseball"],
        "allowed_types":    ["jacket", "kurtka"],
        "strict":           False,
    },
    "Bomber Jacket Vintage": {
        "required_phrases": ["bomber"],
        "allowed_types":    ["jacket", "kurtka", "bomber"],
        "strict":           True,
    },
    "Denim Jacket Vintage": {
        "required_phrases": ["denim", "jeans", "jeansowa", "dżinsowa"],
        "allowed_types":    ["jacket", "kurtka"],
        "strict":           True,
    },
    "Cargo Pants": {
        "required_phrases": ["cargo"],
        "allowed_types":    ["pants", "spodnie", "trousers"],
        "exclude_phrases":  ["sukienka", "spódnica", "top"],
        "strict":           True,
    },
    # ── Designer sunglasses ───────────────────────────
    "Designer Sunglasses": {
        "required_phrases": ["okulary", "sunglasses", "glasses"],
        "exclude_phrases":  ["korekcyjne", "prescription", "zerówki"],
        "strict":           False,
    },
    # ── Football / LEGO / Carhartt — leave to validators ──
    # (these go through their own validate_* functions)
}

# ── Profile lookup helper ─────────────────────────────
def get_search_profile(search_name: str) -> dict:
    """
    Returns profile for a search or an empty default profile.
    Falls back gracefully — no KeyError ever.
    """
    return SEARCH_PROFILES.get(search_name, {
        "required_phrases": [],
        "allowed_types":    [],
        "exclude_phrases":  [],
        "exclude_brands":   [],
        "strict":           False,
    })


def apply_search_profile(title: str, price: float, profile: dict,
                         reject_log: list) -> bool:
    """
    Apply structured profile filters to a single item.
    Returns True if item PASSES (should be kept), False if REJECTED.
    Appends reason to reject_log list for [REJECT_REASON] logging.

    Filters applied in order:
      1. exclude_phrases — hard reject
      2. exclude_brands  — hard reject
      3. required_phrases — strict (ALL) or loose (≥1)
      4. allowed_types  — soft match if defined
    """
    if not profile:
        return True  # no profile → pass through

    tl = title.lower()

    # 1. Exclude phrases (hard)
    for phrase in profile.get("exclude_phrases", []):
        if phrase in tl:
            reject_log.append(f"exclude_phrase:{phrase}")
            return False

    # 2. Exclude brands (hard)
    for brand in profile.get("exclude_brands", []):
        if brand in tl:
            reject_log.append(f"bad_brand:{brand}")
            return False

    # 3. Required phrases
    required = profile.get("required_phrases", [])
    if required:
        if profile.get("strict", True):
            # ALL required phrases must be present
            missing = [p for p in required if p not in tl]
            if missing:
                reject_log.append(f"no_keyword:{','.join(missing)}")
                return False
        else:
            # At least ONE required phrase
            if not any(p in tl for p in required):
                reject_log.append(f"no_keyword:{required[0]}")
                return False

    # 4. Allowed types — soft: if defined, at least one must match
    allowed = profile.get("allowed_types", [])
    if allowed:
        if not any(t in tl for t in allowed):
            reject_log.append("wrong_type")
            return False

    return True  # passed all filters


# ── Human vibe filter ─────────────────────────────────
def human_vibe_skip(title: str, pct: float = 0.12) -> bool:
    """
    Req 3 — 10–15% random skip to simulate human inattention.
    Returns True if item should be SKIPPED (not kept).
    """
    return random.random() < pct


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📦 ITEM PROCESSING — human-like depth + micro delays
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Req 2 — Dynamic depth config
DEPTH_CONFIG = {
    "low":    (10, 25),
    "medium": (25, 50),
    "deep":   (50, 80),
}
# Distribution: 30% low, 50% medium, 20% deep
_DEPTH_CHOICES   = ["low",    "medium", "medium", "medium", "deep"]
_DEPTH_WEIGHTS   = [0.30,     0.50,     None,     None,     0.20  ]

# Req 1 — Per-item micro delay config
ITEM_PROCESSING_MIN  = 0.8    # min delay after processing each item
ITEM_PROCESSING_MAX  = 2.5    # max delay after processing each item
ITEM_READ_PAUSE_PCT  = 0.15   # 15% chance of longer "reading" pause
ITEM_READ_PAUSE_MIN  = 3.0
ITEM_READ_PAUSE_MAX  = 8.0

# Req 7 — Random idle config
SEARCH_IDLE_PCT    = 0.20   # 20% chance of idle between searches
SEARCH_IDLE_MIN    = 30.0
SEARCH_IDLE_MAX    = 90.0
# Fake scrolling
SCROLL_ITER_MIN    = 2
SCROLL_ITER_MAX    = 5
SCROLL_STEP_MIN    = 2.0
SCROLL_STEP_MAX    = 6.0
_CORE_SEARCH_ACTIVE = False


def pick_depth() -> tuple[str, int]:
    """
    Req 2 — Pick a random depth level and max_items for this search pass.
    Returns (depth_name, max_items).
    """
    depth = random.choices(
        ["low", "medium", "deep"],
        weights=[0.30, 0.50, 0.20],
        k=1
    )[0]
    lo, hi  = DEPTH_CONFIG[depth]
    max_it  = random.randint(lo, hi)
    return depth, max_it


def item_micro_delay(item_title: str = "") -> None:
    """
    Req 1 — Sleep after processing each item to simulate human reading speed.
    15% chance of longer 'reading' pause.
    """
    if _CORE_SEARCH_ACTIVE:
        return
    if random.random() < ITEM_READ_PAUSE_PCT:
        delay = random.uniform(ITEM_READ_PAUSE_MIN, ITEM_READ_PAUSE_MAX)
        if DEBUG_ALERTS:
            print(f"  [ITEM] reading_pause={delay:.1f}s | {item_title[:30]}")
    else:
        delay = random.uniform(ITEM_PROCESSING_MIN, ITEM_PROCESSING_MAX)
    time.sleep(delay)


def fake_scroll() -> None:
    """
    Req 7 — Simulate human scrolling through the page before processing.
    """
    steps = random.randint(SCROLL_ITER_MIN, SCROLL_ITER_MAX)
    for _ in range(steps):
        time.sleep(random.uniform(SCROLL_STEP_MIN, SCROLL_STEP_MAX))


def maybe_random_idle(context: str = "") -> bool:
    """
    Req 7 — 20% chance of random idle pause (30–90s).
    Returns True if idled.
    """
    if random.random() < SEARCH_IDLE_PCT:
        idle = random.uniform(SEARCH_IDLE_MIN, SEARCH_IDLE_MAX)
        print(f"  [IDLE] random_idle={idle:.0f}s context={context}")
        time.sleep(idle)
        return True
    return False

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

# Słowa które dyskwalifikują ofertę (niekompletna / nie-zestaw)
SW_INCOMPLETE_KEYWORDS = [
    "niekompletny", "brakuje", "bez figurek", "bez minifigurek",
    "niepełny", "części", "uszkodzony", "incomplete",
    "only parts", "spare parts", "zamienię",
    # FIX #2 — druk 3D / podstawki / gablotki (nie zestawy LEGO)
    "3d print", "3d druk", "druk 3d", "printed", "display stand",
    "display dla", "podstawka", "stand dla", "uchwyt", "ramka",
    "gablotka", "diorama",
    # FIX #4 — sama instrukcja bez zestawu
    "instrukcja", "instrukcje", "manual", "booklet", "instruction",
    "tylko instrukcja", "sam instrukcja",
    # FIX #5 — pojedyncza minifigurka (nie zestaw) — ale ostrożnie:
    # "minifigurka" w tytule BEZ numeru setu = prawdopodobnie luzem
    # (validate_lego_sw sprawdza ten warunek przez brak found_set)
    "pojedyncza figurka", "single minifig", "jedna figurka",
    "figurka luzem", "minifig luzem",
    # Kluczbrelok / gadżet
    "brelok", "keychain", "key chain", "kulcstartó", "nyckelring",
    "magnes", "magnet",
]

# ─────────────────────────────────────────
#  ⚽ KOSZULKI RETRO — konfiguracja
# ─────────────────────────────────────────

# Lata które uznajemy za "retro"
RETRO_DECADES = [
    # Lata jako ciągi (pasuje do "1994/95", "94-95" itp.)
    "1970", "1971", "1972", "1973", "1974", "1975", "1976", "1977", "1978", "1979",
    "1980", "1981", "1982", "1983", "1984", "1985", "1986", "1987", "1988", "1989",
    "1990", "1991", "1992", "1993", "1994", "1995", "1996", "1997", "1998", "1999",
    "2000", "2001", "2002", "2003",
    # Skróty dekad
    "70s", "80s", "90s", "00s", "70'", "80'", "90'",
    # Słowa kluczowe
    "vintage", "retro", "classic", "klasyczna", "klasyk",
    "stara", "kolekcjonerska", "historyczna", "archival",
    "throwback", "heritage", "old school",
]

# ─────────────────────────────────────────
#  ⚽ PRODUCENCI KITÓW — oryginalne marki
# ─────────────────────────────────────────
FOOTBALL_ORIGINAL_BRANDS = [
    # Wielka trójka
    "adidas", "nike", "puma",
    # Klasyczne marki retro
    "umbro", "lotto", "kappa", "reebok",
    "diadora", "le coq sportif", "hummel",
    "errea", "uhlsport", "patrick",
    # Inne autentyczne
    "score draw", "admiral", "bukta",
    "ribero", "hafnia", "uhlsport",
    "fila", "asics", "mizuno",
    "new balance", "macron", "joma",
    "castore", "warrior", "burrda",
]

# Słowa sugerujące replikę → odrzucamy
REPLICA_KEYWORDS = [
    "replika", "replica", "kopia", "podróbka", "nieoryginalna",
    "chiński", "chińska", "fakes", "fake", "inspired", "bootleg",
]

# ─────────────────────────────────────────
#  ⚽ BAZA KLUBÓW I REPREZENTACJI
#  Każdy wpis = jedna forma nazwy jaką
#  sprzedający może wpisać na Vinted
# ─────────────────────────────────────────

# ── SERIE A / WŁOCHY ─────────────────────
_SERIE_A = [
    "ac milan", "milan", "rossoneri",
    "inter milan", "inter", "internazionale", "nerazzurri",
    "juventus", "juve", "bianconeri",
    "as roma", "roma", "giallorossi",
    "napoli", "partenopei",
    "lazio", "biancocelesti",
    "fiorentina", "viola",
    "parma", "crociati",
    "sampdoria", "samp",
    "atalanta", "bergamo",
    "torino",
    "udinese",
    "bologna",
    "genoa",
    "cagliari",
    "palermo",
    "bari",
    "reggiana",
    "piacenza",
    "venezia",
    "brescia",
    "lecce",
]

# ── LA LIGA / HISZPANIA ───────────────────
_LA_LIGA = [
    "real madrid", "real madryt", "madrytu", "los blancos", "merengues",
    "barcelona", "barca", "blaugrana", "barca",
    "atletico madrid", "atletico", "atletico de madrid", "colchoneros",
    "sevilla", "sevillistas",
    "valencia", "che",
    "deportivo", "deportivo la coruna", "galicia",
    "real sociedad",
    "athletic bilbao", "athletic club", "leones",
    "villarreal", "submarino amarillo",
    "betis", "real betis",
    "celta vigo", "celta",
    "rayo vallecano", "rayo",
    "racing santander",
    "real zaragoza", "zaragoza",
    "mallorca",
    "osasuna",
    "alaves",
    "espanyol",
]

# ── PREMIER LEAGUE / ANGLIA ───────────────
_PREMIER_LEAGUE = [
    "manchester united", "man utd", "man united", "red devils", "united",
    "liverpool", "reds", "anfield",
    "arsenal", "gunners",
    "chelsea", "blues",
    "tottenham", "spurs", "tottenham hotspur",
    "manchester city", "man city", "citizens",
    "newcastle", "newcastle united", "magpies",
    "leeds", "leeds united", "whites",
    "aston villa", "villa",
    "everton", "toffees",
    "blackburn", "blackburn rovers",
    "west ham", "hammers",
    "nottingham forest", "forest",
    "leicester", "leicester city", "foxes",
    "coventry", "coventry city",
    "sheffield wednesday", "sheffield united",
    "bolton", "bolton wanderers",
    "ipswich",
    "sunderland",
    "middlesbrough",
    "derby", "derby county",
    "southampton", "saints",
    "wimbledon",
    "crystal palace",
    "charlton",
    "bradford",
    "watford",
    "fulham",
]

# ── BUNDESLIGA / NIEMCY ───────────────────
_BUNDESLIGA = [
    "bayern", "bayern munich", "bayern münchen", "fcb", "rekordmeister",
    "borussia dortmund", "dortmund", "bvb",
    "borussia monchengladbach", "gladbach", "fohlen",
    "schalke", "schalke 04", "knappen",
    "werder bremen", "werder", "bremen",
    "hamburger sv", "hsv", "hamburg",
    "bayer leverkusen", "leverkusen",
    "vfb stuttgart", "stuttgart",
    "eintracht frankfurt", "frankfurt",
    "kaiserslautern", "lautern",
    "1860 münchen", "1860 munich",
    "karlsruher sc",
    "vfl wolfsburg", "wolfsburg",
    "rb leipzig", "leipzig",
    "hertha berlin", "hertha",
    "fc köln", "koln", "cologne",
    "fortuna düsseldorf",
    "mönchengladbach",
]

# ── LIGUE 1 / FRANCJA ────────────────────
_LIGUE_1 = [
    "paris saint-germain", "paris saint germain", "psg",
    "marseille", "om", "olympique marseille",
    "monaco", "as monaco",
    "lyon", "olympique lyonnais", "ol",
    "bordeaux",
    "lens",
    "lille", "losc",
    "nantes", "fc nantes",
    "saint-etienne", "saint etienne", "asse",
    "rennes", "stade rennais",
    "auxerre", "aja",
    "metz",
    "nice", "ogc nice",
    "strasbourg",
    "toulouse",
    "montpellier",
    "reims",
    "gueugnon",
    "troyes",
]

# ── HOLANDIA / EREDIVISIE ─────────────────
_EREDIVISIE = [
    "ajax", "ajax amsterdam", "ajacieden",
    "psv", "psv eindhoven",
    "feyenoord", "feyenoord rotterdam",
    "vitesse",
    "az alkmaar", "az",
    "fc twente", "twente",
    "utrecht", "fc utrecht",
]

# ── SZKOCJA ───────────────────────────────
_SCOTLAND = [
    "celtic", "bhoys",
    "rangers", "gers",
    "aberdeen",
    "hearts",
    "hibernian", "hibs",
    "dundee united",
    "motherwell",
]

# ── PORTUGALIA ────────────────────────────
_PORTUGAL = [
    "benfica", "sl benfica", "aguias",
    "porto", "fc porto", "dragoes",
    "sporting", "sporting cp", "sporting lisbon", "leoes",
    "boavista",
    "braga",
]

# ── BELGIA ────────────────────────────────
_BELGIUM = [
    "anderlecht", "rsc anderlecht",
    "club brugge", "brugge",
    "standard liege", "standard",
]

# ── POLSKA ────────────────────────────────
_POLAND_CLUBS = [
    "legia", "legia warszawa",
    "lech", "lech poznan", "kolejorz",
    "wisla", "wisła", "wisla krakow",
    "gornik", "górnik", "gornik zabrze",
    "cracovia",
    "ruch chorzow", "ruch",
    "zaglebie", "zagłębie",
    "slask", "śląsk", "slask wroclaw",
    "widzew", "widzew lodz",
    "gks katowice", "gks",
    "arka gdynia", "arka",
    "jagiellonia",
]

# ── REPREZENTACJE NARODOWE ────────────────
_NATIONAL_TEAMS = [
    # Polska
    "polska", "poland", "reprezentacja polski",
    # Niemcy
    "niemcy", "niemiec", "germany", "deutschland", "mannschaft",
    # Włochy
    "włochy", "wlochy", "italia", "italy", "azzurri",
    # Francja
    "francja", "france", "les bleus",
    # Brazylia
    "brazylia", "brazil", "brasil", "selecao", "seleção",
    # Argentyna
    "argentyna", "argentina", "albiceleste",
    # Anglia
    "anglia", "england", "three lions",
    # Hiszpania
    "hiszpania", "spain", "espana", "españa", "la roja",
    # Holandia
    "holandia", "netherlands", "holland", "oranje",
    # Portugalia
    "portugalia", "portugal",
    # Chorwacja
    "chorwacja", "croatia", "hrvatska",
    # Czechy
    "czechy", "czech republic", "czechia",
    # Belgia
    "belgia", "belgium", "red devils",
    # Dania
    "dania", "denmark",
    # Szwecja
    "szwecja", "sweden",
    # Norwegia
    "norwegia", "norway",
    # Rumunia
    "rumunia", "romania",
    # Rosja
    "rosja", "russia",
    # Turcja
    "turcja", "turkey",
    # Meksyk
    "meksyk", "mexico",
    # USA
    "usa", "united states", "usmnt",
    # Japonia
    "japonia", "japan",
    # Korea
    "korea", "south korea",
    # Kamerun
    "kamerun", "cameroon",
    # Nigeria
    "nigeria",
    # Senegal
    "senegal",
    # Wybrzeże Kości Słoniowej
    "ivory coast", "cote d'ivoire",
    # Urugwaj
    "urugwaj", "uruguay",
    # Kolumbia
    "kolumbia", "colombia",
    # Chile
    "chile",
    # Szkocja
    "szkocja", "scotland",
    # Irlandia
    "irlandia", "ireland", "republic of ireland",
    # Walia
    "walia", "wales",
]

# ── PUCHARY / TURNIEJE ────────────────────
_TOURNAMENTS = [
    "world cup", "mistrzostwa swiata", "mistrzostwa świata",
    "euro", "mistrzostwa europy",
    "champions league", "liga mistrzow", "liga mistrzów",
    "copa america",
    "africa cup", "afcon",
]

# ── ŁĄCZYMY WSZYSTKO ─────────────────────
FOOTBALL_CLUBS = (
    _SERIE_A + _LA_LIGA + _PREMIER_LEAGUE + _BUNDESLIGA +
    _LIGUE_1 + _EREDIVISIE + _SCOTLAND + _PORTUGAL +
    _BELGIUM + _POLAND_CLUBS + _NATIONAL_TEAMS + _TOURNAMENTS
)

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
# ─────────────────────────────────────────
#  🔍 WYSZUKIWANIA — 4-warstwowy Flip Engine
#  🥇 WIDE BRAND   — dane rynkowe, szerokie siatki
#  🥈 CATEGORY     — trendy, kategorie
#  🥉 TARGETED     — wysokiej wartości itemy
#  🧨 CHAOS/VINTAGE — ukryte okazje
#  ⚽ FOOTBALL     — vintage koszulki
# ─────────────────────────────────────────
SEARCHES = [

    # ══════════════════════════════════════
    #  💎 TIER 0 — GRAIL SNIPER
    #  Bezpośredni snajper na rarytasy vintage
    #  Niski score wymagany — AI/grail filter decyduje
    # ══════════════════════════════════════
    {
        "name":     "Single Stitch Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=single+stitch+vintage&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["single stitch"],
        "min_price": 15,
        "layer": "grail",
        "vintage_mode": True,
        "grail_mode": True,
    },
    {
        "name":     "Band Tee Vintage Tour",
        "url":      "https://www.vinted.pl/catalog?search_text=band+tee+vintage+tour&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["band", "tee", "tour", "vintage"],
        "min_price": 15,
        "layer": "grail",
        "vintage_mode": True,
        "grail_mode": True,
    },
    {
        "name":     "Nirvana Shirt Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=nirvana+shirt+vintage&catalog[]=4&order=newest_first&currency=PLN&price_to=500",
        "category": "clothing",
        "keywords": ["nirvana", "shirt", "tee"],
        "min_price": 15,
        "layer": "grail",
        "vintage_mode": True,
        "grail_mode": True,
    },
    {
        "name":     "Metallica Shirt Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=metallica+shirt+vintage&catalog[]=4&order=newest_first&currency=PLN&price_to=500",
        "category": "clothing",
        "keywords": ["metallica", "shirt", "tee", "tour"],
        "min_price": 15,
        "layer": "grail",
        "vintage_mode": True,
        "grail_mode": True,
    },
    {
        "name":     "Harley Davidson Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=harley+davidson+vintage+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["harley", "davidson", "vintage"],
        "min_price": 15,
        "layer": "grail",
        "vintage_mode": True,
        "grail_mode": True,
    },
    {
        "name":     "Made In USA Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=made+in+usa+vintage+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["made in usa", "vintage"],
        "min_price": 15,
        "layer": "grail",
        "vintage_mode": True,
        "grail_mode": True,
    },
    {
        "name":     "Rap Tee Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=rap+tee+vintage&catalog[]=4&order=newest_first&currency=PLN&price_to=500",
        "category": "clothing",
        "keywords": ["rap", "tee", "vintage", "shirt"],
        "min_price": 15,
        "layer": "grail",
        "vintage_mode": True,
        "grail_mode": True,
    },

    # ══════════════════════════════════════
    #  🥇 LAYER 1 — WIDE BRAND (Core Data)
    # ══════════════════════════════════════
    {
        "name":     "Corteiz",
        "url":      "https://www.vinted.pl/catalog?search_text=corteiz&order=newest_first&currency=PLN&price_to=800",
        "category": "clothing",
        "keywords": ["corteiz", "crtz"],
        "min_price": 50,
        "layer": "wide_brand",
    },
    {
        "name":     "Broken Planet",
        "url":      "https://www.vinted.pl/catalog?search_text=broken+planet&order=newest_first&currency=PLN&price_to=600",
        "category": "clothing",
        "keywords": ["broken planet"],
        "min_price": 50,
        "layer": "wide_brand",
    },
    {
        "name":     "Denim Tears",
        "url":      "https://www.vinted.pl/catalog?search_text=denim+tears&order=newest_first&currency=PLN&price_to=1000",
        "category": "clothing",
        "keywords": ["denim tears"],
        "min_price": 50,
        "layer": "wide_brand",
    },
    {
        "name":     "Represent",
        "url":      "https://www.vinted.pl/catalog?search_text=represent+clothing&order=newest_first&currency=PLN&price_to=800",
        "category": "clothing",
        "keywords": ["represent"],
        "min_price": 50,
        "layer": "wide_brand",
    },
    {
        "name":     "Essentials Fear of God",
        "url":      "https://www.vinted.pl/catalog?search_text=essentials+fear+of+god&order=newest_first&currency=PLN&price_to=600",
        "category": "clothing",
        "keywords": ["essentials", "fear of god", "fog"],
        "min_price": 50,
        "layer": "wide_brand",
    },
    {
        "name":     "Stussy",
        "url":      "https://www.vinted.pl/catalog?search_text=stussy&order=newest_first&currency=PLN&price_to=500",
        "category": "clothing",
        "keywords": ["stussy"],
        "min_price": 30,
        "layer": "wide_brand",
    },
    {
        "name":     "Carhartt WIP",
        "url":      "https://www.vinted.pl/catalog?search_text=carhartt+wip&order=newest_first&currency=PLN&price_to=500",
        "category": "carhartt",
        "keywords": ["carhartt", "wip"],
        "brands":   ["carhartt"],
        "min_price": 40,
        "layer": "wide_brand",
        "carhartt_mode": True,
        "carhartt_models": CARHARTT_PREMIUM_MODELS,
        "carhartt_max_price": CARHARTT_PREMIUM_MAX,
    },
    {
        "name":     "Arc'teryx",
        "url":      "https://www.vinted.pl/catalog?search_text=arcteryx&order=newest_first&currency=PLN&price_to=1500",
        "category": "clothing",
        "keywords": ["arcteryx", "arc'teryx", "arc teryx"],
        "min_price": 100,
        "layer": "wide_brand",
    },
    {
        "name":     "Salomon",
        "url":      "https://www.vinted.pl/catalog?search_text=salomon&order=newest_first&currency=PLN&price_to=600",
        "category": "sneakers",
        "keywords": ["salomon"],
        "min_price": 50,
        "layer": "wide_brand",
    },
    {
        "name":     "New Balance",
        "url":      "https://www.vinted.pl/catalog?search_text=new+balance&catalog[]=1206&order=newest_first&currency=PLN&price_to=600",
        "category": "sneakers",
        "keywords": ["new balance"],
        "min_price": 40,
        "layer": "wide_brand",
    },
    {
        "name":     "ASICS",
        "url":      "https://www.vinted.pl/catalog?search_text=asics&catalog[]=1206&order=newest_first&currency=PLN&price_to=500",
        "category": "sneakers",
        "keywords": ["asics", "gel"],
        "min_price": 40,
        "layer": "wide_brand",
    },

    # ══════════════════════════════════════
    #  🥈 LAYER 2 — CATEGORY (Trend Capture)
    # ══════════════════════════════════════
    {
        "name":     "Cargo Pants",
        "url":      "https://www.vinted.pl/catalog?search_text=cargo+pants&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["cargo", "pants", "spodnie"],
        "min_price": 30,
        "layer": "category",
        "exclude_keywords": [
            "dziecięc", "dzieciec", "dla dzieci", "kids",
        ],
    },
    {
        "name":     "Baggy Jeans",
        "url":      "https://www.vinted.pl/catalog?search_text=baggy+jeans&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["baggy", "jeans", "wide leg"],
        "min_price": 30,
        "layer": "category",
    },
    {
        "name":     "Designer Sunglasses",
        "url":      "https://www.vinted.pl/catalog?search_text=designer+sunglasses&order=newest_first&currency=PLN&price_to=600",
        "category": "clothing",
        "keywords": ["oakley", "ray-ban", "gucci", "prada", "dior", "versace", "carrera"],
        "min_price": 40,
        "layer": "category",
    },
    {
        "name":     "Vintage Nike",
        "url":      "https://www.vinted.pl/catalog?search_text=vintage+nike&order=newest_first&currency=PLN&price_to=300",
        "category": "clothing",
        "keywords": ["nike", "vintage"],
        "min_price": 20,
        "layer": "category",
        "vintage_mode": True,
    },
    {
        "name":     "Football Jersey",
        "url":      "https://www.vinted.pl/catalog?search_text=football+jersey&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "football",
        "keywords": ["jersey", "shirt", "football"],
        "min_price": 15,
        "layer": "category",
        "football_mode": True,
    },

    # ══════════════════════════════════════
    #  🥉 LAYER 3 — TARGETED (High Value)
    # ══════════════════════════════════════
    {
        "name":     "Arc'teryx Beta",
        "url":      "https://www.vinted.pl/catalog?search_text=arcteryx+beta&order=newest_first&currency=PLN&price_to=1500",
        "category": "clothing",
        "keywords": ["arcteryx", "beta"],
        "min_price": 200,
        "layer": "targeted",
    },
    {
        "name":     "Salomon XT-6",
        "url":      "https://www.vinted.pl/catalog?search_text=salomon+xt+6&catalog[]=1206&order=newest_first&currency=PLN&price_to=600",
        "category": "sneakers",
        "keywords": ["salomon", "xt"],
        "min_price": 80,
        "layer": "targeted",
    },
    {
        "name":     "New Balance 1906R",
        # Fix 4 — dodaj model 1906r do query, nie tylko "1906" (łapało kurtki)
        "url":      "https://www.vinted.pl/catalog?search_text=new+balance+1906r&catalog[]=1206&order=newest_first&currency=PLN&price_to=500",
        "category": "sneakers",
        "keywords": ["new balance", "1906"],
        "exclude_keywords": ["jacket", "kurtka", "hoodie", "bluza", "spodnie", "joggers"],
        "min_price": 80,
        "layer": "targeted",
    },

    # ══════════════════════════════════════
    #  🧨 LAYER 4 — CHAOS / VINTAGE
    # ══════════════════════════════════════
    {
        "name":     "Vintage T-Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=vintage+t+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "clothing",
        "keywords": ["vintage", "t-shirt", "tshirt", "tee"],
        # Fix 3 — odrzuć sukienki, spodnie, bluzki które nie są t-shirtami
        "exclude_keywords": [
            "sukienka", "dress", "spodnie", "jeans", "spodenki",
            "bluzka", "sweter", "sweterek", "kardigan", "top na",
        ],
        "min_price": 15,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "Single Stitch",
        "url":      "https://www.vinted.pl/catalog?search_text=single+stitch&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["single stitch"],
        "exclude_keywords": ["sukienka", "dress", "spodnie", "jeans", "kurtka", "jacket"],
        "min_price": 15,
        "layer": "chaos",
        "vintage_mode": True,
        "no_median": True,   # mediana pokryta przez Single Stitch Vintage
    },
    {
        "name":     "Vintage Hoodie",
        "url":      "https://www.vinted.pl/catalog?search_text=vintage+hoodie&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["vintage", "hoodie", "bluza"],
        # Fix 3 — sukienki/spodnie/bluzki wiosenne nie są hoodie
        "exclude_keywords": [
            "sukienka", "dress", "spodnie", "spodenki", "jeans",
            "bluzka", "bluzki", "zestaw", "top ", "kamizelka",
            "sweterek", "sweter", "kardigan", "koszula",
        ],
        "min_price": 20,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "Retro Jacket",
        "url":      "https://www.vinted.pl/catalog?search_text=retro+jacket&catalog[]=4&order=newest_first&currency=PLN&price_to=500",
        "category": "clothing",
        "keywords": ["retro", "jacket", "kurtka"],
        # Fix 3 — sukienki i spodnie to nie kurtki
        "exclude_keywords": [
            "sukienka", "dress", "spodnie", "jeans", "spodenki",
            "bluzka", "sweter", "sweterek", "top ",
        ],
        "min_price": 30,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "Vintage Adidas",
        "url":      "https://www.vinted.pl/catalog?search_text=vintage+adidas&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["adidas", "vintage"],
        "exclude_keywords": ["sukienka", "dress"],
        "min_price": 20,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "90s Jacket",
        "url":      "https://www.vinted.pl/catalog?search_text=90s+jacket&catalog[]=4&order=newest_first&currency=PLN&price_to=500",
        "category": "clothing",
        "keywords": ["90s", "jacket", "kurtka"],
        "exclude_keywords": [
            "sukienka", "dress", "spodnie", "jeans", "kamizelka",
            "sweter", "sweterek", "kardigan", "bluzka", "top ",
        ],
        "min_price": 25,
        "layer": "chaos",
        "vintage_mode": True,
        "no_median": True,   # mediana pokryta przez Retro Jacket
    },
    {
        "name":     "Baggy Jeans Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=baggy+jeans+vintage&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "clothing",
        "keywords": ["baggy", "jeans", "vintage"],
        "exclude_keywords": ["sukienka", "dress", "bluzka", "top ", "kurtka"],
        "min_price": 20,
        "layer": "chaos",
        "vintage_mode": True,
        "no_median": True,   # mediana pokryta przez Baggy Jeans
    },
    {
        "name":     "Leather Jacket Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=leather+jacket+vintage&catalog[]=4&order=newest_first&currency=PLN&price_to=800",
        "category": "clothing",
        "keywords": ["leather", "skórzana", "kurtka", "vintage"],
        "exclude_keywords": ["sukienka", "dress", "spodnie", "bluzka", "top "],
        "min_price": 50,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "Shearling Jacket",
        "url":      "https://www.vinted.pl/catalog?search_text=shearling+jacket&catalog[]=4&order=newest_first&currency=PLN&price_to=1200",
        "category": "clothing",
        "keywords": ["shearling", "kożuch", "sheepskin"],
        "min_price": 80,
        "layer": "chaos",
        "vintage_mode": True,
    },

    # ── Part 2: CHAOS_QUERIES — varsity, college, bomber, old jeans ─────
    {
        "name":     "Varsity Jacket",
        "url":      "https://www.vinted.pl/catalog?search_text=varsity+jacket&catalog[]=4&order=newest_first&currency=PLN&price_to=600",
        "category": "clothing",
        "keywords": ["varsity", "jacket", "college", "letterman"],
        "exclude_keywords": ["sukienka", "dress", "spodnie", "bluzka"],
        "min_price": 30,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "College Jacket",
        "url":      "https://www.vinted.pl/catalog?search_text=college+jacket&catalog[]=4&order=newest_first&currency=PLN&price_to=500",
        "category": "clothing",
        "keywords": ["college", "jacket", "varsity", "letterman"],
        "exclude_keywords": ["sukienka", "dress", "spodnie"],
        "min_price": 30,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "Bomber Jacket Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=bomber+jacket+vintage&catalog[]=4&order=newest_first&currency=PLN&price_to=500",
        "category": "clothing",
        "keywords": ["bomber", "jacket", "vintage", "bomberka"],
        "exclude_keywords": ["sukienka", "dress", "spodnie", "bluzka"],
        "min_price": 30,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "Denim Jacket Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=denim+jacket+vintage&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["denim", "jacket", "vintage", "katana"],
        "exclude_keywords": ["sukienka", "dress", "spodnie"],
        "min_price": 20,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "Old Jeans Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=vintage+jeans&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "clothing",
        "keywords": ["vintage", "jeans", "denim", "501", "505"],
        "exclude_keywords": ["sukienka", "dress", "kurtka", "jacket", "bluzka"],
        "min_price": 20,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "Jeff Hamilton Jacket",
        "url":      "https://www.vinted.pl/catalog?search_text=jeff+hamilton&order=newest_first&currency=PLN",
        "category": "clothing",
        "keywords": ["jeff hamilton", "hamilton"],
        "min_price": 30,
        "layer": "grail",
        "grail_mode": True,
        "vintage_mode": True,
    },
    {
        "name":     "LL Bean Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=ll+bean+jacket&order=newest_first&currency=PLN&price_to=600",
        "category": "clothing",
        "keywords": ["ll bean", "l.l. bean", "bean"],
        "min_price": 30,
        "layer": "chaos",
        "vintage_mode": True,
    },
    {
        "name":     "Eddie Bauer Vintage",
        "url":      "https://www.vinted.pl/catalog?search_text=eddie+bauer+vintage&order=newest_first&currency=PLN&price_to=600",
        "category": "clothing",
        "keywords": ["eddie bauer", "bauer"],
        "min_price": 30,
        "layer": "chaos",
        "vintage_mode": True,
    },
    # Generic chaos — szeroka siatka na hidden gems
    {
        "name":     "Hoodie — Chaos Hunt",
        "url":      "https://www.vinted.pl/catalog?search_text=hoodie&catalog[]=4&order=newest_first&currency=PLN&price_to=200",
        "category": "clothing",
        "keywords": ["supreme", "palace", "bape", "stussy", "carhartt", "arcteryx", "represent", "corteiz"],
        "min_price": 15,
        "layer": "chaos",
        "hidden_gem_mode": True,
        "exclude_keywords": ["dziecięc", "kids", "baby", "junior"],
    },
    {
        "name":     "Jacket — Chaos Hunt",
        "url":      "https://www.vinted.pl/catalog?search_text=jacket&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "clothing",
        "keywords": ["arcteryx", "carhartt", "stone island", "cp company", "salomon", "represent", "nike", "adidas"],
        "min_price": 20,
        "layer": "chaos",
        "hidden_gem_mode": True,
        "exclude_keywords": ["dziecięc", "kids", "baby", "junior"],
    },
    {
        "name":     "Coat — Chaos Hunt",
        "url":      "https://www.vinted.pl/catalog?search_text=coat&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "clothing",
        "keywords": ["moncler", "canada goose", "arcteryx", "burberry", "stone island"],
        "min_price": 30,
        "layer": "chaos",
        "hidden_gem_mode": True,
        "exclude_keywords": ["dziecięc", "kids", "baby"],
    },

    # ══════════════════════════════════════
    #  ⚽ FOOTBALL — Vintage + Chaos
    # ══════════════════════════════════════
    {
        "name":     "Football Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=football+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "football",
        "keywords": ["shirt", "jersey", "koszulka"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
    },
    {
        "name":     "Soccer Jersey",
        "url":      "https://www.vinted.pl/catalog?search_text=soccer+jersey&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "football",
        "keywords": ["jersey", "shirt", "soccer"],
        "exclude_keywords": [
            "kurtka", "jacket", "katana", "jeans", "jeanso",
            "spodnie", "bluza", "hoodie", "coat",
        ],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
        "no_median": True,   # mediana pokryta przez Football Shirt
    },
    {
        "name":     "Koszulka Piłkarska",
        "url":      "https://www.vinted.pl/catalog?search_text=koszulka+pilkarska&catalog[]=4&order=newest_first&currency=PLN&price_to=250",
        "category": "football",
        "keywords": ["koszulka", "piłkarska", "pilkarska"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
        "no_median": True,
    },
    {
        "name":     "Vintage Football Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=vintage+football+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "football",
        "keywords": ["vintage", "shirt", "football"],
        "min_price": 20,
        "layer": "football",
        "football_mode": True,
        "vintage_mode": True,
    },
    {
        "name":     "Retro Football Jersey",
        "url":      "https://www.vinted.pl/catalog?search_text=retro+football+jersey&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "football",
        "keywords": ["retro", "jersey", "football"],
        "min_price": 20,
        "layer": "football",
        "football_mode": True,
        "vintage_mode": True,
        "no_median": True,   # mediana pokryta przez Vintage Football Shirt
    },
    {
        "name":     "90s Football Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=90s+football+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=400",
        "category": "football",
        "keywords": ["90s", "shirt", "football", "jersey"],
        "min_price": 20,
        "layer": "football",
        "football_mode": True,
        "vintage_mode": True,
        "no_median": True,
    },
    {
        "name":     "Umbro Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=umbro+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "football",
        "keywords": ["umbro", "shirt", "jersey"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
        "no_median": True,
    },
    {
        "name":     "Kappa Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=kappa+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "football",
        "keywords": ["kappa", "shirt", "jersey"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
        "no_median": True,
    },
    {
        "name":     "Lotto Football Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=lotto+football+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=250",
        "category": "football",
        "keywords": ["lotto", "shirt", "football"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
        "no_median": True,
    },
    {
        "name":     "Diadora Football Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=diadora+football+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=250",
        "category": "football",
        "keywords": ["diadora", "shirt"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
        "no_median": True,
    },
    {
        "name":     "Old Football Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=old+football+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=200",
        "category": "football",
        "keywords": ["old", "shirt", "football"],
        "min_price": 10,
        "layer": "football",
        "football_mode": True,
        "no_median": True,
    },

    # ══════════════════════════════════════
    #  🧱 LEGO — zachowane z poprzedniej wersji
    # ══════════════════════════════════════
    {
        "name":     "LEGO Star Wars — wszystkie zestawy",
        "url":      "https://www.vinted.pl/catalog?search_text=lego+star+wars&order=newest_first&currency=PLN&price_to=100",
        "category": "lego_sw",
        "keywords": ["lego", "star wars"],
        "exclude_keywords": ["polybag", "bitty", "keychain", "brelok", "kulcstart", "nyckelring", "mints", "saszetk"],
        "min_price": 15,
        "lego_sw_mode": True,
        "layer": "lego",
    },
    {
        "name":     "LEGO Star Wars — numery setów",
        "url":      "https://www.vinted.pl/catalog?search_text=lego+star+wars+75&order=newest_first&currency=PLN&price_to=100",
        "category": "lego_sw",
        "keywords": ["lego", "star wars"],
        "exclude_keywords": ["polybag", "bitty", "keychain", "brelok", "kulcstart", "nyckelring"],
        "min_price": 15,
        "lego_sw_mode": True,
        "layer": "lego",
        "no_median": True,   # mediana pokryta przez LEGO Star Wars — wszystkie zestawy
    },
    {
        "name":     "LEGO zestawy (ogólne)",
        "url":      "https://www.vinted.pl/catalog?search_text=lego&order=newest_first&currency=PLN",
        "category": "lego",
        "keywords": ["lego", "technic", "city", "ninjago", "harry potter", "creator"],
        "exclude_keywords": ["polybag", "bitty", "keychain", "brelok"],
        "brands":   ["lego"],
        "min_price": 20,
        "layer": "lego",
    },
    {
        "name":     "Funko Pop",
        "url":      "https://www.vinted.pl/catalog?search_text=funko+pop&order=newest_first&currency=PLN",
        "category": "funko",
        "keywords": ["funko", "pop", "vinyl", "figurka"],
        "exclude_keywords": ["bitty", "minis", "funko minis", "pocket pop"],
        "brands":   ["funko"],
        "min_price": 10,
        "layer": "lego",
    },
]

# ─────────────────────────────────────────
#  💾 PAMIĘĆ  (z automatycznym czyszczeniem)
# ─────────────────────────────────────────
TASTE_DISCOVERY_QUERIES = [
    "screen stars",
    "single stitch",
    "made in usa t shirt",
    "fruit of the loom usa",
    "hanes heavyweight",
    "hanes beefy",
    "jerzees vintage",
    "galt sand",
    "nutmeg vintage",
    "russell athletic vintage",
    "vintage college sweatshirt",
    "university sweatshirt vintage",
    "mlb vintage",
    "world series vintage",
    "warner bros vintage",
    "taz vintage",
    "looney tunes vintage",
    "lego star wars shirt",
    "star wars vintage shirt",
    "daytona biker",
    "bikerfest",
    "motorcycle vintage",
    "realtree vintage",
    "stussy",
    "stussy vintage",
    "polo ralph lauren eagle",
    "ralph lauren spellout",
    "polo sport vintage",
    "rrl",
    "double rl",
    "lee vintage jacket",
    "lee storm rider",
    "carhartt active jacket",
    "carhartt detroit",
    "carhartt michigan coat",
]


def make_taste_discovery_search(query: str) -> dict:
    encoded = quote_plus(query)
    return {
        "name": f"Taste Discovery: {query}",
        "url": f"https://www.vinted.pl/catalog?search_text={encoded}&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "clothing",
        "keywords": query.split(),
        "exclude_keywords": ["dziec", "kids", "baby", "junior"],
        "min_price": 1,
        "layer": "taste_discovery",
        "hidden_gem_mode": True,
        "taste_discovery": True,
        "no_median": True,
    }


SEEN_FILE      = "seen_items.json"
DATA_DIR       = os.getenv("DATA_DIR", "/data/vinted_bot")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception as e:
    print(f"[DEDUPE] data_dir_unavailable path={DATA_DIR} err={e}")
SENT_ALERTS_FILE = os.path.join(DATA_DIR, "sent_alerts.json")
SENT_ALERT_TTL_HOURS = int(os.getenv("SENT_ALERT_TTL_HOURS", "24"))
_sent_alerts_dirty = False
# FIX: 30 dni → 6h — oferty na Vinted są aktywne przez tygodnie,
# seen musi wygasać żeby bot procesował je ponownie gdy cena spadnie
SEEN_MAX_HOURS = 6
SEEN_MAX_DAYS  = SEEN_MAX_HOURS / 24

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
def _normalize_dedupe_title(title: str) -> str:
    title = str(title or "").lower()
    title = re.sub(r"[^\w\s]", " ", title, flags=re.UNICODE)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def get_item_dedupe_key(item: dict) -> str:
    item = item or {}
    for field in ("id", "item_id", "vinted_id"):
        val = item.get(field)
        if val not in (None, ""):
            return f"id:{val}"

    url = str(item.get("url") or item.get("link") or "")
    ids = re.findall(r"\d+", url)
    if ids:
        return f"url_id:{max(ids, key=len)}"

    title = _normalize_dedupe_title(item.get("title", ""))
    price = item.get("price", "")
    try:
        price = f"{float(price):.2f}"
    except Exception:
        price = str(price or "")
    seller = item.get("seller_id") or item.get("seller_name") or item.get("user_id") or ""
    return f"fallback:{title}|{price}|{seller}"


def load_sent_alerts() -> dict:
    if not os.path.exists(SENT_ALERTS_FILE):
        print("[DEDUPE_LOAD] count=0")
        return {}
    try:
        with open(SENT_ALERTS_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print("[DEDUPE_LOAD] malformed=start_empty")
            return {}
        print(f"[DEDUPE_LOAD] count={len(data)}")
        return data
    except Exception as e:
        print(f"[DEDUPE_LOAD] error={e} start_empty")
        return {}


def save_sent_alerts(force=False):
    global _sent_alerts_dirty
    if not force and not _sent_alerts_dirty:
        return
    try:
        tmp = SENT_ALERTS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(SENT_ALERTS, f, indent=2)
        os.replace(tmp, SENT_ALERTS_FILE)
        _sent_alerts_dirty = False
    except Exception as e:
        print(f"[DEDUPE_SAVE] error={e}")


def cleanup_sent_alerts(ttl_hours=SENT_ALERT_TTL_HOURS):
    global _sent_alerts_dirty
    now_ts = time.time()
    cutoff = now_ts - (ttl_hours * 3600)
    before = len(SENT_ALERTS)
    expired = [
        key for key, data in SENT_ALERTS.items()
        if float(data.get("first_sent_ts") or data.get("last_seen_ts") or 0) < cutoff
    ]
    for key in expired:
        SENT_ALERTS.pop(key, None)
    removed = before - len(SENT_ALERTS)
    if removed:
        _sent_alerts_dirty = True
    print(f"[DEDUPE_CLEANUP] removed={removed}")


def already_sent(dedupe_key: str) -> bool:
    global _sent_alerts_dirty
    if not dedupe_key:
        return False
    data = SENT_ALERTS.get(dedupe_key)
    if not data:
        return False
    cutoff = time.time() - (SENT_ALERT_TTL_HOURS * 3600)
    first_sent = float(data.get("first_sent_ts") or data.get("last_seen_ts") or 0)
    if first_sent < cutoff:
        SENT_ALERTS.pop(dedupe_key, None)
        _sent_alerts_dirty = True
        return False
    data["last_seen_ts"] = time.time()
    _sent_alerts_dirty = True
    return True


def mark_sent(item: dict, result: dict, search_name: str | None = None):
    global _sent_alerts_dirty
    item = item or {}
    result = result or {}
    key = get_item_dedupe_key(item)
    now_ts = time.time()
    meta = item.get("_search_meta") or {}
    search_name = search_name or meta.get("name") or "unknown"
    existing = SENT_ALERTS.get(key, {})
    source_searches = set(existing.get("source_searches") or [])
    engines = set(existing.get("engines") or [])
    if search_name:
        source_searches.add(search_name)
    for eng in (result.get("_merged_engines") or [result.get("engine")]):
        if eng:
            engines.add(eng)
    SENT_ALERTS[key] = {
        "title": item.get("title", ""),
        "price": item.get("price"),
        "brand": result.get("brand") or result.get("brand_detected"),
        "category": result.get("category"),
        "url": item.get("url") or item.get("link"),
        "first_sent_ts": existing.get("first_sent_ts", now_ts),
        "last_seen_ts": now_ts,
        "count": int(existing.get("count", 0)) + 1,
        "source_searches": sorted(source_searches),
        "engines": sorted(engines),
        "final_score": result.get("final_score"),
        "signal_quality_score": result.get("signal_quality_score"),
        "tier": result.get("tier") or result.get("signal_tier"),
    }
    _sent_alerts_dirty = True
    print(f"[DEDUPE_MARK] sent key={key} engine={result.get('engine')} title={str(item.get('title',''))[:60]}")
    save_sent_alerts()


ENGINE_PRIORITY = {"GRAIL": 3, "BRAND": 2, "CHAOS": 1}


def dedupe_results_by_item(results: list[dict]) -> list[dict]:
    best_by_key: dict[str, dict] = {}
    for result in results or []:
        item = result.get("item", {}) or {}
        key = get_item_dedupe_key(item)
        current = best_by_key.get(key)
        if not current:
            best_by_key[key] = result
            continue
        cur_rank = (
            ENGINE_PRIORITY.get(current.get("engine"), 0),
            float(current.get("final_score", 0) or 0),
        )
        new_rank = (
            ENGINE_PRIORITY.get(result.get("engine"), 0),
            float(result.get("final_score", 0) or 0),
        )
        if new_rank > cur_rank:
            kept, dropped = result, current
            best_by_key[key] = result
        else:
            kept, dropped = current, result
        kept["_merged_engines"] = sorted(set(
            (kept.get("_merged_engines") or [kept.get("engine")])
            + (dropped.get("_merged_engines") or [dropped.get("engine")])
        ))
        print(f"[RESULT_DEDUPE] key={key} kept={kept.get('engine')} dropped={dropped.get('engine')}")
    return list(best_by_key.values())


def filter_unsent_items(items: list[dict]) -> list[dict]:
    filtered = []
    batch_keys = set()
    for item in items or []:
        key = get_item_dedupe_key(item)
        if key in batch_keys:
            print(f"[DEDUPE_SKIP] duplicate_in_batch key={key} title={str(item.get('title',''))[:60]}")
            audit_candidate("dedupe_skip", item, block_reason="duplicate_in_batch")
            continue
        if already_sent(key):
            print(f"[DEDUPE_SKIP] already_sent key={key} title={str(item.get('title',''))[:60]}")
            audit_candidate("dedupe_skip", item, block_reason="already_sent_before_engine")
            continue
        batch_keys.add(key)
        filtered.append(item)
    return filtered


RAW_STYLE_OLD_BLANK = [
    "screen stars", "single stitch", "made in usa", "made in u.s.a",
    "made in america", "fruit of the loom", "fruit of the loom usa",
    "hanes heavyweight", "hanes heavy weight", "hanes beefy", "jerzees",
    "velva sheen", "galt sand", "nutmeg", "russell athletic", "tultex",
    "oneita", "anvil",
]
RAW_STYLE_POP_CULTURE = [
    "warner bros", "warner brothers", "looney tunes", "taz",
    "tasmanian devil", "bugs bunny", "star wars", "boba fett",
    "lego star wars", "darth vader", "yoda", "marvel", "batman",
    "spiderman", "south park", "simpsons", "pokemon", "nintendo",
]
RAW_STYLE_BIKER = [
    "harley", "harley davidson", "harley-davidson", "daytona",
    "bikerfest", "biker fest", "bike week", "sturgis", "motorcycle",
    "motorcycles", "motor cycles", "devil cycles", "flame", "flames",
    "skull", "eagle", "panther", "chopper", "rally", "dealer", "garage",
]
RAW_STYLE_SPORTS_COLLEGE = [
    "mlb", "nba", "nfl", "nhl", "ncaa", "world series", "super bowl",
    "dodgers", "raiders", "bulls", "vikings", "minnesota vikings",
    "unlv", "college", "university", "nutmeg", "athletics vs reds",
]
RAW_STYLE_STREETWEAR = [
    "stussy", "stüssy", "supreme", "palace", "bape", "xlarge", "fuct",
    "obey", "realtree", "mossy oak",
]
RAW_STYLE_RALPH_WORKWEAR = [
    "rrl", "double rl", "double ralph lauren", "polo sport", "polo jeans",
    "ralph lauren eagle", "ralph lauren spellout", "lee storm rider",
    "lee riders", "carhartt detroit", "carhartt active",
    "carhartt michigan", "duck canvas", "blanket lined", "cord collar",
    "corduroy collar",
]
RAW_STYLE_METAL = [
    "manowar", "slayer", "megadeth", "iron maiden", "pantera",
    "black sabbath", "ozzy", "judas priest", "motorhead", "motörhead",
    "sepultura",
]
RAW_STYLE_VISUAL = [
    "big print", "large print", "front print", "back print", "sleeve print",
    "graphic", "all over print", "aop", "flame sleeves", "embroidered",
    "embroidery", "spellout", "spell out",
]
RAW_STYLE_ERA_SIGNALS = [
    "70s", "80s", "90s", "00s", "1988", "1989", "1990", "1991", "1992",
    "1993", "1994", "1995", "1996", "1997", "1998", "1999", "2000",
    "2001", "2002", "2003", "2004", "2005", "2006", "2007",
]
RAW_STYLE_FAST_FASHION = {
    "zara", "h&m", "hm", "bershka", "pull&bear", "pull and bear",
    "shein", "romwe", "cider", "temu", "primark", "stradivarius",
}
RAW_STYLE_GENERIC_SPORTS = {"adidas", "nike", "puma", "reebok", "under armour"}
RAW_STYLE_NON_CLOTHING = [
    "figurka", "figura", "figure", "toy", "zabawka", "klocki",
    "lego set", "minifigure", "minifigures", "bundle of figures",
]
RAW_STYLE_CLOTHING_TERMS = [
    "t-shirt", "tshirt", "tee", "koszulka", "longsleeve", "long sleeve",
    "hoodie", "sweatshirt", "crewneck", "jacket", "kurtka", "shirt",
    "bluza", "zip hoodie", "sweater", "vest", "coat",
    "camiseta", "maglietta", "pullover", "jakna", "giacca", "veste",
    "jersey", "kit", "pants", "spodnie", "jeans", "trousers",
    "shorts", "szorty", "plaszcz",
    "bukser", "troje", "haettetroje", "jakke", "byxor", "troja",
    "paita", "huppari", "takki", "housut", "tricko", "mikina", "bunda",
    "kalhoty", "polo", "pulover", "dzseki", "nadrag", "tricou",
    "hanorac", "geaca", "pantaloni", "striuke", "marskineliai", "dzinsai",
]
RAW_STYLE_SMALL_CARHARTT_SIZES = [
    "xs", "extra small", "small", "w24", "w25", "w26", "w27", "w28",
    "w29", "24x", "25x", "26x", "27x", "28x", "29x",
]
RAW_STYLE_STRONG_SIGNAL_PREFIXES = (
    "old_blank:", "pop:", "biker:", "sports:", "streetwear:",
    "workwear:", "metal:", "visual:",
)
RAW_STYLE_WOMEN_FIT_TERMS = [
    "women", "womens", "women s", "ladies", "lady", "damska", "damskie",
    "damski", "kobieta", "dziewczeca", "baby tee", "crop", "cropped",
    "crop top", "top", "tank top", "podkoszulka", "bluzka", "bluzeczka",
    "ramiaczkach", "ramiaczka", "viscose", "wiskoza", "sukienka", "spodnica",
    "v neck", "v-neck", "fitted",
]
WOMEN_FIT_TERMS = [
    "women", "womens", "women's", "women s", "ladies", "lady", "girls", "girl",
    "female", "femme", "woman", "damska", "damskie", "damski", "kobieta",
    "kobiety", "dziewczeca", "damen", "frauen", "madchen", "vrouw",
    "vrouwen", "meisje", "dam", "dame", "pige", "kvinna", "kvinnor",
    "tjej", "kvinner", "jente", "femmes", "fille", "filles", "donna",
    "donne", "ragazza", "mujer", "mujeres", "chica", "mulher", "mulheres",
    "damske", "zeny", "noi", "no", "naisten", "nainen", "femei", "femeie",
]
FITTED_TOP_TERMS = [
    "baby tee", "babydoll", "crop", "cropped", "crop top", "top", "tank",
    "tank top", "cami", "camisole", "halter", "v-neck", "v neck", "blouse",
    "bluzka", "bluzeczka", "ramiaczkach", "ramiaczka", "na ramiaczkach",
    "sleeveless", "bez rekawow", "body", "bodysuit", "gorset", "corset",
    "fitted", "slim fit",
]
HARD_FITTED_TOP_TERMS = [
    "baby tee", "crop", "cropped", "crop top", "top", "tank", "tank top",
    "cami", "camisole", "blouse", "bluzka", "bluzeczka", "gorset", "corset",
]
KIDS_TERMS = [
    "kids", "kid", "children", "child", "junior", "youth", "boys", "girls",
    "dzieciece", "dziecieca", "dzieci", "chlopiece", "dziewczece",
    "kinder", "enfant", "bambino", "bambina", "nino", "nina",
]
MENS_UNISEX_TERMS = [
    "men", "mens", "men's", "men s", "male", "meski", "meska", "unisex",
    "herren", "homme", "uomo", "hombre", "panske", "heren", "mies", "miesten",
]
OVERSIZE_TERMS = ["oversize", "oversized", "boxy", "baggy", "loose fit", "relaxed fit"]
RAW_STYLE_SMALL_SIZE_TERMS = [
    "xs", "extra small", "small", "34", "36", "w24", "w25", "w26", "w27", "w28",
]
RAW_STYLE_MENS_EXCEPTION_TERMS = [
    "men", "mens", "men s", "unisex", "oversize", "oversized", "boxy", "xl", "xxl", "2xl",
    "herren", "homme", "uomo", "hombre", "panske", "heren",
]
RAW_STYLE_BASIC_TERMS = [
    "blank", "plain", "basic", "solid color", "no print", "zwykly", "zwykły",
    "gladki", "gładki", "bez nadruku",
]
RAW_STYLE_CONTEXT_TERMS = [
    "made in usa", "made in u s a", "single stitch", "80s", "90s", "00s",
    "college", "university", "team", "league", "player", "mlb", "nba", "nfl",
    "nhl", "ncaa", "dodgers", "raiders", "bulls", "vikings", "rangers",
    "world series", "super bowl", "final four", "tour", "band", "movie",
    "promo", "race", "racing", "nascar", "event", "daytona", "sturgis",
    "bike week", "bikerfest", "official", "licensed", "copyright",
    "big front print", "front print", "back print", "double sided", "spellout",
    "spell out", "strong graphic", "big graphic", "large print",
]
RAW_STYLE_POP_VALIDATION_TERMS = [
    "warner bros", "warner brothers", "official", "licensed", "copyright",
    "made in usa", "single stitch", "80s", "90s", "00s", "big graphic",
    "big print", "large print", "front print", "back print", "double sided",
    "movie promo", "old tag", "sweatshirt", "crewneck", "taz", "motorcycle",
]
RAW_STYLE_SPORTS_ITEM_TERMS = [
    "jersey", "sweatshirt", "crewneck", "hoodie", "strong graphic", "big graphic",
    "large print", "tee", "t-shirt", "tshirt", "koszulka",
]
RAW_STYLE_VISUAL_CONTEXT_TERMS = [
    "harley", "taz", "motorcycle", "nascar", "racing", "band", "tour", "movie",
    "promo", "college", "university", "mlb", "nba", "nfl", "nhl", "ncaa",
    "made in usa", "single stitch", "screen stars", "nutmeg", "big print",
    "back print", "double sided", "all over print", "aop",
]
RAW_STYLE_GENERIC_VISUAL_TERMS = [
    "graphic", "print", "skate", "grunge", "y2k", "swag", "streetwear", "vintage",
]
RAW_STYLE_KNOWN_STRONG_MOTIFS = [
    "harley skull", "skull", "flame", "flames", "taz motorcycle", "motorcycle",
    "nascar", "petty", "driver", "ramones", "metallica", "manowar", "slayer",
    "movie promo", "warner bros", "daytona", "sturgis",
]
WEAK_VINTAGE_BRANDS = {"vintage", "japan style", "retro", "no brand", "handmade", "unknown"}
WEAK_DESCRIPTOR_TERMS = [
    "vintage", "retro", "y2k", "japanstyle", "japan style", "avant garde",
    "avantgarde", "swag", "streetwear", "archive", "rare", "unique",
    "oldschool", "old skool",
]
WEAK_NOVELTY_BRANDS = ["gas monkey", "gas monkey garage", "american flag", "japan style"]

RAW_STYLE_CYCLE_CANDIDATES: dict[str, dict] = {}
RAW_STYLE_STATS = {
    "checked": 0,
    "candidates": 0,
    "sent": 0,
    "blocked": 0,
    "dedupe_skipped": 0,
}
AGE_GATE_STATS = {
    "raw_checked": 0,
    "blocked_stale_visible_age": 0,
    "blocked_unknown_age": 0,
    "blocked_old_blank_no_context": 0,
    "blocked_weak_brand": 0,
    "blocked_women_fitted": 0,
    "sent": 0,
}
PRESEND_STATS = {
    "checked": 0,
    "passed": 0,
    "blocked": 0,
    "blocked_by_reason": {},
    "by_source": {},
}
AGE_SOURCE_STATS = {
    "created_at_ts": 0,
    "visible_text": 0,
    "synthetic_rank": 0,
    "unknown": 0,
    "synthetic_sent": 0,
    "visible_sent": 0,
}
DETAIL_AGE_STATS = {
    "checked": 0,
    "parsed": 0,
    "blocked_stale": 0,
    "blocked_unverified": 0,
    "allowed_grail_unverified": 0,
}
SAFEGUARD_STATS = {
    "retried": 0,
    "added": 0,
    "passed_presend": 0,
    "blocked_presend": 0,
    "sent": 0,
    "limit_skipped": 0,
}
QUERY_COVERAGE: dict[str, dict] = {}

AUDIT_CURRENT_CYCLE = 0
AUDIT_LINES_THIS_CYCLE = 0
AUDIT_WRITE_ERROR_LOGGED = False
AUDIT_WATCH_NEEDLES = [x.strip().lower() for x in AUDIT_WATCH_TITLES.split(",") if x.strip()]
AUDIT_STATS = {
    "seen": 0,
    "raw_checked": 0,
    "raw_candidates": 0,
    "raw_sent": 0,
    "main_candidates": 0,
    "main_sent": 0,
    "blocked": 0,
    "dedupe_skipped": 0,
    "top_block_reasons": {},
    "top_queries": {},
}
AUDIT_TOP_BLOCKED: list[dict] = []
AUDIT_TOP_NOT_SENT: list[dict] = []
BOT_POSITIVE_KNOWLEDGE_BASE: dict = {}
FRESH_DISCOVERY_QUERY_POOL: list[str] = []
TARGET_MARKERS: set[str] = set()
FRESH_DISCOVERY_STATE_FILE = os.path.join(DATA_DIR, "fresh_discovery_state.json")
FRESH_DISCOVERY_STATS = {
    "enabled": FRESH_DISCOVERY_ENABLED,
    "pool_total": 0,
    "queries_run": 0,
    "seen": 0,
    "candidates": 0,
    "sent": 0,
    "blocked": 0,
    "top_block_reasons": {},
}
TARGET_AUDIT_STATS = {
    "target_seen": 0,
    "target_candidates": 0,
    "target_sent": 0,
    "target_blocked": 0,
    "seen_logs": 0,
    "blocked_logs": 0,
    "top_target_block_reasons": {},
}
VERBOSE_LOG_STATS = {
    "printed": 0,
    "suppressed": {
        "age_source": 0,
        "size_parse": 0,
        "safeguard_blocks": 0,
        "raw_style_blocks": 0,
        "audit_seen": 0,
    },
}
RAW_STYLE_BLOCK_STATS = {
    "total": 0,
    "by_reason": {},
    "top_blocked": [],
}
LAST_TELEGRAM_STATUS = None
LAST_TELEGRAM_ERROR = ""


def verbose_item_log(kind: str, message: str, force: bool = False) -> bool:
    if force:
        print(message)
        return True
    if not VERBOSE_ITEM_DEBUG:
        suppressed = VERBOSE_LOG_STATS["suppressed"]
        suppressed[kind] = suppressed.get(kind, 0) + 1
        return False
    if MAX_VERBOSE_LOGS_PER_CYCLE > 0 and VERBOSE_LOG_STATS["printed"] < MAX_VERBOSE_LOGS_PER_CYCLE:
        print(message)
        VERBOSE_LOG_STATS["printed"] += 1
        return True
    suppressed = VERBOSE_LOG_STATS["suppressed"]
    suppressed[kind] = suppressed.get(kind, 0) + 1
    return False


def suppress_verbose_log(kind: str, count: int = 1):
    suppressed = VERBOSE_LOG_STATS["suppressed"]
    suppressed[kind] = suppressed.get(kind, 0) + int(count or 1)


def record_raw_style_block(reason: str, score, title: str):
    reason = reason or "unknown"
    try:
        score_f = float(score or 0)
    except Exception:
        score_f = 0.0
    RAW_STYLE_BLOCK_STATS["total"] += 1
    by_reason = RAW_STYLE_BLOCK_STATS["by_reason"]
    by_reason[reason] = by_reason.get(reason, 0) + 1
    top = RAW_STYLE_BLOCK_STATS["top_blocked"]
    top.append({"score": round(score_f, 1), "reason": reason, "title": str(title or "")[:70]})
    top.sort(key=lambda x: x.get("score", 0), reverse=True)
    del top[10:]


def log_send_age_source(result: dict):
    source = (result or {}).get("_visible_age_source") or (result or {}).get("age_source")
    if source == "synthetic_rank":
        AGE_SOURCE_STATS["synthetic_sent"] += 1
    elif source in {"visible_text", "created_at_ts", "detail_visible_text"}:
        AGE_SOURCE_STATS["visible_sent"] += 1


def record_age_source_resolution(source: str):
    if source == "created_at_ts":
        AGE_SOURCE_STATS["created_at_ts"] = AGE_SOURCE_STATS.get("created_at_ts", 0) + 1
    elif source == "visible_text":
        AGE_SOURCE_STATS["visible_text"] += 1
    elif source == "detail_visible_text":
        AGE_SOURCE_STATS["visible_text"] += 1
    elif source == "synthetic_rank":
        AGE_SOURCE_STATS["synthetic_rank"] += 1
    else:
        AGE_SOURCE_STATS["unknown"] += 1


def raw_normalize_text(text: str) -> str:
    text_l = str(text or "").lower()
    text_l = text_l.replace("ü", "u").replace("ó", "o").replace("ł", "l")
    text_l = unicodedata.normalize("NFKD", text_l)
    text_l = "".join(ch for ch in text_l if not unicodedata.combining(ch))
    text_l = text_l.replace("&", " and ")
    text_l = re.sub(r"[^a-z0-9]+", " ", text_l)
    return re.sub(r"\s+", " ", text_l).strip()


def raw_contains_phrase(text: str, phrase: str) -> bool:
    text_n = raw_normalize_text(text)
    phrase_n = raw_normalize_text(phrase)
    if not text_n or not phrase_n:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase_n)}(?![a-z0-9])", text_n) is not None


def raw_contains_any_phrase(text: str, phrases: list[str]) -> bool:
    return any(raw_contains_phrase(text, phrase) for phrase in phrases)


def raw_contains_exact_token(text: str, token: str) -> bool:
    return raw_contains_phrase(text, token)


def _raw_hits(text: str, phrases: list[str]) -> list[str]:
    return [phrase for phrase in phrases if raw_contains_phrase(text, phrase)]


CURATED_FRESH_DISCOVERY_SEED = [
    "single stitch vintage",
    "made in usa vintage",
    "90s vintage t shirt",
    "vintage graphic tee",
    "vintage disney tee",
    "disney cruise line",
    "warner bros vintage",
    "looney tunes vintage",
    "space jam vintage",
    "nasa vintage",
    "vintage nasa shirt",
    "nutmeg vintage",
    "vintage nba nutmeg",
    "orlando magic vintage",
    "jerzees vintage",
    "hanes beefy",
    "fruit of the loom usa",
    "screen stars vintage",
    "band tee vintage",
    "tour tee vintage",
    "rap tee vintage",
    "metal longsleeve vintage",
    "harley davidson vintage",
    "daytona bike week",
    "sturgis vintage",
    "nascar vintage",
    "racing vintage",
    "carhartt detroit",
    "carhartt santa fe",
    "workwear vintage",
    "stussy vintage tee",
    "ed hardy vintage",
    "affliction vintage",
    "archive graphic tee",
    "designer archive",
    "ralph lauren vintage knit",
    "polo sport vintage",
]


def _knowledge_add_unique(target: list[str], value):
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _knowledge_add_unique(target, item)
        return
    text = raw_normalize_text(value)
    if text and text not in target:
        target.append(text)


def _negative_discovery_terms() -> set[str]:
    terms: set[str] = set()
    for name in (
        "GLOBAL_EXCLUDE", "BLOCKED_BRANDS", "RAW_STYLE_FAST_FASHION",
        "RAW_STYLE_NON_CLOTHING", "WOMEN_FIT_TERMS", "FITTED_TOP_TERMS",
        "KIDS_TERMS", "WEAK_DESCRIPTOR_TERMS", "WEAK_NOVELTY_BRANDS",
    ):
        val = globals().get(name, [])
        for term in (val if isinstance(val, (list, tuple, set)) else []):
            norm = raw_normalize_text(term)
            if norm:
                terms.add(norm)
    return terms


def build_bot_positive_knowledge_base() -> dict:
    base = {
        "search_profile_terms": [],
        "raw_style_terms": [],
        "authenticity_terms": [],
        "motif_terms": [],
        "brand_terms": [],
        "category_terms": [],
        "manual_seed_terms": [],
    }
    for name, profile in (SEARCH_PROFILES or {}).items():
        _knowledge_add_unique(base["search_profile_terms"], name)
        _knowledge_add_unique(base["search_profile_terms"], profile.get("required_phrases") or [])
        _knowledge_add_unique(base["category_terms"], profile.get("allowed_types") or [])
    for search in SEARCHES:
        if search.get("layer") in {"grail", "targeted", "taste_discovery"} or search.get("grail_mode"):
            _knowledge_add_unique(base["search_profile_terms"], search.get("name"))
            _knowledge_add_unique(base["brand_terms"], search.get("keywords") or [])
    _knowledge_add_unique(base["manual_seed_terms"], TASTE_DISCOVERY_QUERIES)
    _knowledge_add_unique(base["manual_seed_terms"], CURATED_FRESH_DISCOVERY_SEED)
    for name in (
        "RAW_STYLE_CONTEXT_TERMS", "RAW_STYLE_POP_VALIDATION_TERMS",
        "RAW_STYLE_VISUAL_CONTEXT_TERMS", "RAW_STYLE_KNOWN_STRONG_MOTIFS",
        "RAW_STYLE_OLD_BLANK", "RAW_STYLE_POP_CULTURE", "RAW_STYLE_BIKER",
        "RAW_STYLE_SPORTS_COLLEGE", "RAW_STYLE_STREETWEAR",
        "RAW_STYLE_RALPH_WORKWEAR", "RAW_STYLE_METAL", "RAW_STYLE_ERA_SIGNALS",
    ):
        _knowledge_add_unique(base["raw_style_terms"], globals().get(name, []))
    engine_mod = sys.modules.get("engine")
    if engine_mod:
        for name in ("AUTHENTICITY_SIGNALS", "DESIRABLE_VINTAGE"):
            _knowledge_add_unique(base["authenticity_terms"], getattr(engine_mod, name, []))
        for name in (
            "DESIRABLE_OUTDOOR", "DESIRABLE_NIKE", "DESIRABLE_ADIDAS",
            "DESIRABLE_DENIM", "DESIRABLE_HARLEY", "DESIRABLE_DESIGNER",
            "DESIRABLE_CARHARTT", "RALPH_LAUREN_DESIRABLE_SIGNALS",
            "LEE_DESIRABLE_SIGNALS",
        ):
            _knowledge_add_unique(base["motif_terms"], getattr(engine_mod, name, []))
    _knowledge_add_unique(base["motif_terms"], [
        "vintage t shirt", "single stitch", "made in usa", "old blanks",
        "screen stars", "hanes beefy", "fruit of the loom usa", "jerzees",
        "band tee", "tour tee", "rap tee", "metal longsleeve",
        "warner bros", "looney tunes", "space jam", "disney", "nasa",
        "nutmeg", "nba", "nascar", "harley", "daytona", "sturgis",
        "carhartt detroit", "carhartt santa fe", "archive graphic tee",
        "designer archive", "stussy", "ed hardy", "affliction", "polo sport",
    ])
    negatives = _negative_discovery_terms()
    for key, values in list(base.items()):
        filtered = []
        for term in values:
            if term in negatives:
                continue
            if any(term == neg or raw_contains_phrase(term, neg) for neg in negatives if len(neg) > 4):
                continue
            if term not in filtered:
                filtered.append(term)
        base[key] = filtered
    examples = []
    for key in ("authenticity_terms", "motif_terms", "manual_seed_terms"):
        examples.extend(base.get(key, [])[:4])
    print(f"[BOT_KNOWLEDGE_BASE_BUILT] "
          f"search_profile_terms={len(base['search_profile_terms'])} "
          f"raw_style_terms={len(base['raw_style_terms'])} "
          f"authenticity_terms={len(base['authenticity_terms'])} "
          f"motif_terms={len(base['motif_terms'])} "
          f"brand_terms={len(base['brand_terms'])} "
          f"category_terms={len(base['category_terms'])} examples={examples[:8]}")
    return base


WEAK_DISCOVERY_QUERY_WORDS = {
    "tee", "shirt", "t shirt", "tshirt", "koszulka", "vintage",
    "graphic", "streetwear", "archive", "style", "y2k", "rare",
}

STRONG_SINGLE_DISCOVERY_QUERIES = {
    "rrl",
}


def is_discovery_safe_query(query: str) -> bool:
    q = raw_normalize_text(query)
    if not q:
        return False
    if q in STRONG_SINGLE_DISCOVERY_QUERIES:
        return True
    tokens = q.split()
    if len(tokens) == 1 and q in WEAK_DISCOVERY_QUERY_WORDS:
        return False
    if q in WEAK_DISCOVERY_QUERY_WORDS:
        return False
    negatives = _negative_discovery_terms()
    if any(raw_contains_phrase(q, neg) for neg in negatives):
        return False
    context_terms = [
        "vintage", "single stitch", "made in usa", "screen stars", "hanes",
        "fruit of the loom", "jerzees", "nutmeg", "archive", "designer",
        "workwear", "carhartt", "detroit", "santa fe", "harley", "daytona",
        "sturgis", "warner", "looney", "disney", "space jam", "nasa",
        "nba", "nascar", "tour", "band", "rap", "metal", "polo sport",
        "stussy", "ed hardy", "affliction", "rrl", "double rl",
    ]
    return any(raw_contains_phrase(q, term) for term in context_terms) and len(q) >= 7


def build_fresh_discovery_queries_from_knowledge(base: dict) -> list[str]:
    candidates: list[str] = []
    manual_added: set[str] = set()
    rejected_too_generic = 0
    rejected_negative = 0

    def add(query: str, source: str = "code"):
        nonlocal rejected_too_generic, rejected_negative
        q = raw_normalize_text(query)
        if not q:
            return
        if q in WEAK_DISCOVERY_QUERY_WORDS or (len(q.split()) == 1 and q in WEAK_DISCOVERY_QUERY_WORDS):
            rejected_too_generic += 1
            return
        if any(raw_contains_phrase(q, neg) for neg in _negative_discovery_terms()):
            rejected_negative += 1
            return
        if not is_discovery_safe_query(q):
            rejected_too_generic += 1
            return
        if q not in candidates:
            candidates.append(q)
            if source == "manual":
                manual_added.add(q)

    for query in CURATED_FRESH_DISCOVERY_SEED:
        add(query, source="manual")
    for query in base.get("manual_seed_terms", []):
        add(query, source="manual")
    for term in base.get("authenticity_terms", []) + base.get("raw_style_terms", []) + base.get("motif_terms", []):
        t = raw_normalize_text(term)
        if not t:
            continue
        if raw_contains_phrase(t, "single stitch") or raw_contains_phrase(t, "made in usa"):
            add(f"{t} vintage")
        elif raw_contains_phrase(t, "screen stars") or raw_contains_phrase(t, "hanes beefy"):
            add(f"{t} vintage")
        elif raw_contains_phrase(t, "fruit of the loom"):
            add("fruit of the loom usa")
        elif raw_contains_phrase(t, "carhartt") or raw_contains_phrase(t, "detroit") or raw_contains_phrase(t, "santa fe"):
            add(t if "carhartt" in t else f"carhartt {t}")
        elif raw_contains_phrase(t, "warner") or raw_contains_phrase(t, "looney") or raw_contains_phrase(t, "disney"):
            add(f"{t} vintage")
        elif raw_contains_phrase(t, "nba") or raw_contains_phrase(t, "nutmeg") or raw_contains_phrase(t, "nascar"):
            add(f"{t} vintage")
        elif raw_contains_phrase(t, "archive") or raw_contains_phrase(t, "designer"):
            add(t)
    for term in base.get("search_profile_terms", []) + base.get("brand_terms", []):
        t = raw_normalize_text(term)
        if not t:
            continue
        if raw_contains_any_phrase(t, ["single stitch", "made in usa", "screen stars", "hanes beefy", "fruit of the loom usa"]):
            add(t)
        elif raw_contains_any_phrase(t, ["harley", "daytona", "sturgis", "nascar", "warner bros", "looney tunes", "space jam", "nutmeg"]):
            add(f"{t} vintage")
        elif raw_contains_any_phrase(t, ["carhartt", "detroit", "santa fe", "polo sport", "designer archive", "archive graphic"]):
            add(t)
    print(f"[FRESH_DISCOVERY_POOL_BUILT] total={len(candidates)} "
          f"from_existing_code={max(0, len(candidates) - len(manual_added))} "
          f"from_manual_seed={len(manual_added)} "
          f"rejected_too_generic={rejected_too_generic} rejected_negative={rejected_negative} "
          f"examples={candidates[:10]}")
    return candidates


def build_target_markers_from_knowledge(base: dict) -> set[str]:
    markers: set[str] = set()
    negatives = _negative_discovery_terms()
    for key in ("search_profile_terms", "raw_style_terms", "authenticity_terms", "motif_terms", "brand_terms", "manual_seed_terms"):
        for term in base.get(key, []):
            t = raw_normalize_text(term)
            if len(t) >= 3 and t not in negatives and t not in WEAK_DISCOVERY_QUERY_WORDS:
                markers.add(t)
    print(f"[TARGET_MARKERS_BUILT] total={len(markers)} examples={sorted(markers)[:12]}")
    return markers


def make_fresh_discovery_search(query: str) -> dict:
    encoded = quote_plus(query)
    return {
        "name": f"Fresh Discovery: {query}",
        "url": f"https://www.vinted.pl/catalog?search_text={encoded}&catalog[]=4&order=newest_first&currency=PLN&price_to=450",
        "category": "clothing",
        "keywords": query.split(),
        "exclude_keywords": ["dziec", "kids", "baby", "junior"],
        "min_price": 1,
        "layer": "fresh_discovery",
        "hidden_gem_mode": True,
        "fresh_discovery": True,
        "core_search": True,
        "no_median": True,
    }


def _fresh_discovery_load_index() -> int:
    try:
        with open(FRESH_DISCOVERY_STATE_FILE, "r", encoding="utf-8") as fh:
            return int((json.load(fh) or {}).get("index", 0))
    except Exception:
        return 0


def _fresh_discovery_save_index(index: int):
    try:
        os.makedirs(os.path.dirname(FRESH_DISCOVERY_STATE_FILE), exist_ok=True)
        tmp = FRESH_DISCOVERY_STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"index": int(index), "updated_ts": time.time()}, fh)
        os.replace(tmp, FRESH_DISCOVERY_STATE_FILE)
    except Exception as e:
        print(f"[FRESH_DISCOVERY_STATE_ERROR] error={e}")


def select_fresh_discovery_queries() -> list[str]:
    if not FRESH_DISCOVERY_ENABLED or not FRESH_DISCOVERY_QUERY_POOL:
        return []
    count = min(FRESH_DISCOVERY_PER_CYCLE, len(FRESH_DISCOVERY_QUERY_POOL))
    if count <= 0:
        return []
    index_before = _fresh_discovery_load_index() % len(FRESH_DISCOVERY_QUERY_POOL)
    selected = [
        FRESH_DISCOVERY_QUERY_POOL[(index_before + offset) % len(FRESH_DISCOVERY_QUERY_POOL)]
        for offset in range(count)
    ]
    index_after = (index_before + count) % len(FRESH_DISCOVERY_QUERY_POOL)
    _fresh_discovery_save_index(index_after)
    print(f"[FRESH_DISCOVERY_ROTATION] pool_total={len(FRESH_DISCOVERY_QUERY_POOL)} "
          f"index_before={index_before} selected={selected} index_after={index_after}")
    return selected


def reset_fresh_discovery_cycle():
    FRESH_DISCOVERY_STATS.update({
        "enabled": FRESH_DISCOVERY_ENABLED,
        "pool_total": len(FRESH_DISCOVERY_QUERY_POOL),
        "queries_run": 0,
        "seen": 0,
        "candidates": 0,
        "sent": 0,
        "blocked": 0,
        "top_block_reasons": {},
    })
    TARGET_AUDIT_STATS.update({
        "target_seen": 0,
        "target_candidates": 0,
        "target_sent": 0,
        "target_blocked": 0,
        "seen_logs": 0,
        "blocked_logs": 0,
        "top_target_block_reasons": {},
    })


def _target_marker_hits(item: dict, result: dict | None = None) -> list[str]:
    if not TARGET_MARKERS:
        return []
    result = result or {}
    text = " ".join(str(x or "") for x in (
        item.get("title"), item.get("brand"), item.get("description"),
        item.get("category"), result.get("category"), result.get("brand"),
        result.get("brand_detected"),
    ))
    hits = [marker for marker in sorted(TARGET_MARKERS) if raw_contains_phrase(text, marker)]
    return hits[:8]


def _target_audit_event(event: dict):
    markers = event.get("matched_markers") or []
    if not markers:
        return
    stage = event.get("stage")
    query = event.get("query")
    title = str(event.get("title") or "")[:70]
    if stage == "seen":
        TARGET_AUDIT_STATS["target_seen"] += 1
        if TARGET_AUDIT_STATS["seen_logs"] < 20:
            TARGET_AUDIT_STATS["seen_logs"] += 1
            print(f"[TARGET_SEEN] query={query} title={title} brand={event.get('brand')} "
                  f"price={event.get('price')} size={event.get('size')} "
                  f"age_source={event.get('age_source')} age_min={event.get('age')} "
                  f"matched_markers={markers[:5]}")
    elif stage == "candidate":
        TARGET_AUDIT_STATS["target_candidates"] += 1
    elif stage == "sent":
        TARGET_AUDIT_STATS["target_sent"] += 1
        print(f"[TARGET_SENT] query={query} title={title} source={event.get('alert_type') or event.get('engine')} "
              f"score={event.get('score')} matched_markers={markers[:5]}")
    elif stage in ("blocked", "quality_block", "final_skip", "rank_not_selected", "dedupe_skip"):
        TARGET_AUDIT_STATS["target_blocked"] += 1
        reason = event.get("block_reason") or stage
        reasons = TARGET_AUDIT_STATS["top_target_block_reasons"]
        reasons[reason] = reasons.get(reason, 0) + 1
        if TARGET_AUDIT_STATS["blocked_logs"] < 15:
            TARGET_AUDIT_STATS["blocked_logs"] += 1
            print(f"[TARGET_BLOCKED] query={query} title={title} score={event.get('score')} "
                  f"reason={reason} matched_markers={markers[:5]}")


def _fresh_discovery_audit_event(event: dict):
    if not str(event.get("query") or "").startswith("Fresh Discovery:"):
        return
    stage = event.get("stage")
    if stage == "seen":
        FRESH_DISCOVERY_STATS["seen"] += 1
    elif stage == "candidate":
        FRESH_DISCOVERY_STATS["candidates"] += 1
    elif stage == "sent":
        FRESH_DISCOVERY_STATS["sent"] += 1
    elif stage in ("blocked", "quality_block", "final_skip", "rank_not_selected", "dedupe_skip"):
        FRESH_DISCOVERY_STATS["blocked"] += 1
        reason = event.get("block_reason") or stage
        reasons = FRESH_DISCOVERY_STATS["top_block_reasons"]
        reasons[reason] = reasons.get(reason, 0) + 1


def print_fresh_discovery_summary():
    print(f"[FRESH_DISCOVERY_SUMMARY] enabled={FRESH_DISCOVERY_STATS['enabled']} "
          f"pool_total={FRESH_DISCOVERY_STATS['pool_total']} queries_run={FRESH_DISCOVERY_STATS['queries_run']} "
          f"seen={FRESH_DISCOVERY_STATS['seen']} candidates={FRESH_DISCOVERY_STATS['candidates']} "
          f"sent={FRESH_DISCOVERY_STATS['sent']} blocked={FRESH_DISCOVERY_STATS['blocked']} "
          f"top_block_reasons={FRESH_DISCOVERY_STATS['top_block_reasons']}")
    print(f"[TARGET_AUDIT_SUMMARY] target_seen={TARGET_AUDIT_STATS['target_seen']} "
          f"target_candidates={TARGET_AUDIT_STATS['target_candidates']} "
          f"target_sent={TARGET_AUDIT_STATS['target_sent']} "
          f"target_blocked={TARGET_AUDIT_STATS['target_blocked']} "
          f"top_target_block_reasons={TARGET_AUDIT_STATS['top_target_block_reasons']}")


def _raw_item_age(item: dict) -> int:
    age_info = get_item_age_info(item)
    age = age_info.get("minutes")
    try:
        return int(age)
    except Exception:
        return 9999


def _raw_is_clothing(text: str, item: dict) -> bool:
    category = str(item.get("category") or "").lower()
    return bool(
        category in {"clothing", "tshirt", "shirt", "hoodie", "jacket", "coat"}
        or raw_contains_any_phrase(text, RAW_STYLE_CLOTHING_TERMS)
    )


def _raw_size_bucket(text: str, item: dict) -> str:
    size_raw = raw_normalize_text(item.get("size") or "")
    if size_raw:
        if re.search(r"(?<![a-z0-9])(xxl|2xl|xl|x large|extra large|large|l|m l)(?![a-z0-9])", size_raw):
            if DEBUG_ALERTS:
                verbose_item_log("size_parse", "[SIZE_PARSE] source=item_size bucket=large")
            return "large"
        if re.search(r"(?<![a-z0-9])(m|medium)(?![a-z0-9])", size_raw):
            if DEBUG_ALERTS:
                verbose_item_log("size_parse", "[SIZE_PARSE] source=item_size bucket=medium")
            return "medium"
        if re.search(r"(?<![a-z0-9])(w3[0-6]|3[0-6]x3[0-4])(?![a-z0-9])", size_raw):
            if DEBUG_ALERTS:
                verbose_item_log("size_parse", "[SIZE_PARSE] source=item_size bucket=large")
            return "large"
    title_n = raw_normalize_text(text)
    explicit = re.search(
        r"(?<![a-z0-9])(?:size|rozmiar|r|vel|koko|str)\s*\.?\s*(xxl|2xl|xl|l|m|w3[0-6]|3[0-6]x3[0-4])(?![a-z0-9])",
        title_n,
    )
    waist = re.search(r"(?<![a-z0-9])(w3[0-6]|3[0-6]x3[0-4])(?![a-z0-9])", title_n)
    hit = explicit.group(1) if explicit else (waist.group(1) if waist else "")
    if hit in {"xxl", "2xl", "xl", "l"} or hit.startswith("w3") or "x" in hit:
        if DEBUG_ALERTS:
            verbose_item_log("size_parse", "[SIZE_PARSE] source=title_explicit bucket=large")
        return "large"
    if hit == "m":
        if DEBUG_ALERTS:
            verbose_item_log("size_parse", "[SIZE_PARSE] source=title_explicit bucket=medium")
        return "medium"
    if DEBUG_ALERTS:
        verbose_item_log("size_parse", "[SIZE_PARSE] source=none bucket=unknown")
    return ""


def _raw_real_signal_count(signals: list[str]) -> int:
    return sum(1 for sig in signals if str(sig).startswith(RAW_STYLE_STRONG_SIGNAL_PREFIXES))


def _raw_presend_text(item: dict) -> str:
    return " ".join(str(item.get(k) or "") for k in ("title", "brand", "description", "category", "size"))


def _raw_has_small_size(item: dict, text: str) -> bool:
    size_only = raw_normalize_text(item.get("size") or "")
    if re.fullmatch(r"(xs|extra small|small|s|34|36|w24|w25|w26|w27|w28)", size_only or ""):
        return True
    size_text = raw_normalize_text(f"{item.get('size') or ''} {text}")
    return re.search(
        r"(?<![a-z0-9])(?:size|rozmiar|r|w)\s*(xs|s|34|36|24|25|26|27|28)(?![a-z0-9])",
        size_text,
    ) is not None or re.search(
        r"(?<![a-z0-9])(w24|w25|w26|w27|w28|extra small|small)(?![a-z0-9])",
        size_text,
    ) is not None


def _raw_has_good_size(item: dict, text: str) -> bool:
    return _raw_size_bucket(text, item) in ("medium", "large")


def _raw_exact_year_hit(text: str) -> bool:
    return re.search(r"(?<!\d)(19[8-9]\d|200[0-7])(?!\d)", raw_normalize_text(text)) is not None


def _parse_age_text_minutes(text: str) -> int | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    t = raw_normalize_text(raw)
    if not t:
        return None
    patterns = [
        (r"(?:dodane\s*)?(\d+)\s*(?:min|minut|minute|minutes?)", 1),
        (r"(\d+)\s*(?:h|godz|godzin|hour|hours)", 60),
        (r"(\d+)\s*(?:dni|dzien|day|days)", 1440),
        (r"(\d+)\s*(?:tyg|tygodn|week|weeks)", 10080),
        (r"(\d+)\s*(?:mies|miesi|miesiac|month|months)", 43200),
    ]
    for pattern, mult in patterns:
        m = re.search(pattern, t)
        if m:
            return int(m.group(1)) * mult
    if re.search(r"\b(?:godzine|godzina|hour|an hour)\b", t):
        return 60
    if re.search(r"\b(?:wczoraj|dzien|yesterday|a day)\b", t):
        return 1440
    if re.search(r"\b(?:tygodnia|tydzien|week|a week)\b", t):
        return 10080
    if re.search(r"\b(?:mies|miesi|miesiac|month|a month)\b", t):
        return 43200
    return None


def _extract_detail_age_text(html: str) -> tuple[int | None, str | None]:
    try:
        text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    except Exception:
        text = str(html or "")
    if not text:
        return None, None
    candidates: list[str] = []
    patterns = [
        r"(Dodane\s+(?:\d+\s*)?(?:min\.?|minut(?:y)?|godz\.?|godzin(?:e|ę|a|y)?|wczoraj|dzień|dzien|dni|tydzień|tydzien|tygodnia|tyg\.?|miesiąc|miesiac|mies\.?|miesięcy|miesiecy))",
        r"((?:\d+\s*)?(?:min(?:ute)?s?|hours?|days?|weeks?|months?)\s+ago)",
        r"\b(yesterday)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            candidates.append(match.group(1) if match.groups() else match.group(0))
    for match in re.finditer(r"(.{0,25}(?:Dodane|ago|wczoraj|yesterday).{0,70})", text, flags=re.IGNORECASE):
        candidates.append(match.group(1))
    seen = set()
    for candidate in candidates:
        raw = re.sub(r"\s+", " ", str(candidate or "")).strip()
        if not raw or raw.lower() in seen:
            continue
        seen.add(raw.lower())
        minutes = _parse_age_text_minutes(raw)
        if minutes is not None:
            return minutes, raw[:120]
    return None, None


def verify_detail_age_before_send(item, source_age: str | None = None) -> dict:
    if not DETAIL_AGE_VERIFY_ENABLED:
        print("[DETAIL_AGE_VERIFY_SKIPPED] reason=disabled")
        return {
            "ok": False,
            "age_minutes": None,
            "age_source": "disabled",
            "raw_text": None,
            "block_reason": None,
        }
    item = item or {}
    title = str(item.get("title") or "")[:80]
    url = item.get("link") or item.get("url") or ""
    DETAIL_AGE_STATS["checked"] += 1
    if not url:
        print(f"[DETAIL_AGE_VERIFY_ERROR] title={title} error=missing_url")
        return {
            "ok": False,
            "age_minutes": None,
            "age_source": "error",
            "raw_text": None,
            "block_reason": "detail_age_missing_url",
        }
    try:
        response = vinted_fetch(url, label="detail_age_verify")
        if not response:
            print(f"[DETAIL_AGE_VERIFY_ERROR] title={title} error=no_response")
            return {
                "ok": False,
                "age_minutes": None,
                "age_source": "error",
                "raw_text": None,
                "block_reason": "detail_age_fetch_error",
            }
        minutes, raw_text = _extract_detail_age_text(response.text)
        if minutes is None:
            print(f"[DETAIL_AGE_UNVERIFIED_BLOCK] title={title} reason=detail_age_not_found")
            return {
                "ok": False,
                "age_minutes": None,
                "age_source": "not_found",
                "raw_text": raw_text,
                "block_reason": "detail_age_unverified_block",
            }
        DETAIL_AGE_STATS["parsed"] += 1
        print(f"[DETAIL_AGE_VERIFY] title={title} source_age={source_age or 'unknown'} "
              f"detail_age_source=detail_visible_text age_minutes={minutes} raw_text={raw_text}")
        return {
            "ok": True,
            "age_minutes": minutes,
            "age_source": "detail_visible_text",
            "raw_text": raw_text,
            "block_reason": None,
        }
    except Exception as e:
        print(f"[DETAIL_AGE_VERIFY_ERROR] title={title} error={e}")
        return {
            "ok": False,
            "age_minutes": None,
            "age_source": "error",
            "raw_text": None,
            "block_reason": "detail_age_verify_error",
        }


def extract_visible_age_minutes(item) -> tuple[int | None, str]:
    item = item or {}
    fields = [
        "age", "age_text", "created_at_text", "added", "added_text",
        "date", "subtitle", "metadata", "raw_card_text", "detail_text",
    ]
    for field in fields:
        value = item.get(field)
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            try:
                value = json.dumps(value, ensure_ascii=False)
            except Exception:
                value = str(value)
        minutes = _parse_age_text_minutes(str(value))
        if minutes is not None:
            verbose_item_log("age_source", f"[AGE_PARSE] source=visible_text visible={str(value)[:80]!r} minutes={minutes}")
            return minutes, f"visible:{field}"
    synthetic = item.get("age_min")
    if synthetic is None:
        synthetic = item.get("_rank")
    verbose_item_log("age_source", f"[AGE_PARSE] source=synthetic_rank minutes={synthetic} reason=no_visible_age")
    return None, "no_visible_age"


def get_item_age_info(item) -> dict:
    item = item or {}
    ts = item.get("created_at_ts")
    if ts:
        try:
            minutes = max(0, int((time.time() - float(ts)) / 60))
            verbose_item_log("age_source", f"[AGE_SOURCE] source=created_at_ts minutes={minutes} usable_for_freshness=True")
            record_age_source_resolution("created_at_ts")
            return {
                "minutes": minutes,
                "source": "created_at_ts",
                "usable_for_freshness": True,
                "visible_text": None,
            }
        except Exception:
            pass

    fields = [
        "age", "age_text", "created_at_text", "added", "added_text",
        "date", "subtitle", "metadata", "raw_card_text", "detail_text",
    ]
    for field in fields:
        value = item.get(field)
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            try:
                value = json.dumps(value, ensure_ascii=False)
            except Exception:
                value = str(value)
        minutes = _parse_age_text_minutes(str(value))
        if minutes is not None:
            verbose_item_log("age_source", f"[AGE_SOURCE] source=visible_text minutes={minutes} text={str(value)[:80]!r} usable_for_freshness=True")
            record_age_source_resolution("visible_text")
            return {
                "minutes": minutes,
                "source": "visible_text",
                "usable_for_freshness": True,
                "visible_text": str(value),
            }

    rank = item.get("_rank")
    if rank is not None:
        try:
            rank_i = int(rank)
            if rank_i <= 5:
                minutes = 5
            elif rank_i <= 20:
                minutes = 30
            elif rank_i <= 50:
                minutes = 90
            else:
                minutes = 180
        except Exception:
            minutes = None
        verbose_item_log("age_source", f"[AGE_SOURCE] source=synthetic_rank minutes={minutes} usable_for_freshness=False")
        record_age_source_resolution("synthetic_rank")
        return {
            "minutes": minutes,
            "source": "synthetic_rank",
            "usable_for_freshness": False,
            "visible_text": None,
        }

    verbose_item_log("age_source", "[AGE_SOURCE] source=unknown usable_for_freshness=False")
    record_age_source_resolution("unknown")
    return {
        "minutes": None,
        "source": "unknown",
        "usable_for_freshness": False,
        "visible_text": None,
    }


def _raw_weak_brand_only(item: dict, text: str) -> bool:
    brand = raw_normalize_text(item.get("brand") or "")
    title = raw_normalize_text(item.get("title") or "")
    if brand in WEAK_VINTAGE_BRANDS:
        verbose_item_log("raw_style_blocks", f"[WEAK_BRAND_SIGNAL_IGNORED] brand={item.get('brand')} title={str(item.get('title') or '')[:60]}")
        return True
    for weak in WEAK_VINTAGE_BRANDS:
        if raw_contains_phrase(title, f"marka {weak}") or raw_contains_phrase(title, f"brand {weak}"):
            verbose_item_log("raw_style_blocks", f"[WEAK_BRAND_SIGNAL_IGNORED] brand={weak} title={str(item.get('title') or '')[:60]}")
            return True
    m = re.search(r"\bmarka\s+([a-z0-9 ]{2,30})", title)
    if m and m.group(1).strip() in WEAK_VINTAGE_BRANDS:
        verbose_item_log("raw_style_blocks", f"[WEAK_BRAND_SIGNAL_IGNORED] brand={m.group(1).strip()} title={str(item.get('title') or '')[:60]}")
        return True
    return False


def _validated_raw_style_reasons(item: dict, bucket: str) -> list[str]:
    text = _raw_presend_text(item)
    reasons: list[str] = []

    def add(reason: str):
        if reason not in reasons:
            reasons.append(reason)

    if raw_contains_phrase(text, "made in usa") or raw_contains_phrase(text, "made in u s a"):
        add("made in usa")
    if raw_contains_phrase(text, "single stitch"):
        add("single stitch")
    if _raw_exact_year_hit(text) or raw_contains_any_phrase(text, ["80s", "90s", "00s"]):
        add("year_or_era")
    if raw_contains_any_phrase(text, ["official", "licensed", "copyright"]):
        add("official_licensed")
    if raw_contains_any_phrase(text, [
        "mlb", "nba", "nfl", "nhl", "ncaa", "dodgers", "raiders", "bulls",
        "vikings", "rangers", "world series", "super bowl", "college",
        "university", "team", "player", "red sox", "yankees", "bears",
        "final four",
    ]):
        add("team_league_player")
    if raw_contains_any_phrase(text, ["tour", "band", "movie promo", "promo", "race", "racing", "event"]):
        add("event_tour_context")
    if raw_contains_any_phrase(text, ["big print", "big graphic", "large print", "front print", "back print", "double sided", "spellout", "spell out"]):
        add("strong_print")
    if raw_contains_any_phrase(text, RAW_STYLE_KNOWN_STRONG_MOTIFS):
        add("known_motif")
    if reasons and raw_contains_any_phrase(text, [
        "screen stars", "fruit of the loom", "russell athletic", "jerzees",
        "hanes", "nutmeg", "anvil", "tultex", "oneita", "galt sand",
    ]):
        add("old_tag_with_context")
    if _raw_has_good_size(item, text):
        add("good_size")
    return reasons


def count_validated_raw_style_signals(item: dict, bucket) -> int:
    return len(_validated_raw_style_reasons(item or {}, str(bucket or "")))


def _presend_bump(source: str, passed: bool, reason: str | None = None):
    source = source or "MAIN"
    PRESEND_STATS["checked"] += 1
    by_source = PRESEND_STATS["by_source"]
    by_source[source] = by_source.get(source, 0) + 1
    if passed:
        PRESEND_STATS["passed"] += 1
        return
    PRESEND_STATS["blocked"] += 1
    reason = reason or "blocked"
    blocked = PRESEND_STATS["blocked_by_reason"]
    blocked[reason] = blocked.get(reason, 0) + 1


def _validated_real_signal_reasons(item: dict, bucket: str) -> list[str]:
    return [
        reason for reason in _validated_raw_style_reasons(item or {}, bucket)
        if reason not in ("good_size", "old_tag_with_context")
    ]


def validated_real_signal_reasons(item, result=None, bucket=None) -> list[str]:
    result = result or {}
    bucket = bucket or result.get("raw_style_bucket") or result.get("taste_bucket") or result.get("tier") or "none"
    return _validated_real_signal_reasons(item or {}, str(bucket or "none"))


def _old_blank_tag_hit(text: str) -> bool:
    return raw_contains_any_phrase(text, [
        "fruit of the loom", "hanes", "jerzees", "russell athletic", "nutmeg",
        "galt sand", "tultex", "anvil", "screen stars", "oneita",
    ])


def _log_weak_descriptors_ignored(text: str, title: str):
    for term in WEAK_DESCRIPTOR_TERMS:
        if raw_contains_phrase(text, term):
            verbose_item_log("raw_style_blocks", f"[WEAK_DESCRIPTOR_IGNORED] term={term} title={title[:60]}")


def _presend_block(result: dict, source: str, reason: str) -> tuple[bool, str]:
    result["_presend_block_reason"] = reason
    _presend_bump(source, False, reason)
    return False, reason


def telegram_presend_gate(item, result=None, source="MAIN") -> tuple[bool, str]:
    item = item or {}
    result = result or {}
    source = source or "MAIN"
    text = _raw_presend_text(item)
    title = str(item.get("title") or "")
    bucket = str(result.get("raw_style_bucket") or result.get("taste_bucket") or result.get("tier") or "none")
    try:
        alert_type = _alert_type(result)
    except NameError:
        alert_type = source
    score = float(
        result.get("raw_style_score")
        or result.get("taste_watch_score")
        or result.get("final_score")
        or result.get("signal_quality_score")
        or 0
    )
    price = float(item.get("price") or 0)
    effective_price = float(result.get("effective_price") or price or 0)
    reasons = _validated_raw_style_reasons(item, bucket)
    real_reasons = _validated_real_signal_reasons(item, bucket)
    validated = len(real_reasons)
    result["_raw_style_validated_signals"] = validated
    result["_raw_style_presend_reasons"] = real_reasons or reasons
    age_info = get_item_age_info(item)
    visible_age = age_info.get("minutes") if age_info.get("usable_for_freshness") else None
    result["_visible_age_minutes"] = visible_age
    result["_visible_age_source"] = age_info.get("source")
    result["_age_usable_for_freshness"] = bool(age_info.get("usable_for_freshness"))
    AGE_GATE_STATS["raw_checked"] += 1
    _log_weak_descriptors_ignored(text, title)

    if not age_info.get("usable_for_freshness"):
        result["_visible_age_source"] = "synthetic_rank" if age_info.get("source") == "synthetic_rank" else "unknown"

    strong_grail = (
        alert_type == "GRAIL"
        and (
            result.get("tier") == "TIER_S"
            or float(result.get("signal_quality_score") or 0) >= 85
            or score >= 95
        )
    )

    if not age_info.get("usable_for_freshness"):
        if not DETAIL_AGE_VERIFY_ENABLED:
            result["_detail_age_verification"] = {
                "ok": False,
                "age_source": "disabled",
                "block_reason": None,
            }
            print(f"[DETAIL_AGE_VERIFY_SKIPPED] reason=disabled source_age={age_info.get('source')}")
        else:
            detail_age = verify_detail_age_before_send(item, source_age=age_info.get("source"))
            result["_detail_age_verification"] = detail_age
            if detail_age.get("ok") and detail_age.get("age_minutes") is not None:
                detail_minutes = int(detail_age.get("age_minutes"))
                result["_visible_age_minutes"] = detail_minutes
                result["_visible_age_source"] = "detail_visible_text"
                result["_age_usable_for_freshness"] = True
                result["age_min"] = detail_minutes
                result["age_source"] = "detail_visible_text"
                item["age_min"] = detail_minutes
                item["age_source"] = "detail_visible_text"
                visible_age = detail_minutes
                age_info = {
                    "minutes": detail_minutes,
                    "source": "detail_visible_text",
                    "usable_for_freshness": True,
                    "visible_text": detail_age.get("raw_text"),
                }
                record_age_source_resolution("detail_visible_text")
                if detail_minutes > MAX_DETAIL_SEND_AGE_MIN:
                    DETAIL_AGE_STATS["blocked_stale"] += 1
                    print(f"[STALE_DETAIL_AGE_BLOCK] title={title[:80]} "
                          f"age_minutes={detail_minutes} raw_age_text={detail_age.get('raw_text')} "
                          f"source=detail_visible_text url={item.get('link') or item.get('url')} "
                          f"max_allowed={MAX_DETAIL_SEND_AGE_MIN}")
                    return _presend_block(result, source, "stale_detail_age_presend_block")
            else:
                confidence = float(result.get("confidence") or 0)
                if (
                    strong_grail
                    and ALLOW_UNVERIFIED_AGE_FOR_STRONG_GRAIL
                    and validated >= 5
                    and confidence >= 8.5
                ):
                    DETAIL_AGE_STATS["allowed_grail_unverified"] += 1
                    print(f"[DETAIL_AGE_UNVERIFIED_GRAIL_ALLOW] title={title[:80]} "
                          f"validated_signals={validated} confidence={confidence:.1f}")
                else:
                    DETAIL_AGE_STATS["blocked_unverified"] += 1
                    return _presend_block(result, source, detail_age.get("block_reason") or "detail_age_unverified_block")

    if visible_age is not None and visible_age > RAW_STYLE_MAX_VISIBLE_AGE_MIN and not strong_grail:
        AGE_GATE_STATS["blocked_stale_visible_age"] += 1
        print(f"[STALE_BLOCK_DETAIL] visible_age={visible_age} title={title[:80]}")
        return _presend_block(result, source, "stale_visible_age_presend_block")

    if raw_contains_any_phrase(text, KIDS_TERMS):
        return _presend_block(result, source, "kids_presend_block")

    women_fit = raw_contains_any_phrase(text, WOMEN_FIT_TERMS)
    fitted_top = raw_contains_any_phrase(text, FITTED_TOP_TERMS)
    small_size = _raw_has_small_size(item, text)
    has_mens_unisex = raw_contains_any_phrase(text, MENS_UNISEX_TERMS)
    has_oversize = raw_contains_any_phrase(text, OVERSIZE_TERMS)
    has_xl_size = _raw_size_bucket(text, item) == "large"
    hard_fitted = raw_contains_any_phrase(text, HARD_FITTED_TOP_TERMS)
    exception_ok = (
        (has_mens_unisex or has_oversize or has_xl_size)
        and validated >= 4
        and not hard_fitted
        and (strong_grail or source in {"RAW_STYLE", "STYLE_WATCH"} and score >= 90)
        and bucket != "old_blank"
    )
    if (women_fit or fitted_top) and not exception_ok:
        AGE_GATE_STATS["blocked_women_fitted"] += 1
        return _presend_block(result, source, "women_or_fitted_presend_block")
    if source in {"RAW_STYLE", "STYLE_WATCH", "SAFEGUARD"} and small_size and not exception_ok:
        AGE_GATE_STATS["blocked_women_fitted"] += 1
        return _presend_block(result, source, "small_size_presend_block")

    if _raw_weak_brand_only(item, text) and validated < 3 and not strong_grail:
        AGE_GATE_STATS["blocked_weak_brand"] += 1
        return _presend_block(result, source, "weak_brand_only_presend_block")

    if raw_contains_any_phrase(text, WEAK_NOVELTY_BRANDS) and validated < 3:
        AGE_GATE_STATS["blocked_weak_brand"] += 1
        return _presend_block(result, source, "weak_novelty_brand_presend_block")

    if source == "SAFEGUARD" and SAFEGUARD_STRICT_PRESEND_ENABLED and validated < 3 and not strong_grail:
        return _presend_block(result, source, "safeguard_relaxed_not_enough_signal")

    if visible_age is None and result.get("_visible_age_source") == "synthetic_rank" and validated < 3 and not strong_grail:
        AGE_GATE_STATS["blocked_unknown_age"] += 1
        return _presend_block(result, source, "synthetic_age_not_enough_real_signals")

    if price < 25 and validated < 3 and not strong_grail:
        return _presend_block(result, source, "cheap_trash_presend_block")
    if effective_price <= 5 and bucket in ("old_blank", "pop_culture", "sports") and validated < 3 and not strong_grail:
        return _presend_block(result, source, "cheap_trash_presend_block")
    if source in {"RAW_STYLE", "STYLE_WATCH", "SAFEGUARD"} and validated < 2 and not strong_grail:
        return _presend_block(result, source, "not_enough_validated_signals_presend")

    if (bucket == "old_blank" or _old_blank_tag_hit(text)) and not strong_grail:
        real_context_reasons = real_reasons
        basic = raw_contains_any_phrase(text, RAW_STYLE_BASIC_TERMS) or (
            len(real_context_reasons) < 2
            and raw_contains_any_phrase(text, ["t-shirt", "tshirt", "tee", "sweatshirt", "hoodie", "bluza"])
            and not raw_contains_any_phrase(text, RAW_STYLE_CONTEXT_TERMS)
        )
        no_context = len(real_context_reasons) < 2 or not raw_contains_any_phrase(text, RAW_STYLE_CONTEXT_TERMS)
        if basic:
            AGE_GATE_STATS["blocked_old_blank_no_context"] += 1
            return _presend_block(result, source, "old_blank_no_context_presend_block")
        if no_context:
            AGE_GATE_STATS["blocked_old_blank_no_context"] += 1
            return _presend_block(result, source, "old_blank_no_context_presend_block")

    if source in {"RAW_STYLE", "STYLE_WATCH"} and bucket == "pop_culture":
        if validated < 2 or not raw_contains_any_phrase(text, RAW_STYLE_POP_VALIDATION_TERMS):
            return _presend_block(result, source, "pop_culture_not_validated_presend")

    if source in {"RAW_STYLE", "STYLE_WATCH"} and bucket == "sports":
        has_context = raw_contains_any_phrase(text, RAW_STYLE_CONTEXT_TERMS)
        good_item_type = raw_contains_any_phrase(text, RAW_STYLE_SPORTS_ITEM_TERMS)
        generic_sport = raw_contains_any_phrase(text, ["sportowy t-shirt", "damski t-shirt", "women jersey", "v neck", "v-neck", "small logo"])
        if not has_context or not good_item_type or generic_sport or validated < 2:
            return _presend_block(result, source, "sports_not_validated_presend")

    if source in {"RAW_STYLE", "STYLE_WATCH"} and bucket == "visual":
        generic_only = raw_contains_any_phrase(text, RAW_STYLE_GENERIC_VISUAL_TERMS) and not raw_contains_any_phrase(text, RAW_STYLE_VISUAL_CONTEXT_TERMS)
        if generic_only or validated < 2:
            return _presend_block(result, source, "visual_too_generic_presend")

    _presend_bump(source, True)
    return True, "pass"


def raw_style_pre_send_gate(item, raw_style_result) -> tuple[bool, str]:
    return telegram_presend_gate(item, raw_style_result, source="RAW_STYLE")


def reset_candidate_audit_cycle(cycle_number: int):
    global AUDIT_CURRENT_CYCLE, AUDIT_LINES_THIS_CYCLE
    AUDIT_CURRENT_CYCLE = cycle_number
    AUDIT_LINES_THIS_CYCLE = 0
    AUDIT_STATS.update({
        "seen": 0,
        "raw_checked": 0,
        "raw_candidates": 0,
        "raw_sent": 0,
        "main_candidates": 0,
        "main_sent": 0,
        "blocked": 0,
        "dedupe_skipped": 0,
        "top_block_reasons": {},
        "top_queries": {},
    })
    AUDIT_TOP_BLOCKED.clear()
    AUDIT_TOP_NOT_SENT.clear()


def _audit_bump(stage: str, event: dict):
    query = event.get("query") or "unknown"
    AUDIT_STATS["top_queries"][query] = AUDIT_STATS["top_queries"].get(query, 0) + 1
    if stage == "seen":
        AUDIT_STATS["seen"] += 1
    elif stage == "raw_style_check":
        AUDIT_STATS["raw_checked"] += 1
    elif stage == "candidate":
        if event.get("alert_type") == "RAW_STYLE" or event.get("bucket"):
            AUDIT_STATS["raw_candidates"] += 1
        else:
            AUDIT_STATS["main_candidates"] += 1
    elif stage == "main_engine_score":
        AUDIT_STATS["main_candidates"] += 1
    elif stage == "sent":
        if event.get("alert_type") == "RAW_STYLE":
            AUDIT_STATS["raw_sent"] += 1
        else:
            AUDIT_STATS["main_sent"] += 1
    elif stage in ("blocked", "quality_block", "dedupe_skip"):
        if stage == "dedupe_skip":
            AUDIT_STATS["dedupe_skipped"] += 1
        else:
            AUDIT_STATS["blocked"] += 1
        reason = event.get("block_reason") or stage
        reasons = AUDIT_STATS["top_block_reasons"]
        reasons[reason] = reasons.get(reason, 0) + 1


def _audit_track_interesting(event: dict):
    stage = event.get("stage")
    score = float(event.get("score") or 0)
    if stage in ("blocked", "quality_block"):
        AUDIT_TOP_BLOCKED.append(event)
        AUDIT_TOP_BLOCKED.sort(key=lambda e: float(e.get("score") or 0), reverse=True)
        del AUDIT_TOP_BLOCKED[10:]
    elif stage in ("rank_not_selected", "final_skip", "dedupe_skip"):
        AUDIT_TOP_NOT_SENT.append(event)
        AUDIT_TOP_NOT_SENT.sort(key=lambda e: float(e.get("score") or 0), reverse=True)
        del AUDIT_TOP_NOT_SENT[10:]


def write_candidate_audit(event: dict):
    global AUDIT_LINES_THIS_CYCLE, AUDIT_WRITE_ERROR_LOGGED
    if not CANDIDATE_AUDIT_ENABLED:
        return
    event = dict(event or {})
    event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    event.setdefault("cycle", AUDIT_CURRENT_CYCLE)
    _audit_bump(event.get("stage", ""), event)
    _audit_track_interesting(event)
    if AUDIT_LINES_THIS_CYCLE >= CANDIDATE_AUDIT_MAX_LINES_PER_CYCLE:
        return
    try:
        folder = os.path.dirname(CANDIDATE_AUDIT_PATH)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(CANDIDATE_AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        AUDIT_LINES_THIS_CYCLE += 1
        title_n = raw_normalize_text(event.get("title") or "")
        for needle in AUDIT_WATCH_NEEDLES:
            needle_n = raw_normalize_text(needle)
            if needle_n and needle_n in title_n:
                print(f"[AUDIT_WATCH_MATCH] needle={needle} query={event.get('query')} "
                      f"title={str(event.get('title') or '')[:60]} stage={event.get('stage')} "
                      f"score={event.get('score')} block_reason={event.get('block_reason')} sent={event.get('sent')}")
    except Exception as e:
        if not AUDIT_WRITE_ERROR_LOGGED:
            print(f"[AUDIT_WRITE_ERROR] error={e}")
            AUDIT_WRITE_ERROR_LOGGED = True


def audit_candidate(stage: str, item: dict, search: dict | None = None, result: dict | None = None,
                    block_reason: str | None = None, sent: bool = False,
                    alert_type: str | None = None, score=None, bucket=None, signals=None):
    item = item or {}
    result = result or {}
    meta = item.get("_search_meta") or {}
    search = search or {}
    age_info = get_item_age_info(item)
    age = result.get("age_min") if result.get("age_min") is not None else age_info.get("minutes")
    age_source = result.get("age_source") or age_info.get("source")
    dedupe_key = ""
    try:
        dedupe_key = get_item_dedupe_key(item)
    except Exception:
        pass
    event = {
        "stage": stage,
        "query": search.get("name") or meta.get("name") or "unknown",
        "title": item.get("title"),
        "url": item.get("url") or item.get("link"),
        "brand": result.get("brand") or result.get("brand_detected") or item.get("brand"),
        "price": item.get("price"),
        "effective_price": result.get("effective_price"),
        "age": age,
        "age_source": age_source,
        "age_usable_for_freshness": age_info.get("usable_for_freshness"),
        "size": item.get("size") or result.get("size"),
        "category": result.get("category") or item.get("category"),
        "bucket": bucket or result.get("raw_style_bucket") or result.get("taste_bucket") or result.get("tier"),
        "score": score if score is not None else (
            result.get("raw_style_score") or result.get("final_score") or result.get("signal_quality_score")
        ),
        "quality_score": result.get("signal_quality_score"),
        "tier": result.get("tier") or result.get("signal_tier"),
        "engine": result.get("engine"),
        "signals": signals if signals is not None else (
            result.get("raw_style_signals") or result.get("taste_signals") or result.get("desirable_signals") or []
        ),
        "block_reason": block_reason or result.get("_quality_block_reason") or result.get("raw_style_block_reason"),
        "sent": bool(sent),
        "alert_type": alert_type,
        "dedupe_key": dedupe_key,
    }
    _fresh_discovery_audit_event(event)
    markers = _target_marker_hits(item, result)
    if markers:
        event["matched_markers"] = markers
        _target_audit_event(event)
    write_candidate_audit(event)


def compute_raw_style_score(item: dict) -> dict:
    item = item or {}
    title = str(item.get("title") or "")
    text = " ".join(str(item.get(k) or "") for k in ("title", "brand", "description", "category"))
    text_n = raw_normalize_text(text)
    price = float(item.get("price") or 0)
    effective_price = max(0.0, price - NEGOTIATION_BUFFER_PLN)
    age_info = get_item_age_info(item)
    age = int(age_info.get("minutes") if age_info.get("minutes") is not None else 9999)
    freshness_scored = False
    signals: list[str] = []
    buckets: set[str] = set()
    score = 0
    block_reason = None

    def add(prefix: str, hit: str, points: int, bucket: str):
        nonlocal score
        score += points
        sig = f"{prefix}:{hit}"
        if sig not in signals:
            signals.append(sig)
        buckets.add(bucket)

    for hit in _raw_hits(text, RAW_STYLE_OLD_BLANK):
        add("old_blank", hit, 35, "old_blank")
        break
    for hit in _raw_hits(text, RAW_STYLE_POP_CULTURE):
        add("pop", hit, 30, "pop_culture")
        break
    for hit in _raw_hits(text, RAW_STYLE_BIKER):
        add("biker", hit, 30, "biker")
        break
    for hit in _raw_hits(text, RAW_STYLE_SPORTS_COLLEGE):
        add("sports", hit, 30, "sports")
        break
    for hit in _raw_hits(text, RAW_STYLE_STREETWEAR):
        add("streetwear", hit, 25, "streetwear")
        break
    for hit in _raw_hits(text, RAW_STYLE_RALPH_WORKWEAR):
        add("workwear", hit, 25, "workwear")
        break
    for hit in _raw_hits(text, RAW_STYLE_METAL):
        add("metal", hit, 25, "metal")
        break

    visual_hits = _raw_hits(text, RAW_STYLE_VISUAL)
    if visual_hits:
        add("visual", visual_hits[0], 15, "visual")
    era_hits = _raw_hits(text, RAW_STYLE_ERA_SIGNALS)
    if era_hits:
        score += 15
        signals.append(f"era:{era_hits[0]}")

    size_bucket = _raw_size_bucket(text, item)
    if size_bucket == "large":
        score += 10
        signals.append("size:L_XL_XXL")
    elif size_bucket == "medium":
        score += 5
        signals.append("size:M")

    if effective_price <= 30:
        score += 25
        signals.append("price:effective_<=30")
    elif effective_price <= 50:
        score += 20
        signals.append("price:effective_<=50")
    elif effective_price <= 80:
        score += 10
        signals.append("price:effective_<=80")
    elif effective_price <= 100:
        score += 5
        signals.append("price:effective_<=100")

    if age_info.get("usable_for_freshness") and age <= 10:
        score += 20
        signals.append("fresh:<=10")
        freshness_scored = True
    elif age_info.get("usable_for_freshness") and age <= 30:
        score += 15
        signals.append("fresh:<=30")
        freshness_scored = True
    elif age_info.get("usable_for_freshness") and age <= 90:
        score += 10
        signals.append("fresh:<=90")
        freshness_scored = True

    is_clothing = _raw_is_clothing(text, item)
    fast_fashion = raw_contains_any_phrase(text, list(RAW_STYLE_FAST_FASHION))
    non_clothing = raw_contains_any_phrase(text, RAW_STYLE_NON_CLOTHING) and not is_clothing
    fake_hit = raw_contains_any_phrase(text, ["fake", "inspired", "unofficial", "style"])
    strong_official_context = bool(
        buckets.intersection({"old_blank", "pop_culture", "sports", "biker", "workwear", "metal"})
        or raw_contains_any_phrase(text, ["licensed", "official", "made in usa", "single stitch", "screen stars"])
    )
    generic_sports_brand = raw_contains_any_phrase(text, list(RAW_STYLE_GENERIC_SPORTS))
    generic_sports_ok = bool(
        buckets.intersection({"old_blank", "sports", "pop_culture"})
        or raw_contains_any_phrase(text, ["all over print", "aop", "track jacket", "football shirt", "football kit", "jersey"])
        or any(sig.startswith("visual:") and not sig.endswith(":graphic") for sig in signals)
    )
    carhartt_small_pants = bool(
        raw_contains_phrase(text, "carhartt")
        and raw_contains_any_phrase(text, ["pants", "pant", "spodnie", "cargo", "work pants", "double knee", "jeans"])
        and raw_contains_any_phrase(text, RAW_STYLE_SMALL_CARHARTT_SIZES)
    )

    if fast_fashion:
        block_reason = "fast_fashion"
    elif non_clothing:
        block_reason = "non_clothing"
    elif carhartt_small_pants:
        block_reason = "small_carhartt_pants"
    elif fake_hit and not strong_official_context:
        block_reason = "fake_inspired_unofficial"
    elif generic_sports_brand and not generic_sports_ok:
        block_reason = "generic_sports_brand_no_style_signal"
    elif not is_clothing:
        block_reason = "non_clothing"

    real_signal_count = _raw_real_signal_count(signals)
    raw_style_real_signal = real_signal_count > 0
    bucket = "none"
    for preferred in ("old_blank", "pop_culture", "biker", "sports", "streetwear", "workwear", "metal", "visual"):
        if preferred in buckets:
            bucket = preferred
            break
    score = max(0, min(100, round(score, 2)))

    if not raw_style_real_signal:
        block_reason = block_reason or "no_real_style_signal"
    if price <= 0:
        block_reason = block_reason or "missing_price"
    if price > RAW_STYLE_SNIPER_MAX_PRICE:
        block_reason = block_reason or "price_above_raw_style_max"
    if age_info.get("usable_for_freshness") and age > RAW_STYLE_SNIPER_MAX_AGE_MIN:
        block_reason = block_reason or "age_above_raw_style_max"

    eligible = False
    validated_real_count = len(validated_real_signal_reasons(item, bucket=bucket))
    collectible_watch = bool(
        price > RAW_STYLE_SNIPER_MAX_PRICE
        and raw_style_real_signal
        and (
            validated_real_count >= 4
            or (
                buckets.intersection({"old_blank", "pop_culture", "sports", "workwear", "metal", "biker"})
                and (raw_contains_any_phrase(text, RAW_STYLE_ERA_SIGNALS)
                     or raw_contains_any_phrase(text, ["single stitch", "made in usa", "screen stars", "nutmeg", "licensed", "official"]))
            )
        )
    )
    if block_reason == "price_above_raw_style_max" and collectible_watch:
        block_reason = "price_high_but_collectible_watch"
    if not block_reason and RAW_STYLE_SNIPER_ENABLED:
        if age_info.get("usable_for_freshness"):
            eligible = bool(
                (score >= 65 and raw_style_real_signal and price <= RAW_STYLE_SNIPER_MAX_PRICE and age <= RAW_STYLE_SNIPER_MAX_AGE_MIN)
                or (score >= 55 and effective_price <= 50 and age <= 90 and real_signal_count >= 2)
                or (buckets.intersection({"streetwear", "biker", "pop_culture", "old_blank"}) and effective_price <= 30 and size_bucket in {"medium", "large"} and age <= 90)
                or (score >= 75 and price <= RAW_STYLE_SNIPER_MAX_PRICE and age <= RAW_STYLE_SNIPER_MAX_AGE_MIN and real_signal_count >= 2)
            )
        else:
            eligible = bool(
                price <= RAW_STYLE_SNIPER_MAX_PRICE
                and validated_real_count >= 3
                and score >= 70
                and raw_style_real_signal
            )
    if not eligible and not block_reason:
        block_reason = "below_raw_style_threshold"

    return {
        "raw_style_score": score,
        "raw_style_signals": signals,
        "raw_style_bucket": bucket,
        "raw_style_block_reason": block_reason,
        "raw_style_real_signal": raw_style_real_signal,
        "raw_style_real_signal_count": real_signal_count,
        "effective_price": round(effective_price, 2),
        "age_min": age,
        "age_source": age_info.get("source"),
        "freshness_scored": freshness_scored,
        "validated_real_signals": validated_real_count,
        "collector_watch_candidate": collectible_watch,
        "eligible": eligible,
    }


def reset_raw_style_cycle():
    RAW_STYLE_CYCLE_CANDIDATES.clear()
    RAW_STYLE_STATS.update({
        "checked": 0,
        "candidates": 0,
        "sent": 0,
        "blocked": 0,
        "dedupe_skipped": 0,
    })
    AGE_GATE_STATS.update({
        "raw_checked": 0,
        "blocked_stale_visible_age": 0,
        "blocked_unknown_age": 0,
        "blocked_old_blank_no_context": 0,
        "blocked_weak_brand": 0,
        "blocked_women_fitted": 0,
        "sent": 0,
    })
    PRESEND_STATS.update({
        "checked": 0,
        "passed": 0,
        "blocked": 0,
        "blocked_by_reason": {},
        "by_source": {},
    })
    DETAIL_AGE_STATS.update({
        "checked": 0,
        "parsed": 0,
        "blocked_stale": 0,
        "blocked_unverified": 0,
        "allowed_grail_unverified": 0,
    })
    AGE_SOURCE_STATS.update({
        "created_at_ts": 0,
        "visible_text": 0,
        "synthetic_rank": 0,
        "unknown": 0,
        "synthetic_sent": 0,
        "visible_sent": 0,
    })
    SAFEGUARD_STATS.update({
        "retried": 0,
        "added": 0,
        "passed_presend": 0,
        "blocked_presend": 0,
        "sent": 0,
        "limit_skipped": 0,
    })
    VERBOSE_LOG_STATS["printed"] = 0
    VERBOSE_LOG_STATS["suppressed"] = {
        "age_source": 0,
        "size_parse": 0,
        "safeguard_blocks": 0,
        "raw_style_blocks": 0,
        "audit_seen": 0,
    }
    RAW_STYLE_BLOCK_STATS.update({
        "total": 0,
        "by_reason": {},
        "top_blocked": [],
    })


def collect_raw_style_candidate(item: dict, search: dict | None = None):
    if not RAW_STYLE_SNIPER_ENABLED:
        return
    item = dict(item or {})
    search = search or {}
    if search.get("football_mode") or search.get("lego_sw_mode"):
        return
    item.setdefault("_search_meta", {"name": search.get("name")})
    RAW_STYLE_STATS["checked"] += 1
    profile = compute_raw_style_score(item)
    if VERBOSE_ITEM_DEBUG:
        print(f"[RAW_STYLE_CHECK] score={profile['raw_style_score']:.0f} "
              f"bucket={profile['raw_style_bucket']} signals={profile['raw_style_signals'][:5]} "
              f"real_signal={profile['raw_style_real_signal']} price={float(item.get('price') or 0):.0f} "
              f"effective_price={profile['effective_price']:.0f} age={profile['age_min']} "
              f"title={str(item.get('title') or '')[:60]}")
    audit_candidate(
        "raw_style_check", item, search, profile,
        score=profile.get("raw_style_score"),
        bucket=profile.get("raw_style_bucket"),
        signals=profile.get("raw_style_signals"),
    )
    if not profile["eligible"]:
        RAW_STYLE_STATS["blocked"] += 1
        record_raw_style_block(profile.get("raw_style_block_reason"), profile.get("raw_style_score"), item.get("title"))
        if profile.get("collector_watch_candidate"):
            watch_result = dict(profile)
            watch_result.update({
                "engine": "WATCH",
                "item": item,
                "watch_candidate": True,
                "collector_watch_candidate": True,
                "_quality_block_reason": "price_high_but_collectible_watch",
            })
            print(f"[COLLECTOR_WATCH_CANDIDATE] reason=price_high_but_collectible_watch "
                  f"score={profile.get('raw_style_score'):.0f} bucket={profile.get('raw_style_bucket')} "
                  f"price={float(item.get('price') or 0):.0f} signals={profile.get('raw_style_signals', [])[:5]} "
                  f"title={str(item.get('title') or '')[:60]}")
            audit_candidate(
                "candidate", item, search, watch_result,
                alert_type="WATCH",
                score=profile.get("raw_style_score"),
                bucket=profile.get("raw_style_bucket"),
                signals=profile.get("raw_style_signals"),
            )
        raw_block_msg = (f"[RAW_STYLE_BLOCK] reason={profile['raw_style_block_reason']} "
                         f"score={profile['raw_style_score']:.0f} signals={profile['raw_style_signals'][:5]} "
                         f"title={str(item.get('title') or '')[:60]}")
        if VERBOSE_ITEM_DEBUG or float(profile.get("raw_style_score") or 0) >= 60:
            verbose_item_log("raw_style_blocks", raw_block_msg, force=not VERBOSE_ITEM_DEBUG)
        else:
            suppress_verbose_log("raw_style_blocks")
        audit_candidate(
            "blocked", item, search, profile,
            block_reason=profile.get("raw_style_block_reason"),
            score=profile.get("raw_style_score"),
            bucket=profile.get("raw_style_bucket"),
            signals=profile.get("raw_style_signals"),
        )
        return
    key = get_item_dedupe_key(item)
    if already_sent(key):
        RAW_STYLE_STATS["dedupe_skipped"] += 1
        print(f"[RAW_STYLE_DEDUPE_SKIP] key={key} title={str(item.get('title') or '')[:60]}")
        audit_candidate(
            "dedupe_skip", item, search, profile,
            block_reason="already_sent",
            score=profile.get("raw_style_score"),
            bucket=profile.get("raw_style_bucket"),
            signals=profile.get("raw_style_signals"),
        )
        return
    result = {
        "engine": "RAW_STYLE",
        "item": item,
        "raw_style_score": profile["raw_style_score"],
        "raw_style_signals": profile["raw_style_signals"],
        "raw_style_bucket": profile["raw_style_bucket"],
        "raw_style_real_signal": profile["raw_style_real_signal"],
        "raw_style_real_signal_count": profile["raw_style_real_signal_count"],
        "effective_price": profile["effective_price"],
        "age_min": profile["age_min"],
        "age_source": profile.get("age_source"),
        "final_score": profile["raw_style_score"],
        "tier": "RAW_STYLE",
    }
    current = RAW_STYLE_CYCLE_CANDIDATES.get(key)
    rank = (
        result["raw_style_score"],
        -result["age_min"],
        -result["effective_price"],
        -float(item.get("price") or 0),
        result["raw_style_real_signal_count"],
    )
    current_rank = None
    if current:
        current_item = current.get("item") or {}
        current_rank = (
            current.get("raw_style_score", 0),
            -current.get("age_min", 9999),
            -current.get("effective_price", 9999),
            -float(current_item.get("price") or 0),
            current.get("raw_style_real_signal_count", 0),
        )
    if not current or rank > current_rank:
        RAW_STYLE_CYCLE_CANDIDATES[key] = result
        query_coverage_record(search.get("name"))["candidates_created"] += 1
    RAW_STYLE_STATS["candidates"] = max(RAW_STYLE_STATS["candidates"], len(RAW_STYLE_CYCLE_CANDIDATES))
    print(f"[RAW_STYLE_CANDIDATE] score={result['raw_style_score']:.0f} "
          f"bucket={result['raw_style_bucket']} signals={result['raw_style_signals'][:5]} "
          f"price={float(item.get('price') or 0):.0f} effective_price={result['effective_price']:.0f} "
          f"age={result['age_min']} title={str(item.get('title') or '')[:60]}")
    audit_candidate(
        "candidate", item, search, result,
        alert_type="RAW_STYLE",
        score=result.get("raw_style_score"),
        bucket=result.get("raw_style_bucket"),
        signals=result.get("raw_style_signals"),
    )


def format_raw_style_alert(result: dict) -> str:
    return format_telegram_alert(result.get("item") or {}, result, "RAW_STYLE")
    item = result.get("item") or {}
    signals = ", ".join((result.get("raw_style_signals") or [])[:6]) or "-"
    price = float(item.get("price") or 0)
    link = item.get("link") or item.get("url") or ""
    lines = [
        "⚡ RAW STYLE SNIPE",
        "",
        f"score={result.get('raw_style_score', 0):.0f}",
        f"bucket={result.get('raw_style_bucket', 'none')}",
        f"age={result.get('age_min', '?')}min",
        f"price={price:.0f} PLN",
        f"effective_price={float(result.get('effective_price') or 0):.0f} PLN",
        f"signals={signals}",
        "",
        str(item.get("title") or "")[:140],
    ]
    if link:
        lines.extend(["", "Open link", str(link)])
    return "\n".join(lines)


def send_raw_style_candidates(max_cycle_slots: int, sent_this_cycle: int) -> int:
    if not RAW_STYLE_SNIPER_ENABLED or max_cycle_slots <= sent_this_cycle:
        return 0
    remaining_raw_slots = max(0, RAW_STYLE_SNIPER_MAX_PER_CYCLE - int(RAW_STYLE_STATS.get("sent", 0)))
    if remaining_raw_slots <= 0:
        return 0
    candidates = sorted(
        RAW_STYLE_CYCLE_CANDIDATES.values(),
        key=lambda r: (
            r.get("raw_style_score", 0),
            -int(r.get("age_min", 9999) or 9999),
            -float(r.get("effective_price", 9999) or 9999),
            -float((r.get("item") or {}).get("price") or 0),
            r.get("raw_style_real_signal_count", 0),
        ),
        reverse=True,
    )
    sent = 0
    for result in candidates:
        if sent >= remaining_raw_slots or sent_this_cycle + sent >= max_cycle_slots:
            break
        item = result.get("item") or {}
        key = get_item_dedupe_key(item)
        if already_sent(key):
            engines = set((SENT_ALERTS.get(key) or {}).get("engines") or [])
            if engines.intersection({"GRAIL", "BRAND", "CHAOS"}):
                print(f"[RAW_STYLE_MERGE_WITH_MAIN_ENGINE] key={key} engines={sorted(engines)} title={str(item.get('title') or '')[:60]}")
            print(f"[RAW_STYLE_DEDUPE_BLOCK] key={key} title={str(item.get('title') or '')[:60]}")
            audit_candidate("dedupe_skip", item, result=result, block_reason="duplicate_before_send",
                            alert_type="RAW_STYLE", score=result.get("raw_style_score"),
                            bucket=result.get("raw_style_bucket"), signals=result.get("raw_style_signals"))
            continue
        presend_ok, presend_reason = raw_style_pre_send_gate(item, result)
        validated_signals = int(result.get("_raw_style_validated_signals") or 0)
        if not presend_ok:
            query_coverage_record((item.get("_search_meta") or {}).get("name"))["blocked_count"] += 1
            record_raw_style_block(presend_reason, result.get("raw_style_score"), item.get("title"))
            presend_block_msg = (f"[RAW_STYLE_PRE_SEND_BLOCK] reason={presend_reason} "
                                 f"score={result.get('raw_style_score',0):.0f} "
                                 f"bucket={result.get('raw_style_bucket','none')} "
                                 f"validated_signals={validated_signals} "
                                 f"visible_age={result.get('_visible_age_minutes')} "
                                 f"title={str(item.get('title') or '')[:60]}")
            if VERBOSE_ITEM_DEBUG or float(result.get("raw_style_score") or 0) >= 70:
                print(presend_block_msg)
            else:
                suppress_verbose_log("raw_style_blocks")
            audit_candidate("blocked", item, result=result, block_reason=presend_reason,
                            alert_type="RAW_STYLE", score=result.get("raw_style_score"),
                            bucket=result.get("raw_style_bucket"), signals=result.get("raw_style_signals"))
            continue
        print(f"[RAW_STYLE_PRE_SEND_PASS] score={result.get('raw_style_score',0):.0f} "
              f"bucket={result.get('raw_style_bucket','none')} "
              f"validated_signals={validated_signals} "
              f"pass_reasons={(result.get('_raw_style_presend_reasons') or [])[:5]} "
              f"title={str(item.get('title') or '')[:60]}")
        photo = item.get("photo") or get_item_photo(item.get("id"), item.get("link") or item.get("url") or "")
        sent_ok = send_alert_message(
            format_telegram_alert(item, result, "RAW_STYLE"),
            item, result, "RAW_STYLE", key,
            photo_url=photo,
            item_link=item.get("link") or item.get("url"),
        )
        if not sent_ok:
            continue
        log_decision_trace(item, result, "RAW_STYLE", presend_reason, send_status="success")
        query_coverage_record((item.get("_search_meta") or {}).get("name"))["alerts_sent"] += 1
        mark_sent(item, result, (item.get("_search_meta") or {}).get("name"))
        print(f"[RAW_STYLE_DEDUPE_MARK] key={key} title={str(item.get('title') or '')[:60]}")
        RAW_STYLE_CYCLE_CANDIDATES.pop(key, None)
        sent += 1
        RAW_STYLE_STATS["sent"] += 1
        AGE_GATE_STATS["sent"] += 1
        log_send_age_source(result)
        print(f"[RAW_STYLE_SEND] rank={sent} score={result.get('raw_style_score',0):.0f} "
              f"bucket={result.get('raw_style_bucket','none')} "
              f"price={float(item.get('price') or 0):.0f} "
              f"effective_price={float(result.get('effective_price') or 0):.0f} "
              f"age={result.get('age_min')} title={str(item.get('title') or '')[:60]}")
        audit_candidate("sent", item, result=result, sent=True, alert_type="RAW_STYLE",
                        score=result.get("raw_style_score"), bucket=result.get("raw_style_bucket"),
                        signals=result.get("raw_style_signals"))
    return sent


def print_raw_style_summary():
    top = sorted(
        RAW_STYLE_CYCLE_CANDIDATES.values(),
        key=lambda r: (
            r.get("raw_style_score", 0),
            -int(r.get("age_min", 9999) or 9999),
            -float(r.get("effective_price", 9999) or 9999),
        ),
        reverse=True,
    )[:3]
    preview = [
        f"score={r.get('raw_style_score',0):.0f} bucket={r.get('raw_style_bucket','none')} "
        f"price={float((r.get('item') or {}).get('price') or 0):.0f} "
        f"effective_price={float(r.get('effective_price') or 0):.0f} "
        f"age={r.get('age_min')} title={str((r.get('item') or {}).get('title') or '')[:45]}"
        for r in top
    ]
    print(f"[RAW_STYLE_SUMMARY] checked={RAW_STYLE_STATS['checked']} "
          f"candidates={RAW_STYLE_STATS['candidates']} sent={RAW_STYLE_STATS['sent']} "
          f"blocked={RAW_STYLE_STATS['blocked']} dedupe_skipped={RAW_STYLE_STATS['dedupe_skipped']} "
          f"top_candidates={preview}")
    print(f"[AGE_GATE_SUMMARY] raw_checked={AGE_GATE_STATS['raw_checked']} "
          f"blocked_stale_visible_age={AGE_GATE_STATS['blocked_stale_visible_age']} "
          f"blocked_unknown_age={AGE_GATE_STATS['blocked_unknown_age']} "
          f"blocked_old_blank_no_context={AGE_GATE_STATS['blocked_old_blank_no_context']} "
          f"blocked_weak_brand={AGE_GATE_STATS['blocked_weak_brand']} "
          f"blocked_women_fitted={AGE_GATE_STATS['blocked_women_fitted']} "
          f"sent={AGE_GATE_STATS['sent']}")
    print(f"[PRESEND_SUMMARY] checked={PRESEND_STATS['checked']} "
          f"passed={PRESEND_STATS['passed']} blocked={PRESEND_STATS['blocked']} "
          f"blocked_by_reason={PRESEND_STATS['blocked_by_reason']} "
          f"by_source={PRESEND_STATS['by_source']}")
    print(f"[AGE_SOURCE_SUMMARY] created_at_ts={AGE_SOURCE_STATS.get('created_at_ts', 0)} "
          f"visible_text={AGE_SOURCE_STATS['visible_text']} "
          f"synthetic_rank={AGE_SOURCE_STATS['synthetic_rank']} "
          f"unknown={AGE_SOURCE_STATS['unknown']} "
          f"synthetic_sent={AGE_SOURCE_STATS['synthetic_sent']} "
          f"visible_sent={AGE_SOURCE_STATS.get('visible_sent', 0)}")
    print(f"[DETAIL_AGE_SUMMARY] checked={DETAIL_AGE_STATS['checked']} "
          f"parsed={DETAIL_AGE_STATS['parsed']} "
          f"blocked_stale={DETAIL_AGE_STATS['blocked_stale']} "
          f"blocked_unverified={DETAIL_AGE_STATS['blocked_unverified']} "
          f"allowed_grail_unverified={DETAIL_AGE_STATS['allowed_grail_unverified']}")
    print(f"[SAFEGUARD_SUMMARY] retried={SAFEGUARD_STATS['retried']} "
          f"added={SAFEGUARD_STATS.get('added', 0)} "
          f"passed_presend={SAFEGUARD_STATS['passed_presend']} "
          f"blocked_presend={SAFEGUARD_STATS['blocked_presend']} "
          f"sent={SAFEGUARD_STATS['sent']} "
          f"limit_skipped={SAFEGUARD_STATS['limit_skipped']}")
    print(f"[RAW_STYLE_BLOCK_SUMMARY] total={RAW_STYLE_BLOCK_STATS['total']} "
          f"by_reason={RAW_STYLE_BLOCK_STATS['by_reason']} "
          f"top_blocked={RAW_STYLE_BLOCK_STATS['top_blocked']}")
    suppressed = VERBOSE_LOG_STATS["suppressed"]
    total_suppressed = sum(int(v or 0) for v in suppressed.values())
    print(f"[VERBOSE_LOG_SUPPRESSED] age_source={suppressed.get('age_source', 0)} "
          f"size_parse={suppressed.get('size_parse', 0)} "
          f"safeguard_blocks={suppressed.get('safeguard_blocks', 0)} "
          f"raw_style_blocks={suppressed.get('raw_style_blocks', 0)} "
          f"audit_seen={suppressed.get('audit_seen', 0)} "
          f"total_suppressed={total_suppressed}")


def print_candidate_audit_summary():
    if not CANDIDATE_AUDIT_ENABLED:
        return
    summary = (f"[AUDIT_SUMMARY] cycle={AUDIT_CURRENT_CYCLE} "
               f"seen={AUDIT_STATS['seen']} raw_checked={AUDIT_STATS['raw_checked']} "
               f"raw_candidates={AUDIT_STATS['raw_candidates']} raw_sent={AUDIT_STATS['raw_sent']} "
               f"main_candidates={AUDIT_STATS['main_candidates']} main_sent={AUDIT_STATS['main_sent']} "
               f"blocked={AUDIT_STATS['blocked']} top_block_reasons={AUDIT_STATS['top_block_reasons']} "
               f"top_queries={AUDIT_STATS['top_queries']}")
    print(summary)
    for event in AUDIT_TOP_BLOCKED[:10]:
        print(f"[AUDIT_TOP_BLOCKED] score={event.get('score')} bucket={event.get('bucket')} "
              f"reason={event.get('block_reason')} query={event.get('query')} "
              f"title={str(event.get('title') or '')[:70]}")
    for event in AUDIT_TOP_NOT_SENT[:10]:
        print(f"[AUDIT_TOP_NOT_SENT] score={event.get('score')} bucket={event.get('bucket')} "
              f"reason={event.get('block_reason') or event.get('stage')} query={event.get('query')} "
              f"title={str(event.get('title') or '')[:70]}")
    if CANDIDATE_AUDIT_TELEGRAM_SUMMARY:
        send_message(
            "🧾 AUDIT SUMMARY\n"
            f"cycle={AUDIT_CURRENT_CYCLE}\n"
            f"seen={AUDIT_STATS['seen']} raw_checked={AUDIT_STATS['raw_checked']}\n"
            f"raw_candidates={AUDIT_STATS['raw_candidates']} raw_sent={AUDIT_STATS['raw_sent']}\n"
            f"main_candidates={AUDIT_STATS['main_candidates']} main_sent={AUDIT_STATS['main_sent']}\n"
            f"blocked={AUDIT_STATS['blocked']}"
        )


def log_decision_trace(item: dict, result: dict, source: str, presend_reason: str = "pass", send_status: str = "success"):
    if result.get("_visible_age_source") or result.get("age_source"):
        age_info = {
            "source": result.get("_visible_age_source") or result.get("age_source"),
            "minutes": result.get("_visible_age_minutes") if result.get("_visible_age_minutes") is not None else result.get("age_min"),
            "usable_for_freshness": bool(result.get("_age_usable_for_freshness")),
        }
    else:
        age_info = get_item_age_info(item)
    signals = result.get("_raw_style_presend_reasons") or validated_real_signal_reasons(item, result)
    query = (item.get("_search_meta") or {}).get("name") or "unknown"
    print(f"[DECISION_TRACE] id={item.get('id')} query={query} source={source} "
          f"age_source={age_info.get('source')} age_min={age_info.get('minutes')} "
          f"usable_freshness={age_info.get('usable_for_freshness')} "
          f"real_signals={signals[:5]} engine={result.get('engine')} "
          f"bucket={result.get('raw_style_bucket') or result.get('taste_bucket') or result.get('tier')} "
          f"score={result.get('raw_style_score') or result.get('taste_watch_score') or result.get('final_score')} "
          f"presend_reason={presend_reason} "
          f"send_status={send_status} "
          f"final_reason={result.get('reason') or result.get('_quality_block_reason') or result.get('raw_style_block_reason')} "
          f"title={str(item.get('title') or '')[:80]}")


def is_core_search(search: dict) -> bool:
    if search.get("core_search") is True:
        return True
    name = raw_normalize_text(search.get("name") or search.get("query") or "")
    layer = raw_normalize_text(search.get("layer") or "")
    if layer == "grail":
        return True
    core_terms = [
        "taste discovery", "carhartt", "harley", "bape", "stussy",
        "single stitch", "made in usa", "screen stars", "fruit of the loom",
    ]
    return any(raw_contains_phrase(name, term) for term in core_terms)


def query_coverage_record(name: str) -> dict:
    return QUERY_COVERAGE.setdefault(name or "unknown", {
        "last_checked_at": None,
        "seconds_since_last_check": None,
        "items_seen": 0,
        "candidates_created": 0,
        "alerts_sent": 0,
        "blocked_count": 0,
        "core": False,
        "checked_this_cycle": False,
        "skipped_this_cycle": False,
    })


def print_query_coverage_summary():
    core_checked = core_skipped = peripheral_checked = peripheral_skipped = 0
    oldest_core_since = 0
    for name, data in QUERY_COVERAGE.items():
        if data.get("core"):
            core_checked += 1 if data.get("checked_this_cycle") else 0
            core_skipped += 1 if data.get("skipped_this_cycle") else 0
            oldest_core_since = max(oldest_core_since, int(data.get("seconds_since_last_check") or 0))
        else:
            peripheral_checked += 1 if data.get("checked_this_cycle") else 0
            peripheral_skipped += 1 if data.get("skipped_this_cycle") else 0
        print(f"[QUERY_COVERAGE] name={name} since_last={data.get('seconds_since_last_check')} "
              f"seen={data.get('items_seen', 0)} candidates={data.get('candidates_created', 0)} "
              f"sent={data.get('alerts_sent', 0)} blocked={data.get('blocked_count', 0)}")
        data["checked_this_cycle"] = False
        data["skipped_this_cycle"] = False
        data["items_seen"] = 0
        data["candidates_created"] = 0
        data["alerts_sent"] = 0
        data["blocked_count"] = 0
    print(f"[QUERY_COVERAGE_SUMMARY] core_checked={core_checked} core_skipped={core_skipped} "
          f"peripheral_checked={peripheral_checked} peripheral_skipped={peripheral_skipped} "
          f"oldest_core_since_last={oldest_core_since}")


def find_audit_matches(search_text: str, limit=20):
    needle = raw_normalize_text(search_text)
    if not needle:
        print("[AUDIT_LOOKUP] empty_search")
        return []
    matches = []
    try:
        with open(CANDIDATE_AUDIT_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if needle in raw_normalize_text(event.get("title") or ""):
                    matches.append(event)
    except Exception as e:
        print(f"[AUDIT_LOOKUP_ERROR] error={e}")
        return []
    for event in matches[-limit:]:
        print(f"[AUDIT_LOOKUP] seen={bool(event)} query={event.get('query')} "
              f"stage={event.get('stage')} score={event.get('score')} "
              f"block_reason={event.get('block_reason')} sent={event.get('sent')} "
              f"title={str(event.get('title') or '')[:80]}")
    return matches[-limit:]


def get_vinted_thumb(item_url, item_id):
    return None


_last_tg_send   = 0.0
TG_MIN_INTERVAL = 2.0


def send_message(text, photo_url=None, item_link=None):
    global _last_tg_send, LAST_TELEGRAM_STATUS, LAST_TELEGRAM_ERROR
    import json as _json
    tg_base = f"https://api.telegram.org/bot{TOKEN}"
    LAST_TELEGRAM_STATUS = None
    LAST_TELEGRAM_ERROR = ""

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
        last_response = None

        if photo_url:
            data = {"chat_id": CHAT_ID, "photo": photo_url, "caption": clean[:1024]}
            if reply_markup:
                data["reply_markup"] = reply_markup
            r = requests.post(f"{tg_base}/sendPhoto", data=data, timeout=15)
            last_response = r
            LAST_TELEGRAM_STATUS = r.status_code
            if VERBOSE_ITEM_DEBUG:
                print(f"[TELEGRAM] status={r.status_code} body={r.text[:200]}")
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
            last_response = r
            LAST_TELEGRAM_STATUS = r.status_code
            if VERBOSE_ITEM_DEBUG:
                print(f"[TELEGRAM] status={r.status_code} body={r.text[:200]}")
            if r.status_code == 429:
                time.sleep(5)
                r = requests.post(f"{tg_base}/sendMessage", data=data, timeout=10)
                last_response = r
                LAST_TELEGRAM_STATUS = r.status_code
                if VERBOSE_ITEM_DEBUG:
                    print(f"[TELEGRAM] status={r.status_code} body={r.text[:200]}")

        _last_tg_send = time.time()
        if last_response is not None and last_response.status_code != 200:
            LAST_TELEGRAM_ERROR = str(last_response.text[:200])
        return bool(last_response and last_response.status_code == 200)

    except Exception as e:
        LAST_TELEGRAM_ERROR = str(e)
        print(f"Błąd wysyłania: {e}")
        return False

# ─────────────────────────────────────────
#  💰 WYCIĄGANIE CENY
# ─────────────────────────────────────────
def send_alert_message(text, item: dict, result: dict, source: str, key: str, photo_url=None, item_link=None) -> bool:
    title = str((item or {}).get("title") or "")[:60]
    print(f"[SEND_ATTEMPT] source={source} key={key} title={title}")
    ok = send_message(text, photo_url=photo_url, item_link=item_link)
    if ok:
        print(f"[SEND_SUCCESS] source={source} key={key} telegram_status={LAST_TELEGRAM_STATUS or 200} title={title}")
        return True
    error = LAST_TELEGRAM_ERROR or "send_message_returned_false"
    print(f"[SEND_FAIL] source={source} key={key} status={LAST_TELEGRAM_STATUS} error={str(error)[:160]} title={title}")
    return False


TITLE_NOISE_WORDS = [
    "swag", "drip", "opium", "archive", "avantgarde", "rare unique",
    "hidden gem", "japanstyle", "y2k", "rap",
]

SIGNAL_LABELS = {
    "taste_old_blank_tag": "old blank tag",
    "taste_year_era": "rocznik / era vintage",
    "taste_good_resale_size": "dobry rozmiar",
    "taste_ok_resale_size": "sensowny rozmiar",
    "taste_price_<=30": "bardzo dobra cena",
    "taste_price_<=50": "dobra cena",
    "taste_price_<=80": "sensowna cena",
    "taste_visual_graphic": "mocny grafik",
    "vintage_blank_tag_signal": "old blank tag",
    "vintage_blank_graphic_combo": "blank tag + grafik",
    "pop_culture_graphic_signal": "pop culture graphic",
    "pop_culture_good_price": "dobra cena pop culture",
    "harley_dealer_location_graphic": "Harley dealer/location print",
    "harley_style_watch": "Harley graphic / biker vibe",
    "biker_event_graphic_signal": "biker/event graphic",
    "vintage_sports_college_signal": "vintage sports / college",
    "ralph_lauren_graphic_spellout": "Ralph Lauren graphic/spellout",
    "rrl_double_rl_mega_signal": "RRL / Double RL",
    "rrl_western_heritage_signal": "RRL western / heritage",
    "lee_vintage_workwear_jacket": "Lee vintage workwear",
    "carhartt_desirable_item": "Carhartt desirable model",
    "carhartt_good_pants_size": "dobry rozmiar Carhartt pants",
    "single_stitch": "single stitch",
    "made_in_usa": "Made in USA",
    "screen_stars": "Screen Stars tag",
    "nutmeg": "Nutmeg tag",
    "fruit_of_the_loom": "Fruit of the Loom tag",
    "raw_style_old_blank": "old blank / vintage tag",
    "raw_style_pop_culture": "pop culture",
    "raw_style_biker": "biker / Harley vibe",
    "raw_style_sports": "vintage sports",
    "raw_style_streetwear": "streetwear",
    "raw_style_workwear": "workwear / heritage",
    "raw_style_metal": "metal / band graphic",
    "fresh_low_price_style": "swiezy listing + dobra cena",
}


def clean_title(title: str) -> str:
    text = str(title or "")
    text = re.sub(r",?\s*(marka|stan|rozmiar):.*", "", text, flags=re.IGNORECASE)
    for word in TITLE_NOISE_WORDS:
        text = re.sub(rf"(?i)\b{re.escape(word)}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_,")
    return (text[:87] + "...") if len(text) > 90 else (text or "Item")


def humanize_signal(signal: str) -> str:
    raw = str(signal or "").strip()
    if not raw:
        return ""
    if ":" in raw:
        prefix, value = raw.split(":", 1)
        prefix_map = {
            "old_blank": "old blank / vintage tag",
            "pop": "pop culture",
            "biker": "biker / Harley vibe",
            "sports": "vintage sports",
            "streetwear": "streetwear",
            "workwear": "workwear / heritage",
            "metal": "metal / band graphic",
            "visual": "mocny grafik",
            "era": "rocznik / era vintage",
            "size": "dobry rozmiar",
            "price": "dobra cena",
            "fresh": "swiezy listing",
        }
        if prefix in prefix_map:
            if prefix in {"old_blank", "pop", "biker", "sports", "streetwear", "workwear", "metal"} and value:
                return f"{prefix_map[prefix]}: {value.replace('_', ' ')}"
            return prefix_map[prefix]
    if raw in SIGNAL_LABELS:
        return SIGNAL_LABELS[raw]
    cleaned = raw
    for prefix in ("taste_", "raw_style_", "signal_"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned.replace("_", " ")[:42]


def _alert_type(result: dict, fallback: str | None = None) -> str:
    if fallback:
        return fallback
    if result.get("engine") == "RAW_STYLE":
        return "RAW_STYLE"
    if result.get("style_watch_sent"):
        return "STYLE_WATCH"
    engine_name = result.get("engine")
    if engine_name == "GRAIL" or result.get("is_grail"):
        return "GRAIL"
    if engine_name == "BRAND":
        return "BRAND"
    if engine_name == "CHAOS":
        return "FLIP"
    if result.get("taste_watch_candidate"):
        return "STYLE_WATCH"
    return "ITEM"


def _alert_meta(alert_type: str) -> dict:
    return {
        "GRAIL": ("💎 GRAIL FIND", "Grail score", "Mocny kandydat - sprawdz szybko"),
        "RAW_STYLE": ("⚡ RAW STYLE SNIPE", "Style score", "Swieze + w Twoim stylu - kliknij szybko"),
        "STYLE_WATCH": ("👀 STYLE WATCH", "Taste score", "Warto zobaczyc, niekoniecznie instant buy"),
        "FLIP": ("🔥 FLIP ALERT", "Flip score", "Potencjalny flip - sprawdz stan i cene"),
        "BRAND": ("🔵 BRAND FIND", "Brand score", "Marka/model do sprawdzenia"),
        "ITEM": ("📌 ITEM ALERT", "Score", "Warto sprawdzic"),
    }.get(alert_type, ("📌 ITEM ALERT", "Score", "Warto sprawdzic"))


def _item_age_label(item: dict, result: dict) -> str:
    age_source = result.get("age_source") or result.get("_visible_age_source")
    if age_source == "synthetic_rank":
        return "?"
    age = result.get("age_min") or item.get("age_min")
    if age is None:
        age = parse_item_age_minutes(item)
    try:
        age_int = int(age)
        return f"{age_int} min" if age_int < 360 else "?"
    except Exception:
        return "?"


def _score_for_alert(result: dict, alert_type: str):
    if alert_type == "RAW_STYLE":
        score = result.get("raw_style_score") or result.get("taste_watch_score") or result.get("final_score")
    elif alert_type == "STYLE_WATCH":
        score = result.get("taste_watch_score") or result.get("raw_style_score") or result.get("final_score")
    elif alert_type == "GRAIL":
        score = result.get("final_score") or result.get("signal_quality_score") or result.get("grail_score")
    else:
        score = result.get("final_score") or result.get("signal_quality_score")
    try:
        return min(100, max(0, round(float(score))))
    except Exception:
        return None


def _telegram_reasons(item: dict, result: dict, alert_type: str) -> list[str]:
    signals = []
    for key in ("desirable_signals", "taste_signals", "raw_style_signals"):
        val = result.get(key) or []
        if isinstance(val, str):
            val = [val]
        signals.extend(val)
    labels = []
    for sig in signals:
        label = humanize_signal(sig)
        if label and label not in labels and not label.startswith("_"):
            labels.append(label)
    title_l = str(item.get("title") or "").lower()
    if "screen stars" in title_l and "Screen Stars tag" not in labels:
        labels.append("Screen Stars tag")
    if "single stitch" in title_l and "single stitch" not in labels:
        labels.append("single stitch")
    if "made in usa" in title_l and "Made in USA" not in labels:
        labels.append("Made in USA")
    if (result.get("effective_price") or 0) and "negocjacyjna cena" not in labels:
        labels.append("negocjacyjna cena")
    if _item_age_label(item, result) != "?" and "swiezy listing" not in labels:
        labels.append("swiezy listing")
    priority = {
        "rrl": 0, "carhartt": 0, "harley": 0, "lee": 0, "ralph": 0,
        "screen": 1, "single": 1, "made": 1, "old blank": 1, "vintage": 1,
        "graphic": 2, "grafik": 2, "pop culture": 2, "biker": 2,
        "rozmiar": 3, "cena": 4, "swiezy": 4,
    }
    labels.sort(key=lambda x: min((v for k, v in priority.items() if k in x.lower()), default=9))
    return labels[:5] or ["ciekawy sygnal", "warto sprawdzic"]


def _type_label(result: dict, alert_type: str) -> str:
    label = (
        result.get("raw_style_bucket")
        or result.get("taste_bucket")
        or result.get("category")
        or result.get("tier")
        or alert_type.lower()
    )
    return str(label).replace("_", " ").lower()


def format_telegram_alert(item: dict, result: dict, alert_type: str | None = None) -> str:
    item = item or {}
    result = result or {}
    alert_type = _alert_type(result, alert_type)
    header, score_label, decision = _alert_meta(alert_type)
    title = clean_title(item.get("title", ""))
    price = item.get("price")
    link = item.get("link") or item.get("url") or ""
    size = item.get("size") or result.get("size")
    age = _item_age_label(item, result)
    score = _score_for_alert(result, alert_type)
    effective_price = result.get("effective_price")
    estimated_value = result.get("estimated_value") or result.get("market_price") or item.get("market_price") or result.get("resale_value")
    profit = result.get("profit") or result.get("estimated_profit")

    lines = [header, "━━━━━━━━━━━━━━", f"📦 {title}", ""]
    try:
        if price:
            lines.append(f"💰 Cena: {float(price):.0f} zł")
    except Exception:
        lines.append(f"💰 Cena: {price}")
    try:
        if effective_price is not None and price and float(effective_price) < float(price):
            lines.append(f"🤝 Po negocjacji: ~{float(effective_price):.0f} zł")
    except Exception:
        pass
    if alert_type == "FLIP":
        try:
            if estimated_value:
                lines.append(f"📈 Wycena: ~{float(estimated_value):.0f} zł")
            if profit:
                lines.append(f"🟢 Potencjał: +{float(profit):.0f} zł")
        except Exception:
            pass
    if size:
        lines.append(f"📏 Rozmiar: {size}")
    age_source = result.get("age_source") or result.get("_visible_age_source")
    if age_source == "synthetic_rank":
        lines.append("⏱️ Świeżość: brak danych")
    elif age != "?":
        lines.append(f"⏱️ Dodane: {age}")
    if score is not None:
        lines.append(f"🎯 {score_label}: {score}/100")
    reasons = _telegram_reasons(item, result, alert_type)
    lines.extend(["", "✅ Dlaczego warto:"])
    lines.extend([f"• {reason}" for reason in reasons])
    lines.extend(["", f"🏷️ Typ: {_type_label(result, alert_type)}", f"🧠 Decyzja: {decision}"])
    if link:
        lines.extend(["", "🔗 Otwórz na Vinted:", str(link)])
    return "\n".join(lines)


def send_telegram_photo(chat_id, photo_path_or_url, caption) -> bool:
    tg_base = f"https://api.telegram.org/bot{TOKEN}"
    try:
        data = {"chat_id": chat_id, "caption": caption[:1024]}
        if str(photo_path_or_url).startswith(("http://", "https://")):
            data["photo"] = photo_path_or_url
            r = requests.post(f"{tg_base}/sendPhoto", data=data, timeout=15)
        else:
            with open(photo_path_or_url, "rb") as fh:
                r = requests.post(f"{tg_base}/sendPhoto", data=data, files={"photo": fh}, timeout=20)
        print(f"[TELEGRAM] status={r.status_code} body={r.text[:200]}")
        if r.status_code == 200:
            print("[STARTUP_IMAGE_SENT]")
            return True
        print(f"[STARTUP_IMAGE_ERROR] error=status_{r.status_code}")
        return False
    except Exception as e:
        print(f"[STARTUP_IMAGE_ERROR] error={e}")
        return False


def build_startup_message() -> str:
    raw_status = "ON" if RAW_STYLE_SNIPER_ENABLED else "OFF"
    watch_enabled = os.getenv("TASTE_WATCH_ENABLED", "1") == "1" or os.getenv("TASTE_WATCH_SEND_ENABLED", "1") == "1"
    watch_status = "ON" if watch_enabled else "OFF"
    grail_status = "ON"
    flip_status = "ON"
    if STARTUP_MESSAGE_COMPACT:
        return (
            "💎 HIDDEN GEM — RADAR ACTIVE\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "👁️ Skanuję Vinted\n"
            f"🔍 Wyszukiwań: {len(SEARCHES)}\n"
            f"⚡ RAW Style: {raw_status}\n"
            f"💎 Grail: {grail_status}\n"
            f"👀 Watch: {watch_status}\n\n"
            "🎯 Vintage / archive / pop culture / workwear\n\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    return (
        "💎 HIDDEN GEM RADAR — ONLINE\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👁️ Skanuję Vinted w tle\n"
        f"🔍 Wyszukiwań: {len(SEARCHES)}\n"
        f"⚡ RAW Style Sniper: {raw_status}\n"
        f"👀 Style Watch: {watch_status}\n"
        f"💎 Grail Engine: {grail_status}\n"
        f"🔥 Flip Engine: {flip_status}\n\n"
        "📦 Kategorie:\n"
        "• Vintage tees / old blanks\n"
        "• Harley / biker graphics\n"
        "• Pop culture / Star Wars / Warner Bros\n"
        "• Workwear / Carhartt / Lee\n"
        "• Sports / college / MLB / NFL\n"
        "• RRL / Ralph heritage\n\n"
        "🎯 Cel:\n"
        "Świeże, tanie i stylowe rzeczy zanim znikną.\n\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


def send_startup_message():
    caption = build_startup_message()
    if STARTUP_IMAGE_ENABLED:
        photo_ref = ""
        if STARTUP_IMAGE_PATH:
            candidates = [STARTUP_IMAGE_PATH]
            if not os.path.isabs(STARTUP_IMAGE_PATH):
                candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), STARTUP_IMAGE_PATH))
            for candidate in candidates:
                if os.path.exists(candidate):
                    photo_ref = candidate
                    break
            if not photo_ref and not STARTUP_IMAGE_URL:
                print("[STARTUP_IMAGE_FALLBACK] reason=missing_file")
        if not photo_ref and STARTUP_IMAGE_URL:
            photo_ref = STARTUP_IMAGE_URL
        if photo_ref:
            if send_telegram_photo(CHAT_ID, photo_ref, caption):
                return
            print("[STARTUP_IMAGE_FALLBACK] reason=send_error")
    send_message(caption)


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
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🌐 REQUEST SCHEDULING LAYER — human-like behavior
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Req 9 — real browser User-Agent pool (desktop + mobile mix)
USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Req 9 — Accept-Language variants
_ACCEPT_LANGS = [
    "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "pl-PL,pl;q=0.9,en;q=0.8",
    "pl,en-US;q=0.9,en;q=0.8",
    "pl-PL,pl;q=0.8,en-GB;q=0.7,en;q=0.6",
    "en-US,en;q=0.9,pl;q=0.8",
]

# Req 1 — Variable base delay: 8–20s base, 10% spike 25–40s
VINTED_DELAY_BASE_MIN  = 8.0
VINTED_DELAY_BASE_MAX  = 20.0
VINTED_DELAY_SPIKE_MIN = 25.0
VINTED_DELAY_SPIKE_MAX = 40.0
VINTED_DELAY_SPIKE_PCT = 0.10    # 10% chance of spike

# Req 4 — Thinking pauses between searches
THINKING_PAUSE_MIN     = 15.0
THINKING_PAUSE_MAX     = 45.0
THINKING_PAUSE_LONG_MIN= 60.0
THINKING_PAUSE_LONG_MAX= 120.0
THINKING_PAUSE_LONG_PCT= 0.15   # 15% chance of long pause

# Req 5 — Cycle break
CYCLE_BREAK_MIN        = 120.0  # 2 min
CYCLE_BREAK_MAX        = 300.0  # 5 min
CYCLE_BREAK_LONG_MIN   = 300.0  # 5 min
CYCLE_BREAK_LONG_MAX   = 600.0  # 10 min
CYCLE_BREAK_LONG_PCT   = 0.20   # 20% chance of extended break

# Req 7 — 403 retry config
_consecutive_403       = 0
_cycle_403_stop        = False   # flag: stop cycle after 3rd failure
_403_RETRY_WAITS       = [
    (20.0, 40.0),    # 1st retry wait range
    (60.0, 120.0),   # 2nd retry wait range
]
_403_HARD_STOP         = 3       # 3rd failure → stop cycle + long sleep
_403_HARD_STOP_MIN     = 300.0   # 5 min
_403_HARD_STOP_MAX     = 600.0   # 10 min

# Req 8 — Session refresh config
_last_session_refresh  = 0.0
_SESSION_REFRESH_MIN_INTERVAL = 600.0   # 10 min
_SESSION_REFRESH_MAX_INTERVAL = 900.0   # 15 min
_next_session_refresh  = random.uniform(600.0, 900.0)

# Req 12 — Rate limit safety
_request_timestamps: list = []
RATE_LIMIT_MAX_RPM     = 12     # max 12 requests/minute
RATE_LIMIT_WINDOW      = 60.0
RATE_LIMIT_COOLDOWN_MIN= 60.0
RATE_LIMIT_COOLDOWN_MAX= 120.0

# Req 10 — Micro delays after item processing
ITEM_MICRO_DELAY_MIN   = 2.0
ITEM_MICRO_DELAY_MAX   = 6.0
ITEM_IDLE_PCT          = 0.15   # 15% chance of idle simulation
ITEM_IDLE_MIN          = 5.0
ITEM_IDLE_MAX          = 15.0

VINTED_429_WAIT = 180


def _human_delay(label: str = "") -> float:
    """
    Req 1+11 — Generuje human-like delay z jitterem.
    Każdy request MUSI mieć delay. Nigdy request→request bez przerwy.
    """
    if random.random() < VINTED_DELAY_SPIKE_PCT:
        delay = random.uniform(VINTED_DELAY_SPIKE_MIN, VINTED_DELAY_SPIKE_MAX)
        print(f"  [REQUEST] delay={delay:.1f}s (spike) search={label}")
    else:
        delay = random.uniform(VINTED_DELAY_BASE_MIN, VINTED_DELAY_BASE_MAX)
        print(f"  [REQUEST] delay={delay:.1f}s search={label}")
    time.sleep(delay)
    return delay


def _thinking_pause(after: str = "") -> float:
    """
    Req 4 — Human-like pause between searches (15–45s, 15% chance 60–120s).
    """
    if random.random() < THINKING_PAUSE_LONG_PCT:
        pause = random.uniform(THINKING_PAUSE_LONG_MIN, THINKING_PAUSE_LONG_MAX)
        print(f"  [SEARCH] thinking_pause={pause:.0f}s (long) after={after}")
    else:
        pause = random.uniform(THINKING_PAUSE_MIN, THINKING_PAUSE_MAX)
        print(f"  [SEARCH] thinking_pause={pause:.0f}s after={after}")
    time.sleep(pause)
    return pause


def _check_rate_limit():
    """Req 12 — Enforce max RPM. Force cooldown if exceeded."""
    global _request_timestamps
    now = time.time()
    _request_timestamps = [t for t in _request_timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(_request_timestamps) >= RATE_LIMIT_MAX_RPM:
        cooldown = random.uniform(RATE_LIMIT_COOLDOWN_MIN, RATE_LIMIT_COOLDOWN_MAX)
        print(f"  ⚠️ [RATE_LIMIT] RPM={len(_request_timestamps)} ≥ {RATE_LIMIT_MAX_RPM} "
              f"→ cooldown {cooldown:.0f}s")
        time.sleep(cooldown)
        _request_timestamps.clear()
    _request_timestamps.append(now)


def _maybe_refresh_session():
    """Req 8 — Refresh session only when needed (not aggressively)."""
    global _last_session_refresh, _next_session_refresh
    elapsed = time.time() - _last_session_refresh
    if elapsed >= _next_session_refresh:
        refresh_session()
        _last_session_refresh   = time.time()
        _next_session_refresh   = random.uniform(
            _SESSION_REFRESH_MIN_INTERVAL, _SESSION_REFRESH_MAX_INTERVAL
        )
        print(f"  [SESSION] next refresh in {_next_session_refresh:.0f}s")


def get_headers() -> dict:
    """Req 9 — Randomise User-Agent, Accept-Language and minor headers per request."""
    ua   = random.choice(USER_AGENTS)
    lang = random.choice(_ACCEPT_LANGS)
    # Minor header variations
    dnt  = random.choice(["1", "0", None])
    headers = {
        "User-Agent":      ua,
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": lang,
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":  "document",
        "Sec-Fetch-Mode":  "navigate",
        "Sec-Fetch-Site":  random.choice(["none", "same-origin"]),
        "Cache-Control":   random.choice(["max-age=0", "no-cache"]),
    }
    if dnt:
        headers["DNT"] = dnt
    # Random Sec-CH-UA hint (Chrome only)
    if "Chrome" in ua:
        ver = re.search(r'Chrome/(\d+)', ua)
        if ver:
            v = ver.group(1)
            headers["Sec-CH-UA"] = f'"Chromium";v="{v}", "Google Chrome";v="{v}"'
    return headers


def vinted_fetch(url: str, label: str = "") -> "requests.Response | None":
    """
    Req 1+7+11+12 — Human-like request with:
    - mandatory pre-request delay (anti-burst)
    - rate limit check
    - 3-attempt 403 retry with escalating waits
    - hard stop on 3rd failure → long sleep + session refresh
    """
    global _consecutive_403, _cycle_403_stop

    # Req 12 — rate limit guard
    _check_rate_limit()

    # Req 11 — ANTI-BURST: mandatory delay before every request
    _human_delay(label)

    for attempt in range(1, 4):   # max 3 attempts (Req 7)
        try:
            host = urlparse(url).netloc or "unknown"
            print(f"[REQUEST_CONTEXT] label={label} detail_age_enabled={1 if DETAIL_AGE_VERIFY_ENABLED else 0} url_host={host}")
            r = requests.get(url, headers=get_headers(), timeout=15)

            if r.status_code == 200:
                _consecutive_403 = 0
                return r

            if r.status_code == 429:
                wait = VINTED_429_WAIT * attempt
                print(f"  🚫 429 [{label}] — czekam {wait}s (próba {attempt}/3)")
                time.sleep(wait)
                continue

            if r.status_code in (403, 401):
                _consecutive_403 += 1

                if attempt <= 2:
                    # Req 7 — escalating retry waits
                    wait_range = _403_RETRY_WAITS[attempt - 1]
                    wait = random.uniform(*wait_range)
                    print(f"  [403] retry={attempt}/3 "
                          f"cooldown={wait:.0f}s "
                          f"consecutive={_consecutive_403} "
                          f"search={label}")
                    time.sleep(wait)
                    continue
                else:
                    # Req 7 — 3rd failure: HARD STOP
                    stop_sleep = random.uniform(_403_HARD_STOP_MIN, _403_HARD_STOP_MAX)
                    print(f"  [403] retry=3/3 HARD STOP → "
                          f"cycle stop + sleep {stop_sleep:.0f}s + session refresh "
                          f"search={label}")
                    _cycle_403_stop = True
                    time.sleep(stop_sleep)
                    _maybe_refresh_session()
                    _consecutive_403 = 0
                    return None

            print(f"  ⚠️ HTTP {r.status_code} [{label}]")
            return None

        except requests.exceptions.Timeout:
            print(f"  ⚠️ Timeout [{label}] próba {attempt}/3")
            time.sleep(random.uniform(10, 20))
        except Exception as e:
            print(f"  ⚠️ Request error [{label}]: {e}")
            time.sleep(random.uniform(5, 15))

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
                        ts_final = None

                        # Fix #6 — debug: raz pokaż klucze pierwszego itemu żeby wiedzieć
                        # jakie pola zwraca Vinted (pomaga wykryć właściwe pole czasu)
                        if len(seen_ids) == 1 and not items:
                            ts_keys = [k for k in entry.keys()
                                       if any(t in k.lower() for t in
                                              ["time", "date", "at", "ts", "push", "create", "update", "active"])]
                            if ts_keys:
                                print(f"  🕐 Vinted TS fields: {ts_keys} | vals: {[entry.get(k) for k in ts_keys[:4]]}")
                                print("  🕐 ts_final zostanie policzony po parsowaniu pola czasu")
                            else:
                                print(f"  ⚠️  Vinted NIE zwraca pola z czasem — używam syntetycznego wieku (rank-based)")
                                print(f"  🕐 Vinted keys (first 10): {list(entry.keys())[:10]}")

                        title = entry.get("title", "") or entry.get("name", "") or ""
                        url   = entry.get("url", "") or f"https://www.vinted.pl/items/{item_id}"
                        if not url.startswith("http"):
                            url = "https://www.vinted.pl" + url

                        # Fix #6 — Vinted używa różnych nazw pola czasu w zależności od endpointu
                        created = (
                            entry.get("created_at_ts") or
                            entry.get("created_at") or
                            entry.get("last_push_up_at") or
                            entry.get("last_push_up_at_ts") or
                            entry.get("updated_at_ts") or
                            entry.get("updated_at") or
                            entry.get("pushed_up_at") or
                            entry.get("active_at") or
                            0
                        )

                        # Spróbuj też ISO string: "2024-01-15T12:34:56+00:00"
                        ts_final = None
                        if created:
                            try:
                                ts = float(str(created).replace(",", ""))
                                ts_final = ts / 1000 if ts > 1e12 else ts
                            except (ValueError, TypeError):
                                # Spróbuj jako ISO string
                                try:
                                    from datetime import datetime, timezone
                                    s = str(created).replace("Z", "+00:00")
                                    dt = datetime.fromisoformat(s)
                                    ts_final = dt.timestamp()
                                except:
                                    pass
                        if len(seen_ids) == 1 and not items and DEBUG_PIPELINE:
                            print(f"[PARSE_TS] item_id={item_id} ts_final={ts_final}")

                        # Filtr czasu — tylko oferty z ostatnich 24h (gdy mamy ts)
                        if ts_final:
                            age_hours = (time.time() - ts_final) / 3600
                            if age_hours > 24:
                                continue

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
                            raw_card_text = " ".join(
                                str(v) for v in [
                                    entry.get("age"), entry.get("age_text"), entry.get("time_ago"),
                                    entry.get("created_at_text"), entry.get("added"), entry.get("added_text"),
                                    entry.get("date"), entry.get("subtitle")
                                ] if v is not None
                            )
                            items.append({
                                "id":            item_id,
                                "title":         title,
                                "price":         price,
                                "url":           url,
                                "photo":         photo_url,
                                "created_at_ts": ts_final,   # None gdy Vinted nie zwraca ts
                                "age":           entry.get("age"),
                                "age_text":      entry.get("age_text") or entry.get("time_ago") or entry.get("created_at_text"),
                                "created_at_text": entry.get("created_at_text") or entry.get("created_at"),
                                "added":         entry.get("added"),
                                "added_text":    entry.get("added_text"),
                                "date":          entry.get("date"),
                                "subtitle":      entry.get("subtitle"),
                                "metadata":      entry.get("metadata") or entry.get("meta"),
                                "raw_card_text": raw_card_text,
                                "_rank":         len(items),  # pozycja na liście (do synth-age)
                            })
                    except Exception as e:
                        if DEBUG_PIPELINE:
                            _item_id = locals().get("item_id", "?")
                            _title = locals().get("title", "")
                            print(f"[PARSE_ITEM_ERROR] error={e} item_id={_item_id} title={_title[:80] if _title else '?'}")
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
                    "created_at_ts": None,
                    "raw_card_text": tag.get_text(" ", strip=True),
                    "_rank": len(items),
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
                p = photos[0]
                url = p.get("full_size_url") or p.get("url") or p.get("thumb_url")
                if url:
                    return url
    except:
        pass
    return None


def get_item_details(item_url):
    """
    Pobiera (photo_url, description) dla oferty.
    Używane w hidden_gem_mode do analizy AI.
    Zwraca (None, None) przy błędzie.
    """
    try:
        r = vinted_fetch(item_url, label="item_details")
        if not r:
            return None, None
        from bs4 import BeautifulSoup as _BS
        soup = _BS(r.text, "html.parser")
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

    # 2. Odrzuć oczywiste śmieci (tylko to co NA PEWNO nie jest koszulką piłkarską)
    NOISE = [
        "swag", "avant garde", "coquette", "drippy",
        "gorset", "spódniczk", "koronkow", "halter", "babydoll",
        "alt alternative", "japan style",
        "sukienk", "kurtka jeans",
        "racing", "motocycl", "moto ",   # koszulki motosportowe
        "baseball cap", "czapka",
    ]
    for noise in NOISE:
        if noise in text:
            return False, [f"odrzucono: {noise.strip()}"]

    # 3. Musi zawierać słowo związane z koszulką/jerseyem
    JERSEY_WORDS = [
        "koszulka", "jersey", "shirt", "trikot", "maillot",
        "fodboldtrøje", "voetbalshirt", "mez ", " mez",
        "tricou", "trøje", "tröja", "dres ", " kit",
        "football top", "soccer top", "piłkarska", "pilkarska",
        "fotbal", "fútbol", "calcio",
    ]
    is_jersey = any(w in text for w in JERSEY_WORDS)
    if not is_jersey:
        return False, ["brak słowa koszulka/jersey/shirt"]

    # 4. Musi mieć markę LUB klub/reprezentację
    has_brand = any(b in text for b in FOOTBALL_ORIGINAL_BRANDS)
    has_club  = any(c in text for c in FOOTBALL_CLUBS)

    if not has_brand and not has_club:
        return False, ["brak marki piłkarskiej i klubu"]

    # 5. Retro LUB klub — jedno z dwóch wystarczy
    is_retro = any(d in text for d in RETRO_DECADES)

    # Jeśli ma konkretny klub → akceptuj nawet bez słowa "retro"
    if not is_retro and not has_club:
        return False, ["brak retro/vintage i brak konkretnego klubu"]

    reasons = []
    if has_brand:  reasons.append("✅ marka")
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
#  ⚡ SNIPER — pomocnicze funkcje czasu
# ─────────────────────────────────────────
def parse_item_age_minutes(item: dict) -> int | None:
    """
    Zwraca wiek oferty w minutach.

    Priorytet:
    1. created_at_ts — Unix timestamp z JSON Vinted (dokładny)
    2. _rank         — pozycja na liście newest_first → syntetyczny wiek
                       Vinted sortuje od najnowszego, więc pozycja 0 ≈ przed chwilą,
                       pozycja 95 ≈ kilka godzin temu.
                       Mapujemy: rank 0–5 → ~5 min, 6–20 → ~30 min, 21–50 → ~90 min,
                       51+ → ~180 min  (zawsze < 360 min, więc przechodzą filtr AGED)
    3. None          — tylko gdy brak obu (fallback HTML, brak rank)
    """
    ts = item.get("created_at_ts")
    if ts:
        try:
            age_sec = time.time() - float(ts)
            return max(0, int(age_sec / 60))
        except:
            pass

    # Syntetyczny wiek z pozycji na liście
    rank = item.get("_rank")
    if rank is not None:
        if rank <= 5:
            return 5          # ULTRA FRESH tier
        elif rank <= 20:
            return 30         # FRESH tier
        elif rank <= 50:
            return 90         # AGED tier — przejdzie jeśli grail/undervalue
        else:
            return 180        # AGED tier (6 godzin to 360, więc OK)

    return None


def parse_item_age_minutes_from_text(created_at_text: str) -> int:
    """
    Fallback — parsuje tekst w stylu '5 minutes ago', '2 hours ago'.
    """
    t = created_at_text.lower()
    nums = re.findall(r'\d+', t)
    if not nums:
        return 9999
    n = int(nums[0])
    if "min" in t:
        return n
    if "hour" in t or " h" in t:
        return n * 60
    if "day" in t:
        return n * 1440
    return 9999


# Part 4 — in-memory seen set (szybszy niż disk dla sniping)
_SNIPER_SEEN: dict[str, float] = {}   # FIX: dict z TTL zamiast set (wygasa po 6h)


# ─────────────────────────────────────────
#  🕵️ SPRAWDZANIE OFERT (HTML scraping)
# ─────────────────────────────────────────
def check_search(search, seen, market_price):
    global _CORE_SEARCH_ACTIVE
    _CORE_SEARCH_ACTIVE = is_core_search(search)
    found    = []
    all_ids  = []
    cnt_seen = cnt_price = cnt_kw = cnt_rejected = 0
    # Part 2 — pipeline metrics
    total_items     = 0
    processed_items = 0
    MAX_FOUND = MAX_ALERTS_PER_SEARCH * 2
    _seen_title_price: set[str] = set()

    try:
        r = vinted_fetch(search["url"], label=search["name"])
        if not r:
            return [], []

        items = parse_items_from_html(r.text)
        print(f"[{search['name']}] Ofert na stronie: {len(items)}")

        fallback_mode   = search.get("_fallback_mode", False)
        hard_cutoff_min = 120 if fallback_mode else 360

        tiered_items = []
        for it in items:
            age = parse_item_age_minutes(it)
            if age is None or age > hard_cutoff_min:
                continue
            tiered_items.append(it)

        if not tiered_items:
            print(f"  ⏰ Brak ofert w oknie {hard_cutoff_min} min [{search['name']}]")
            return [], []

        tiered_items.sort(key=lambda x: parse_item_age_minutes(x) or 9999)
        items = tiered_items

        for dbg in items[:2]:
            age_dbg = parse_item_age_minutes(dbg)
            age_str = f"{age_dbg}min" if age_dbg is not None else "?"
            print(f"  🔍 '{dbg['title'][:60]}' | {dbg['price']} zł | ⏱ {age_str}")

        # ── Req 2 — DYNAMIC DEPTH: pick how many items to process ──
        depth_name, max_items_this_run = pick_depth()
        if _CORE_SEARCH_ACTIVE:
            depth_name, max_items_this_run = "core", len(tiered_items)
        items = items[:max_items_this_run]
        print(f"  [DEPTH] depth={depth_name} max_items={max_items_this_run} "
              f"(available={len(tiered_items)})")

        # ── Req 7 — FAKE SCROLL before processing (simulate page scan) ──
        if not _CORE_SEARCH_ACTIVE:
            fake_scroll()

        # ── Req 3 — Load search profile ──────────────────────────────
        profile         = get_search_profile(search.get("name", ""))
        profile_active  = bool(profile.get("required_phrases") or
                               profile.get("exclude_phrases") or
                               profile.get("allowed_types") or
                               profile.get("exclude_brands"))

        # ── Filter metric counters ────────────────────────────────────
        cnt_profile_rej = 0
        cnt_vibe_skip   = 0
        reject_reasons: dict[str, int] = {}   # for [REJECT_REASON] log

        hidden_gem_mode = search.get("hidden_gem_mode", False)
        football_mode   = search.get("football_mode", False)
        lego_sw_mode    = search.get("lego_sw_mode", False)
        carhartt_mode   = search.get("carhartt_mode", False)

        # Track pass rate for safeguard logic
        _raw_candidates = 0  # items that reach profile check

        for item in items:
            if not item:
                continue
            total_items += 1

            # Req 1 — micro delay after EVERY item (human reading speed)
            # (applied at the end of the loop; put try/except around full block)
            try:
                item_id = item.get("id", "")
                title   = item.get("title", "")
                href    = item.get("url", "")
                price   = item.get("price")

                _now_sn = time.time()
                _sniper_ts = _SNIPER_SEEN.get(item_id)
                if _sniper_ts and (_now_sn - _sniper_ts) < 6 * 3600:
                    cnt_seen += 1
                    item_micro_delay(title)
                    continue
                _SNIPER_SEEN[item_id] = _now_sn
                if len(_SNIPER_SEEN) > 5000:
                    _cutoff = _now_sn - 6 * 3600
                    _SNIPER_SEEN_new = {k: v for k, v in _SNIPER_SEEN.items() if v > _cutoff}
                    _SNIPER_SEEN.clear()
                    _SNIPER_SEEN.update(_SNIPER_SEEN_new)

                age_min = parse_item_age_minutes(item)
                if age_min is not None and DEBUG_ALERTS:
                    print(f"  📤 NEW ITEM: {title[:60]} | age={age_min}min | {price} zł")

                seen_audit_item = dict(item)
                seen_audit_item["link"] = href
                seen_audit_item["url"] = href
                seen_audit_item["age_min"] = age_min
                seen_audit_item["_search_meta"] = {"name": search.get("name")}
                audit_candidate("seen", seen_audit_item, search)
                query_coverage_record(search.get("name"))["items_seen"] += 1
                verbose_item_log("audit_seen", f"[AUDIT_SEEN] query={search.get('name')} title={title[:60]}")

                if not item_id or not href:
                    audit_candidate("blocked", seen_audit_item, search, block_reason="missing_id_or_url")
                    item_micro_delay(title)
                    continue

                _seen_ts = seen.get(item_id)
                if _seen_ts and (time.time() - _seen_ts) < 6 * 3600:
                    cnt_seen += 1
                    audit_candidate("dedupe_skip", seen_audit_item, search, block_reason="seen_ttl")
                    item_micro_delay(title)
                    continue

                all_ids.append(item_id)

                if not title or not href:
                    audit_candidate("blocked", seen_audit_item, search, block_reason="missing_title_or_url")
                    item_micro_delay(title)
                    continue

                _dedup_key = f"{title.lower().strip()}_{int(price or 0)}"
                if _dedup_key in _seen_title_price:
                    cnt_seen += 1
                    audit_candidate("dedupe_skip", seen_audit_item, search, block_reason="duplicate_title_price_in_search")
                    item_micro_delay(title)
                    continue
                _seen_title_price.add(_dedup_key)

                title_lower = title.lower()
                if any(ex in title_lower for ex in GLOBAL_EXCLUDE):
                    audit_candidate("blocked", seen_audit_item, search, block_reason="global_exclude")
                    item_micro_delay(title)
                    continue

                if any(b in title_lower for b in BLOCKED_BRANDS):
                    audit_candidate("blocked", seen_audit_item, search, block_reason="blocked_brand")
                    item_micro_delay(title)
                    continue

                exclude_kw = search.get("exclude_keywords", [])
                if exclude_kw and any(ek in title_lower for ek in exclude_kw):
                    audit_candidate("blocked", seen_audit_item, search, block_reason="search_exclude_keyword")
                    item_micro_delay(title)
                    continue

                raw_probe_item = dict(item)
                raw_probe_item["link"] = href
                raw_probe_item["url"] = href
                raw_probe_item["age_min"] = age_min
                raw_probe_item["_search_meta"] = {"name": search.get("name")}
                collect_raw_style_candidate(raw_probe_item, search)

                if not price or price < search.get("min_price", 1):
                    cnt_price += 1
                    audit_candidate("blocked", seen_audit_item, search, block_reason="price_below_search_min")
                    item_micro_delay(title)
                    continue

                if price < 18:
                    cnt_price += 1
                    audit_candidate("blocked", seen_audit_item, search, block_reason="price_below_global_min")
                    item_micro_delay(title)
                    continue

                _non_latin = sum(1 for c in title if ord(c) > 591)
                if _non_latin > len(title) * 0.3:
                    cnt_rejected += 1
                    audit_candidate("blocked", seen_audit_item, search, block_reason="non_latin_title")
                    item_micro_delay(title)
                    continue

                # ── Req 3 — SEARCH PROFILE FILTER ────────────────────
                # Special modes (football/lego/carhartt) bypass profile
                # to keep their own validators working
                _raw_candidates += 1
                if profile_active and not football_mode and not lego_sw_mode and not carhartt_mode:
                    _reject_log: list[str] = []
                    if not apply_search_profile(title, price, profile, _reject_log):
                        cnt_profile_rej += 1
                        for reason in _reject_log:
                            reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
                        audit_candidate("blocked", seen_audit_item, search, block_reason="profile_filter:" + ",".join(_reject_log[:3]))
                        item_micro_delay(title)
                        continue

                # ── Req 3 — HUMAN VIBE SKIP (10–15% random) ──────────
                if human_vibe_skip(title, pct=0.12):
                    cnt_vibe_skip += 1
                    reject_reasons["vibe_skip"] = reject_reasons.get("vibe_skip", 0) + 1
                    audit_candidate("blocked", seen_audit_item, search, block_reason="vibe_skip")
                    item_micro_delay(title)
                    continue

                # ── PART 1 — CENTRAL FEATURE EXTRACTION ──────────────
                features     = extract_item_features(item)
                _has_brand   = features["has_brand"]
                _has_vintage = features["is_vintage"]

                if DEBUG_PIPELINE:
                    print(f"  [FEAT] {title[:50]} | brand={features['brand']} "
                          f"vintage={_has_vintage} cat={features['category']}")

                CATEGORY_KW = search.get("keywords", [])
                TRASH_KW    = [
                    "zara", "bershka", "h&m", "hm", "shein", "primark",
                    "sinsay", "reserved", "stradivarius", "pull&bear",
                    "mango", "mohito", "house brand", "terranova",
                ]

                TRASH_KEYWORDS_ITEM = [
                    "blouse", "bluzka", "sukienka", "dress", "cute",
                    "coquette", " top,", "top z ", "crop top", "stanik",
                    "bra ", "bikini", "swimsuit", "kąpiel",
                    "kombinezon", "body ", "legginsy", "rajstopy",
                ]
                if not lego_sw_mode and not football_mode and not carhartt_mode:
                    if any(x in title_lower for x in TRASH_KEYWORDS_ITEM):
                        cnt_rejected += 1
                        reject_reasons["trash_keyword"] = reject_reasons.get("trash_keyword", 0) + 1
                        audit_candidate("blocked", seen_audit_item, search, block_reason="trash_keyword")
                        item_micro_delay(title)
                        continue

                # Part 5 — scoring przez features (nigdy undefined variable)
                item_score = 0
                if _has_brand:
                    item_score += 1
                if CATEGORY_KW and any(kw_term.lower() in title_lower for kw_term in CATEGORY_KW):
                    item_score += 2
                if _has_vintage:
                    item_score += 2
                if price and price < 80:
                    item_score += 1
                if any(tr in title_lower for tr in TRASH_KW):
                    item_score -= 2

                grail_mode = search.get("grail_mode", False)

                if not lego_sw_mode and not carhartt_mode and not football_mode:
                    effective_hidden = hidden_gem_mode and bool(ANTHROPIC_KEY)
                    if grail_mode or effective_hidden or search.get("layer") == "chaos":
                        min_score = 1
                    else:
                        min_score = 2
                    if item_score < min_score:
                        cnt_kw += 1
                        audit_candidate("blocked", seen_audit_item, search, block_reason=f"item_score_below_min:{item_score}<{min_score}", score=item_score)
                        item_micro_delay(title)
                        continue

                _item_score_val = item_score

                if (
                    not lego_sw_mode and not carhartt_mode
                    and not football_mode and not grail_mode
                    and not _has_brand and not _has_vintage
                    and price < 40
                ):
                    cnt_rejected += 1
                    audit_candidate("blocked", seen_audit_item, search, block_reason="cheap_unbranded_not_vintage")
                    item_micro_delay(title)
                    continue

                steal_threshold = STEAL_PRICES.get(search["category"], 9999)
                is_steal_price  = price <= steal_threshold
                is_below_market = False
                discount_pct    = 0
                if market_price and market_price > 0:
                    discount_pct    = (1 - price / market_price) * 100
                    saving          = market_price - price
                    is_below_market = (
                        discount_pct >= MIN_DISCOUNT_PCT
                        and saving >= MIN_SAVING_PLN
                    )

                typo_brand, typo_found = detect_typo_brand(title)
                has_typo = typo_brand is not None

                lego_sw_valid, lego_sw_score, lego_sw_reasons, lego_set_info = False, 0, [], {}
                if lego_sw_mode:
                    lego_sw_valid, lego_sw_score, lego_sw_reasons, lego_set_info = validate_lego_sw(title, None, None)
                    if lego_sw_score < 40:
                        lego_sw_valid = False
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

                if lego_sw_mode:
                    qualifies = lego_sw_valid
                elif football_mode:
                    qualifies = football_valid
                elif carhartt_mode:
                    qualifies = carhartt_valid
                elif hidden_gem_mode and not ANTHROPIC_KEY:
                    qualifies = is_steal_price or is_below_market
                else:
                    qualifies = (
                        is_steal_price or is_below_market
                        or has_typo or is_hidden_gem
                    )
                if not qualifies:
                    cnt_rejected += 1
                    audit_candidate("blocked", seen_audit_item, search, block_reason="normal_qualifier_false", score=_item_score_val)
                    item_micro_delay(title)
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
                    "item_score": _item_score_val,
                    "ts": time.time(),
                    "age_min": age_min,
                    "_features": features,
                })
                audit_candidate("candidate", seen_audit_item, search, {
                    "engine": "PRE_ENGINE",
                    "final_score": _item_score_val,
                    "category": features.get("category"),
                    "brand": features.get("brand"),
                }, alert_type="PRE_ENGINE", score=_item_score_val)

                processed_items += 1

                # Req 1 — micro delay AFTER accepted item
                item_micro_delay(title)

                if len(found) >= MAX_FOUND:
                    break

            except Exception as e:
                print(f"  ❌ ITEM PIPELINE ERROR: {e} | "
                      f"item={item.get('title', '?')[:60] if item else '?'}")
                if DEBUG_PIPELINE:
                    import traceback
                    traceback.print_exc()
                item_micro_delay()
                continue

        # ── Req 4 — SAFEGUARD: 0 items after filter → relax ──────────
        if processed_items == 0 and _raw_candidates > 0 and profile_active:
            print(f"  [SAFEGUARD] 0 items passed profile — relaxing filters "
                  f"(retrying {_raw_candidates} candidates without profile)")
            # Retry the same items without profile restrictions
            for item in items:
                if not item:
                    continue
                try:
                    item_id     = item.get("id", "")
                    title       = item.get("title", "")
                    href        = item.get("url", "")
                    price       = item.get("price")
                    title_lower = title.lower()
                    if (not item_id or not href or not title or
                            not price or price < 18):
                        continue
                    if any(ex in title_lower for ex in GLOBAL_EXCLUDE):
                        continue
                    TRASH_KEYWORDS_ITEM = [
                        "sukienka", "dress", "bluzka", "bikini", "stanik",
                        "swimsuit", "legginsy", "rajstopy",
                    ]
                    if any(x in title_lower for x in TRASH_KEYWORDS_ITEM):
                        continue
                    steal_threshold = STEAL_PRICES.get(search.get("category", "clothing"), 9999)
                    is_steal_price  = price <= steal_threshold
                    is_below_market = False
                    discount_pct    = 0
                    if market_price and market_price > 0:
                        discount_pct    = (1 - price / market_price) * 100
                        saving          = market_price - price
                        is_below_market = discount_pct >= 30 and saving >= MIN_SAVING_PLN
                    features = extract_item_features(item)
                    real_signal_reasons = validated_real_signal_reasons(item, bucket="safeguard")
                    real_signal_count = len(real_signal_reasons)
                    qualifies = (
                        (is_below_market and real_signal_count >= 2)
                        or (is_steal_price and real_signal_count >= 3)
                        or (real_signal_count >= 4)
                    )
                    if not qualifies:
                        verbose_item_log(
                            "safeguard_blocks",
                            f"[SAFEGUARD_QUALIFY_BLOCK] reason=not_enough_real_signal "
                            f"title={title[:60]} signals={real_signal_reasons[:5]}",
                        )
                        continue
                    SAFEGUARD_STATS["added"] += 1
                    found.append({
                        "id": item_id, "title": title, "link": href,
                        "price": price, "market_price": market_price,
                        "discount_pct": discount_pct,
                        "is_steal": is_steal_price, "is_below": is_below_market,
                        "has_typo": False, "typo_brand": None,
                        "is_hidden_gem": False, "mismatch": False,
                        "ai_brand": None, "reasons": ["safeguard_relaxed"],
                        "lego_sw_valid": False, "lego_sw_score": 0, "lego_set_info": {},
                        "football_valid": False, "carhartt_valid": False,
                        "carhartt_model": None, "carhartt_max": 0,
                        "photo": item.get("photo"),
                        "item_score": 1, "ts": time.time(),
                        "age_min": parse_item_age_minutes(item),
                        "_features": features,
                    })
                    processed_items += 1
                    if len(found) >= MAX_FOUND:
                        break
                except Exception:
                    continue

        # ── Req 5 — CAP: too many items → tighten (keep top by price proximity to market) ──
        if len(found) > 20:
            # Keep items closest to market price (best deals = furthest below)
            if market_price and market_price > 0:
                found.sort(key=lambda x: x.get("price", 0) / market_price)
            found = found[:20]
            print(f"  [FILTER_CAP] trimmed to 20 best deals")

        # ── Req 6 — [FILTER] logging ─────────────────────────────────
        total_reached = _raw_candidates or total_items
        ratio_pct = (processed_items / total_reached * 100) if total_reached > 0 else 0
        print(f"  [FILTER] accepted={processed_items} rejected={cnt_profile_rej} "
              f"vibe_skip={cnt_vibe_skip} "
              f"ratio={ratio_pct:.0f}% ({processed_items}/{total_reached})")
        if reject_reasons:
            top_reasons = sorted(reject_reasons.items(), key=lambda x: -x[1])[:5]
            for reason, count in top_reasons:
                print(f"  [REJECT_REASON] {reason}: {count}x")

    except Exception as e:
        print(f"  ❌ check_search FATAL [{search['name']}]: {e}")
        if DEBUG_PIPELINE:
            import traceback
            traceback.print_exc()

    # Part 2 — pipeline metrics
    print(f"  📊 Processed: {processed_items}/{total_items} | "
          f"widziane={cnt_seen} brak_ceny={cnt_price} "
          f"brak_słów={cnt_kw} odrzucone={cnt_rejected} wysłane={len(found)}")
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
BOT_POSITIVE_KNOWLEDGE_BASE = build_bot_positive_knowledge_base()
FRESH_DISCOVERY_QUERY_POOL = build_fresh_discovery_queries_from_knowledge(BOT_POSITIVE_KNOWLEDGE_BASE)
TARGET_MARKERS = build_target_markers_from_knowledge(BOT_POSITIVE_KNOWLEDGE_BASE)

print("✅ BOT HIDDEN GEM FINDER URUCHOMIONY")

load_bricklink_cache()
refresh_session()

if False: send_message(
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

send_startup_message()

seen          = load_seen()
# FIX: usuń stale seen jeśli mają stary format (30-dniowy) — jednorazowe czyszczenie
_now = time.time()
_cutoff_6h = _now - 6 * 3600
_before = len(seen)
seen = {k: v for k, v in seen.items() if v > _cutoff_6h}
_after = len(seen)
if _before != _after:
    print(f"🧹 Wyczyszczono seen: {_before} → {_after} wpisów (usunięto stare >6h)")
    save_seen(seen)
else:
    print(f"💾 Seen załadowany: {_after} wpisów (TTL=6h)")

SENT_ALERTS = load_sent_alerts()
cleanup_sent_alerts()
save_sent_alerts(force=True)

market_prices = {}
cycle         = 0

# Inicjalizacja silnika inteligencji
engine = None
if _ENGINE_AVAILABLE:
    engine = Engine(anthropic_key=ANTHROPIC_KEY)
    print(engine.stats())

while True:
    try:
        # Co 50 cykli (~50 min) odśwież sesję Vinted
        if cycle % 50 == 0:
            refresh_session()

        # Mediany w tle — co 60 cykli (~90 min), uruchamiamy osobny wątek
        # żeby nie blokować głównej pętli przez 12 minut
        if cycle % 60 == 0 and cycle > 0:
            import threading
            def _update_medians_bg():
                cnt = 0
                err = 0
                median_searches = [s for s in SEARCHES
                                   if not s.get("hidden_gem_mode") and not s.get("no_median")]
                print(f"\n📊 [BG] Start aktualizacji median ({len(median_searches)} searchów)...")
                for s in median_searches:
                    try:
                        val = get_market_median(s)
                        if val:
                            market_prices[s["name"]] = val
                            cnt += 1
                        time.sleep(random.uniform(5.0, 9.0))
                    except Exception as e:
                        err += 1
                        # Part 6 — nie ignoruj błędów cichutko
                        print(f"  ❌ [BG] median error [{s['name']}]: {e}")
                print(f"📊 [BG] Mediany zaktualizowane: {cnt}/{len(median_searches)} "
                      f"(błędy: {err})")
            threading.Thread(target=_update_medians_bg, daemon=True).start()

        cycle += 1
        _consecutive_403  = 0   # reset na starcie cyklu
        _cycle_403_stop   = False
        cycle_start       = time.time()

        print(f"\n🔄 Cykl #{cycle}")
        reset_raw_style_cycle()
        reset_candidate_audit_cycle(cycle)
        reset_fresh_discovery_cycle()

        # Req 8 — session refresh (only when needed, not every cycle)
        _maybe_refresh_session()

        # Propaguj mediany do searchów no_median w tej samej kategorii
        _cat_to_median: dict[str, float] = {}
        for s in SEARCHES:
            if not s.get("no_median") and s["name"] in market_prices:
                cat = s.get("category", "")
                if cat and cat not in _cat_to_median:
                    _cat_to_median[cat] = market_prices[s["name"]]
        for s in SEARCHES:
            if s.get("no_median") and s["name"] not in market_prices:
                cat = s.get("category", "")
                if cat and cat in _cat_to_median:
                    market_prices[s["name"]] = _cat_to_median[cat]

        # ── Req 2+3: RANDOMIZED CYCLE SIZE + RANDOM SEARCH SELECTION ──
        # 50% → 2 searches, 30% → 3, 20% → 4
        _roll = random.random()
        if _roll < 0.50:
            n_searches = 2
        elif _roll < 0.80:
            n_searches = 3
        else:
            n_searches = 4

        # Build pool from tiered rotation (same logic as before)
        TIER_A_LAYERS = {"wide_brand", "premium"}
        TIER_B_LAYERS = {"chaos", "category", "targeted"}
        TIER_C_LAYERS = {"football", "lego"}
        GRAIL_LAYERS  = {"grail"}

        tier_a     = [s for s in SEARCHES if s.get("layer") in TIER_A_LAYERS and not s.get("no_median")]
        tier_b     = [s for s in SEARCHES if s.get("layer") in TIER_B_LAYERS]
        tier_c     = [s for s in SEARCHES if s.get("layer") in TIER_C_LAYERS]
        tier_grail = [s for s in SEARCHES if s.get("layer") in GRAIL_LAYERS]

        # Always include at least one grail search + sample from other tiers
        pool: list = list(tier_grail)
        pool += random.sample(tier_a, min(len(tier_a), max(1, n_searches - 1)))
        if cycle % 2 == 0 and tier_b:
            pool += random.sample(tier_b, min(len(tier_b), 2))
        if cycle % 4 == 0 and tier_c:
            pool += random.sample(tier_c, min(len(tier_c), 1))

        # Req 3 — shuffle EVERY time (never same order twice)
        random.shuffle(pool)
        this_cycle_searches = pool[:n_searches + 2]   # +2 buffer for skips

        # Req 10 — early exit
        if random.random() < 0.10:
            print(f"  [CYCLE] early_exit=True (noise injection)")
            core_keep = [s for s in this_cycle_searches if is_core_search(s)]
            peripheral_keep = [s for s in this_cycle_searches if not is_core_search(s)][:1]
            this_cycle_searches = core_keep + peripheral_keep

        if TASTE_DISCOVERY_ENABLED and TASTE_DISCOVERY_QUERIES:
            taste_limit = max(0, int(TASTE_DISCOVERY_MAX_QUERIES_PER_CYCLE or 0))
            taste_count = min(taste_limit, len(TASTE_DISCOVERY_QUERIES))
            if taste_count:
                chosen_taste_queries = random.sample(TASTE_DISCOVERY_QUERIES, taste_count)
                existing_search_names = {s.get("name") for s in this_cycle_searches}
                for taste_query in chosen_taste_queries:
                    taste_search = make_taste_discovery_search(taste_query)
                    if taste_search["name"] in existing_search_names:
                        continue
                    this_cycle_searches.append(taste_search)
                    existing_search_names.add(taste_search["name"])
                    print(f"  [TASTE_DISCOVERY_QUERY] query={taste_query} reason=manual_taste_pool")

        fresh_queries = select_fresh_discovery_queries()
        if fresh_queries:
            existing_search_names = {s.get("name") for s in this_cycle_searches}
            for fresh_query in fresh_queries:
                fresh_search = make_fresh_discovery_search(fresh_query)
                if fresh_search["name"] in existing_search_names:
                    continue
                this_cycle_searches.append(fresh_search)
                existing_search_names.add(fresh_search["name"])
                print(f"[FRESH_DISCOVERY_QUERY] query={fresh_query} reason=knowledge_rotation")

        print(f"[SEARCH_PLAN] "
              f"core={[s.get('name') for s in this_cycle_searches if is_core_search(s)][:6]} "
              f"taste={[s.get('name') for s in this_cycle_searches if s.get('taste_discovery')][:6]} "
              f"fresh={[s.get('name') for s in this_cycle_searches if s.get('fresh_discovery')]}")

        print(f"  [CYCLE] search_count={len(this_cycle_searches)} "
              f"(target={n_searches})")

        # Zbierz wszystkie nowe itemy z tego cyklu
        all_new_items: list = []
        special_items: list = []
        now = time.time()
        searches_done = 0

        for search in this_cycle_searches:
            core_search = is_core_search(search)
            qcov = query_coverage_record(search["name"])
            qcov["core"] = core_search
            # Req 7 — hard stop if cycle marked for stop by 403
            if _cycle_403_stop:
                print(f"  [403] cycle_stop — przerywam cykl po banie")
                break

            # Req 6 — 20% chance: skip search entirely (noise)
            if random.random() < 0.20 and not core_search:
                qcov["skipped_this_cycle"] = True
                print(f"  [SEARCH_SKIP] name={search['name']} reason=random_noise_peripheral_only")
                continue

            print(f"  ⏳ Sprawdzam: {search['name']}")
            if core_search:
                print(f"  [CORE_SEARCH_RUN] name={search['name']}")
            market_price = market_prices.get(search["name"])
            last_checked = qcov.get("last_checked_at")
            qcov["seconds_since_last_check"] = int(now - last_checked) if last_checked else None
            qcov["last_checked_at"] = now
            qcov["checked_this_cycle"] = True
            new_items, all_ids = check_search(search, seen, market_price)
            searches_done += 1
            print(f"  [SEARCH] selected={search['name']} nowych={len(new_items)}")

            # Oznacz jako seen tylko stare itemy
            new_ids = {str(it.get("id", "")) for it in new_items}
            for _id in all_ids:
                if _id not in seen and str(_id) not in new_ids:
                    seen[_id] = now

            is_special = (
                search.get("football_mode") or
                search.get("lego_sw_mode") or
                search.get("carhartt_mode")
            )

            # Req 6 — 10% chance: first page only (early stop within search)
            items_to_take = MAX_ALERTS_PER_SEARCH if core_search else (1 if random.random() < 0.10 else MAX_ALERTS_PER_SEARCH)
            qcov["candidates_created"] += min(len(new_items), items_to_take)
            if search.get("fresh_discovery"):
                FRESH_DISCOVERY_STATS["queries_run"] += 1
                print(f"[FRESH_DISCOVERY_RESULT] query={search.get('name')} "
                      f"seen={qcov.get('items_seen', 0)} candidates={qcov.get('candidates_created', 0)} "
                      f"blocked={qcov.get('blocked_count', 0)}")
            for item in new_items[:items_to_take]:
                item["_search_meta"] = {
                    "football_mode":  search.get("football_mode"),
                    "lego_sw_mode":   search.get("lego_sw_mode"),
                    "carhartt_mode":  search.get("carhartt_mode"),
                    "name":           search.get("name"),
                }
                if is_special:
                    special_items.append((search, item))
                else:
                    all_new_items.append(item)

            # Req 4 — thinking pause between searches
            if not core_search:
                _thinking_pause(after=search["name"])

            # Req 7 — 20% chance: random idle (30–90s) between searches
            if not core_search:
                maybe_random_idle(context=search["name"])

        cycle_duration = time.time() - cycle_start
        print(f"  [CYCLE] search_count={searches_done} duration={cycle_duration:.0f}s")

        # ── STEP 7 — EVALUATE_AND_DECIDE ────────────────────────────
        sent_this_cycle = 0
        MAX_PER_CYCLE   = 10
        safeguard_sent_this_cycle = 0

        for search, item in special_items:
            item["_search_meta"] = {
                "football_mode":  search.get("football_mode"),
                "lego_sw_mode":   search.get("lego_sw_mode"),
                "carhartt_mode":  search.get("carhartt_mode"),
                "name":           search.get("name"),
            }
            all_new_items.append(item)

        if engine and all_new_items:
            all_new_items = filter_unsent_items(all_new_items)
            engine_results = dedupe_results_by_item(engine.run_cycle_strict(all_new_items, market_prices))
            for audit_result in engine_results:
                audit_candidate(
                    "main_engine_score",
                    audit_result.get("item", {}),
                    result=audit_result,
                    alert_type=_alert_type(audit_result),
                    score=audit_result.get("final_score"),
                    bucket=audit_result.get("raw_style_bucket") or audit_result.get("taste_bucket") or audit_result.get("tier"),
                    signals=audit_result.get("desirable_signals") or audit_result.get("taste_signals") or [],
                )

            for idx, result in enumerate(engine_results):
                if sent_this_cycle >= MAX_PER_CYCLE:
                    for skipped_result in engine_results[idx:]:
                        audit_candidate("rank_not_selected", skipped_result.get("item", {}), result=skipped_result,
                                        block_reason="max_per_cycle_limit", alert_type=_alert_type(skipped_result),
                                        score=skipped_result.get("final_score"))
                    break

                item   = result["item"]
                eng    = result.get("engine", "?")
                profit = result.get("profit", 0)
                conf   = result.get("confidence", 0)
                reason = result.get("reason", "")
                dedupe_key = get_item_dedupe_key(item)
                if already_sent(dedupe_key):
                    print(f"[DEDUPE_BLOCK] duplicate_before_send key={dedupe_key} title={str(item.get('title',''))[:60]}")
                    audit_candidate("dedupe_skip", item, result=result, block_reason="duplicate_before_send",
                                    alert_type=_alert_type(result), score=result.get("final_score"))
                    continue

                alert_type = _alert_type(result)
                is_safeguard = "safeguard_relaxed" in (item.get("reasons") or [])
                presend_source = "SAFEGUARD" if is_safeguard else alert_type
                if presend_source == "SAFEGUARD":
                    SAFEGUARD_STATS["retried"] += 1
                    if safeguard_sent_this_cycle >= SAFEGUARD_MAX_SEND_PER_CYCLE:
                        SAFEGUARD_STATS["limit_skipped"] += 1
                        print(f"[SAFEGUARD_SEND_LIMIT_SKIP] title={str(item.get('title') or '')[:60]}")
                        audit_candidate("final_skip", item, result=result, block_reason="safeguard_send_limit",
                                        alert_type=alert_type, score=result.get("final_score"))
                        continue
                presend_ok, presend_reason = telegram_presend_gate(item, result, source=presend_source)
                validated_signals = int(result.get("_raw_style_validated_signals") or 0)
                if not presend_ok:
                    query_coverage_record((item.get("_search_meta") or {}).get("name"))["blocked_count"] += 1
                    if presend_source == "SAFEGUARD":
                        SAFEGUARD_STATS["blocked_presend"] += 1
                        print(f"[SAFEGUARD_PRESEND_BLOCK] reason={presend_reason} "
                              f"validated_signals={validated_signals} title={str(item.get('title') or '')[:60]}")
                    else:
                        print(f"[PRESEND_BLOCK] source={presend_source} reason={presend_reason} "
                              f"validated_signals={validated_signals} title={str(item.get('title') or '')[:60]}")
                    audit_candidate("blocked", item, result=result, block_reason=presend_reason,
                                    alert_type=alert_type, score=result.get("final_score"),
                                    bucket=result.get("taste_bucket") or result.get("raw_style_bucket") or result.get("tier"),
                                    signals=result.get("taste_signals") or result.get("raw_style_signals"))
                    continue
                if presend_source == "SAFEGUARD":
                    SAFEGUARD_STATS["passed_presend"] += 1
                    print(f"[SAFEGUARD_PRESEND_PASS] validated_signals={validated_signals} "
                          f"title={str(item.get('title') or '')[:60]}")

                photo     = item.get("photo") or get_item_photo(item["id"], item.get("link", ""))
                alert_msg = format_telegram_alert(item, result)
                sent_ok = send_alert_message(
                    alert_msg, item, result, presend_source, dedupe_key,
                    photo_url=photo,
                    item_link=item.get("link"),
                )
                if not sent_ok:
                    continue
                log_decision_trace(item, result, presend_source, presend_reason, send_status="success")
                query_coverage_record((item.get("_search_meta") or {}).get("name"))["alerts_sent"] += 1
                mark_sent(item, result, (item.get("_search_meta") or {}).get("name"))
                audit_candidate("sent", item, result=result, sent=True, alert_type=_alert_type(result),
                                score=result.get("final_score"))
                if alert_type == "STYLE_WATCH":
                    AGE_GATE_STATS["sent"] += 1
                log_send_age_source(result)
                if presend_source == "SAFEGUARD":
                    safeguard_sent_this_cycle += 1
                    SAFEGUARD_STATS["sent"] += 1
                seen[item["id"]] = now
                sent_this_cycle += 1

                emoji = {"GRAIL": "💎", "BRAND": "🟣", "CHAOS": "🔵"}.get(eng, "⚪")
                print(f"  {emoji} [{eng}] conf={conf:.1f} profit={profit:.0f}zł "
                      f"reason={reason} | {item['title'][:35]}")

                # Req 10 — micro delay after each sent item
                if random.random() < ITEM_IDLE_PCT:
                    idle = random.uniform(ITEM_IDLE_MIN, ITEM_IDLE_MAX)
                    print(f"  [ITEM] idle={idle:.1f}s (simulate reading)")
                    time.sleep(idle)
                else:
                    time.sleep(random.uniform(ITEM_MICRO_DELAY_MIN, ITEM_MICRO_DELAY_MAX))

        # ── FALLBACK ────────────────────────────────────────────────
        raw_style_sent = send_raw_style_candidates(MAX_PER_CYCLE, sent_this_cycle)
        sent_this_cycle += raw_style_sent

        if sent_this_cycle == 0 and not _cycle_403_stop:
            print(f"  ⚠️ FALLBACK MODE — brak wyników, rozszerzam okno do 120 min")
            fallback_items: list = []
            _fallback_searches = list(SEARCHES)
            random.shuffle(_fallback_searches)

            for search in _fallback_searches[:5]:   # ograniczone w fallback
                if _cycle_403_stop:
                    break
                if search.get("football_mode") or search.get("lego_sw_mode"):
                    continue
                fb_search = dict(search, _fallback_mode=True)
                fb_items, fb_ids = check_search(fb_search, seen, market_prices.get(search["name"]))
                for fb_item in fb_items:
                    fb_item["_search_meta"] = {
                        "football_mode":  fb_search.get("football_mode"),
                        "lego_sw_mode":   fb_search.get("lego_sw_mode"),
                        "carhartt_mode":  fb_search.get("carhartt_mode"),
                        "name":           fb_search.get("name"),
                    }
                for _id in fb_ids:
                    if _id not in seen:
                        seen[_id] = now
                fallback_items.extend(fb_items[:2])
                if len(fallback_items) >= 15:
                    break
                _thinking_pause(after=f"fallback:{search['name']}")

            if engine and fallback_items:
                fallback_items = filter_unsent_items(fallback_items)
                fb_results = dedupe_results_by_item(engine.run_cycle_strict(fallback_items, market_prices))
                for audit_result in fb_results:
                    audit_candidate("main_engine_score", audit_result.get("item", {}), result=audit_result,
                                    alert_type=_alert_type(audit_result), score=audit_result.get("final_score"))
                for skipped_result in fb_results[MAX_PER_CYCLE:]:
                    audit_candidate("rank_not_selected", skipped_result.get("item", {}), result=skipped_result,
                                    block_reason="fallback_max_per_cycle_slice", alert_type=_alert_type(skipped_result),
                                    score=skipped_result.get("final_score"))
                for result in fb_results[:MAX_PER_CYCLE]:
                    item   = result["item"]
                    profit = result.get("profit", 0)
                    if profit < 10:
                        audit_candidate("final_skip", item, result=result, block_reason="fallback_profit_below_10",
                                        alert_type=_alert_type(result), score=result.get("final_score"))
                        seen[item["id"]] = now
                        continue
                    dedupe_key = get_item_dedupe_key(item)
                    if already_sent(dedupe_key):
                        print(f"[DEDUPE_BLOCK] duplicate_before_send key={dedupe_key} title={str(item.get('title',''))[:60]}")
                        audit_candidate("dedupe_skip", item, result=result, block_reason="duplicate_before_send",
                                        alert_type=_alert_type(result), score=result.get("final_score"))
                        continue
                    alert_type = _alert_type(result)
                    SAFEGUARD_STATS["retried"] += 1
                    if safeguard_sent_this_cycle >= SAFEGUARD_MAX_SEND_PER_CYCLE:
                        SAFEGUARD_STATS["limit_skipped"] += 1
                        print(f"[SAFEGUARD_SEND_LIMIT_SKIP] title={str(item.get('title') or '')[:60]}")
                        audit_candidate("final_skip", item, result=result, block_reason="safeguard_send_limit",
                                        alert_type=alert_type, score=result.get("final_score"))
                        continue
                    presend_ok, presend_reason = telegram_presend_gate(item, result, source="SAFEGUARD")
                    validated_signals = int(result.get("_raw_style_validated_signals") or 0)
                    if not presend_ok:
                        query_coverage_record((item.get("_search_meta") or {}).get("name"))["blocked_count"] += 1
                        SAFEGUARD_STATS["blocked_presend"] += 1
                        print(f"[SAFEGUARD_PRESEND_BLOCK] reason={presend_reason} "
                              f"validated_signals={validated_signals} title={str(item.get('title') or '')[:60]}")
                        audit_candidate("blocked", item, result=result, block_reason=presend_reason,
                                        alert_type=alert_type, score=result.get("final_score"),
                                        bucket=result.get("taste_bucket") or result.get("raw_style_bucket") or result.get("tier"),
                                        signals=result.get("taste_signals") or result.get("raw_style_signals"))
                        continue
                    SAFEGUARD_STATS["passed_presend"] += 1
                    print(f"[SAFEGUARD_PRESEND_PASS] validated_signals={validated_signals} "
                          f"title={str(item.get('title') or '')[:60]}")
                    photo     = item.get("photo") or get_item_photo(item["id"], item.get("link", ""))
                    alert_msg = format_telegram_alert(item, result)
                    sent_ok = send_alert_message(
                        alert_msg, item, result, "SAFEGUARD", dedupe_key,
                        photo_url=photo,
                        item_link=item.get("link"),
                    )
                    if not sent_ok:
                        continue
                    log_decision_trace(item, result, "SAFEGUARD", presend_reason, send_status="success")
                    query_coverage_record((item.get("_search_meta") or {}).get("name"))["alerts_sent"] += 1
                    mark_sent(item, result, (item.get("_search_meta") or {}).get("name"))
                    audit_candidate("sent", item, result=result, sent=True, alert_type=_alert_type(result),
                                    score=result.get("final_score"))
                    if alert_type == "STYLE_WATCH":
                        AGE_GATE_STATS["sent"] += 1
                    log_send_age_source(result)
                    safeguard_sent_this_cycle += 1
                    SAFEGUARD_STATS["sent"] += 1
                    seen[item["id"]] = now
                    sent_this_cycle += 1
                    print(f"  🔁 FALLBACK [{result.get('engine','?')}] | {item['title'][:55]} | {item['price']:.0f} zł")

        extra_raw_style_sent = send_raw_style_candidates(MAX_PER_CYCLE, sent_this_cycle)
        sent_this_cycle += extra_raw_style_sent
        for remaining_raw in list(RAW_STYLE_CYCLE_CANDIDATES.values()):
            audit_candidate("final_skip", remaining_raw.get("item", {}), result=remaining_raw,
                            block_reason="raw_style_not_selected_limit_or_priority",
                            alert_type="RAW_STYLE", score=remaining_raw.get("raw_style_score"),
                            bucket=remaining_raw.get("raw_style_bucket"),
                            signals=remaining_raw.get("raw_style_signals"))

        print_raw_style_summary()
        print_candidate_audit_summary()
        print_fresh_discovery_summary()
        print_query_coverage_summary()
        print(f"  📊 Cykl #{cycle} zakończony — wysłano: {sent_this_cycle} alertów [CHAOS+BRAND+GRAIL+RAW_STYLE]")

        save_seen(seen)
        save_sent_alerts()

        if engine:
            engine.db.save()
            if DEBUG_PIPELINE:
                print(f"  💾 MarketDB: {len(engine.db.db)} grup | dirty={engine.db._dirty}")

        # Req 5 — CYCLE BREAK: 2–5 min, 20% chance 5–10 min
        if random.random() < CYCLE_BREAK_LONG_PCT:
            break_t = random.uniform(CYCLE_BREAK_LONG_MIN, CYCLE_BREAK_LONG_MAX)
            print(f"  [CYCLE] extended_break={break_t:.0f}s (20% chance)")
        else:
            break_t = random.uniform(CYCLE_BREAK_MIN, CYCLE_BREAK_MAX)
            print(f"  [CYCLE] break={break_t:.0f}s")
        time.sleep(break_t)

    except Exception as e:
        # Part 6 — NIE ignoruj błędów głównej pętli cichutko
        import traceback
        print(f"❌ Błąd głównej pętli (cykl #{cycle}): {e}")
        if DEBUG_PIPELINE:
            traceback.print_exc()
        # Zapisz DB nawet przy błędzie — nie trać danych
        if engine:
            try:
                engine.db.save(force=True)
            except Exception as save_err:
                print(f"  ❌ DB save po błędzie nie powiódł się: {save_err}")
        time.sleep(15)
