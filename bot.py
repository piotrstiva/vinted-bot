import requests
import time
import os
import json
import re
import base64
from statistics import median

# ── Intelligence Engine ──────────────────
try:
    from engine import Engine
    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False
    print("⚠️  engine.py nie znaleziony — tryb podstawowy")

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
DEBUG_ALERTS          = True  # FIX: loguj decyzje engine (conf, profit, grail)

# ─────────────────────────────────────────
#  ⚡ SNIPER MODE
# ─────────────────────────────────────────
MAX_ITEM_AGE_MINUTES  = 15   # Part 1 — tylko świeże oferty 0–15 min
SLEEP_BETWEEN_CYCLES  = 15   # Part 5 — szybszy loop (było 60s)

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
        # Fix 3 — beżowy kardigan / bezrękawnik futerko to nie jacket
        "exclude_keywords": [
            "sukienka", "dress", "spodnie", "jeans", "kamizelka",
            "sweter", "sweterek", "kardigan", "bluzka", "top ",
        ],
        "min_price": 25,
        "layer": "chaos",
        "vintage_mode": True,
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
    },
    {
        "name":     "Koszulka Piłkarska",
        "url":      "https://www.vinted.pl/catalog?search_text=koszulka+pilkarska&catalog[]=4&order=newest_first&currency=PLN&price_to=250",
        "category": "football",
        "keywords": ["koszulka", "piłkarska", "pilkarska"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
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
    },
    {
        "name":     "Umbro Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=umbro+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "football",
        "keywords": ["umbro", "shirt", "jersey"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
    },
    {
        "name":     "Kappa Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=kappa+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=300",
        "category": "football",
        "keywords": ["kappa", "shirt", "jersey"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
    },
    {
        "name":     "Lotto Football Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=lotto+football+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=250",
        "category": "football",
        "keywords": ["lotto", "shirt", "football"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
    },
    {
        "name":     "Diadora Football Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=diadora+football+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=250",
        "category": "football",
        "keywords": ["diadora", "shirt"],
        "min_price": 15,
        "layer": "football",
        "football_mode": True,
    },
    {
        "name":     "Old Football Shirt",
        "url":      "https://www.vinted.pl/catalog?search_text=old+football+shirt&catalog[]=4&order=newest_first&currency=PLN&price_to=200",
        "category": "football",
        "keywords": ["old", "shirt", "football"],
        "min_price": 10,
        "layer": "football",
        "football_mode": True,
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
SEEN_FILE      = "seen_items.json"
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

# BOT #5 — globalny licznik 403 — gdy Vinted blokuje, zwiększamy pauzę
_consecutive_403   = 0
_403_BACKOFF_STEPS = [60, 120, 300]   # FIX #7 — exponential: 60s → 120s → 300s
_403_BACKOFF_THRESHOLD = 3

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
    FIX #7: exponential backoff 60s → 120s → 300s po serii 403.
    """
    global _consecutive_403
    for attempt in range(1, 4):
        try:
            time.sleep(random.uniform(VINTED_MIN_DELAY, VINTED_MAX_DELAY))
            r = requests.get(url, headers=get_headers(), timeout=10)

            if r.status_code == 200:
                _consecutive_403 = 0
                return r

            if r.status_code == 429:
                wait = VINTED_429_WAIT * attempt
                print(f"  🚫 429 [{label}] — czekam {wait}s (próba {attempt})")
                time.sleep(wait)
                continue

            if r.status_code in (403, 401):
                _consecutive_403 += 1
                step_idx = min(_consecutive_403 - 1, len(_403_BACKOFF_STEPS) - 1)
                backoff  = _403_BACKOFF_STEPS[step_idx]
                print(f"  ⚠️ HTTP {r.status_code} [{label}] — próba {attempt}/3 "
                      f"(seria {_consecutive_403}x → backoff {backoff}s)")
                if _consecutive_403 >= _403_BACKOFF_THRESHOLD:
                    print(f"  🛑 Seria {_consecutive_403}x 403 — backoff {backoff}s + odświeżam sesję")
                    time.sleep(backoff)
                    refresh_session()
                    _consecutive_403 = 0
                else:
                    time.sleep(backoff)
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

                        # Fix #6 — debug: raz pokaż klucze pierwszego itemu żeby wiedzieć
                        # jakie pola zwraca Vinted (pomaga wykryć właściwe pole czasu)
                        if len(seen_ids) == 1 and not items:
                            ts_keys = [k for k in entry.keys()
                                       if any(t in k.lower() for t in
                                              ["time", "date", "at", "ts", "push", "create", "update", "active"])]
                            if ts_keys:
                                print(f"  🕐 Vinted TS fields: {ts_keys} | vals: {[entry.get(k) for k in ts_keys[:4]]}")
                            else:
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
                            items.append({
                                "id":         item_id,
                                "title":      title,
                                "price":      price,
                                "url":        url,
                                "photo":      photo_url,
                                "created_at_ts": ts_final,  # Fix #6 — już przeliczony
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
    Returns item age in minutes, or None when timestamp is unavailable.
    None-safe: callers must guard with `if age is not None`.
    """
    ts = item.get("created_at_ts")
    if not ts:
        return None
    try:
        age_sec = time.time() - float(ts)
        return max(0, int(age_sec / 60))
    except:
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
    found    = []
    all_ids  = []   # wszystkie ID widziane w tym cyklu
    cnt_seen = cnt_price = cnt_kw = cnt_rejected = 0
    # BOT #1 — limit znalezionych wewnątrz check_search (nie tylko w głównej pętli)
    # MAX_ALERTS_PER_SEARCH w głównej pętli przycina DO wysyłki, ale found=20
    # powoduje że engine ocenia 20 itemów niepotrzebnie
    MAX_FOUND = MAX_ALERTS_PER_SEARCH * 2  # 10 — bufor na engine skip
    # BOT #3 — dedup po title+price (Vinted zwraca ten sam item przez kilka wyszukiwań)
    _seen_title_price: set[str] = set()

    try:
        r = vinted_fetch(search["url"], label=search["name"])
        if not r:
            return [], []

        items = parse_items_from_html(r.text)
        print(f"[{search['name']}] Ofert na stronie: {len(items)}")

        # ── MULTI-LAYER FRESHNESS PRE-FILTER ────────────────────
        # Engine owns the tier logic; bot just pre-sorts and drops truly stale items.
        # Hard cutoff: >360 min (6 h) — engine rejects these anyway.
        # PART 3: fallback_mode=True relaxes to 120 min for all items (used when 0 sent).
        fallback_mode   = search.get("_fallback_mode", False)
        hard_cutoff_min = 120 if fallback_mode else 360

        tiered_items = []
        for it in items:
            age = parse_item_age_minutes(it)
            if age is None or age > hard_cutoff_min:
                continue
            tiered_items.append(it)

        if not tiered_items:
            # Nothing at all — still return empty so main loop can trigger fallback
            print(f"  ⏰ Brak ofert w oknie {hard_cutoff_min} min [{search['name']}]")
            return [], []

        # Sort freshest first so engine sees best candidates early
        tiered_items.sort(key=lambda x: parse_item_age_minutes(x) or 9999)
        items = tiered_items

        # Debug — show first 2 items with age
        for dbg in items[:2]:
            age_dbg = parse_item_age_minutes(dbg)
            age_str = f"{age_dbg}min" if age_dbg is not None else "?"
            print(f"  🔍 '{dbg['title'][:60]}' | {dbg['price']} zł | ⏱ {age_str}")

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

                # Part 4 — in-memory sniper seen (szybszy niż disk seen)
                # Part 4 — in-memory sniper seen z TTL 6h
                _now_sn = time.time()
                _sniper_ts = _SNIPER_SEEN.get(item_id)
                if _sniper_ts and (_now_sn - _sniper_ts) < 6 * 3600:
                    cnt_seen += 1
                    continue
                _SNIPER_SEEN[item_id] = _now_sn
                # Wyczyść stare wpisy gdy za duże
                if len(_SNIPER_SEEN) > 5000:
                    _cutoff = _now_sn - 6 * 3600
                    _SNIPER_SEEN_new = {k: v for k, v in _SNIPER_SEEN.items() if v > _cutoff}
                    _SNIPER_SEEN.clear()
                    _SNIPER_SEEN.update(_SNIPER_SEEN_new)

                # Part 7 — debug age
                age_min = parse_item_age_minutes(item)
                if age_min is not None and DEBUG_ALERTS:
                    print(f"  📤 NEW ITEM: {title[:60]} | age={age_min}min | {price} zł")

                if not item_id or not href:
                    continue

                # FIX: seen sprawdza TTL — item wraca po 6h
                _seen_ts = seen.get(item_id)
                if _seen_ts and (time.time() - _seen_ts) < 6 * 3600:
                    cnt_seen += 1
                    continue

                all_ids.append(item_id)  # zapamiętaj wszystkie widziane

                if not title or not href:
                    continue

                # BOT #3 — odrzuć duplikaty tego samego tytułu+ceny w tym cyklu
                # (ten sam item może trafić przez 2 wyszukiwania)
                _dedup_key = f"{title.lower().strip()}_{int(price or 0)}"
                if _dedup_key in _seen_title_price:
                    cnt_seen += 1
                    continue
                _seen_title_price.add(_dedup_key)

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

                # ── PART 5: SMART ITEM SCORING ──────────────
                VINTAGE_KW  = ["vintage", "retro", "90s", "80s", "70s", "y2k",
                                "single stitch", "archive", "deadstock", "band tee",
                                "tour", "old school", "heritage", "throwback",
                                "made in usa", "made in italy", "rare", "promo",
                                "concert", "bootleg", "rap tee"]
                BRAND_KW    = [
                    "nike", "adidas", "jordan", "supreme", "palace", "stussy",
                    "bape", "carhartt", "arcteryx", "salomon", "corteiz",
                    "represent", "broken planet", "denim tears", "essentials",
                    "fear of god", "yeezy", "levi", "wrangler", "kappa",
                    "umbro", "lotto", "diadora", "hummel", "fila", "funko", "lego",
                    "puma", "reebok", "asics", "new balance", "vans",
                    "harley davidson", "harley", "metallica", "nirvana", "grateful dead",
                ]
                CATEGORY_KW = search.get("keywords", [])
                TRASH_KW    = [
                    "zara", "bershka", "h&m", "hm", "shein", "primark",
                    "sinsay", "reserved", "stradivarius", "pull&bear",
                    "mango", "mohito", "house brand", "terranova",
                ]

                t_lo = title_lower

                # Fix #1 — zdefiniuj _has_brand i _has_vintage PRZED użyciem
                _has_brand   = any(b in t_lo for b in BRAND_KW)
                _has_vintage = any(v in t_lo for v in VINTAGE_KW)

                # Fix #5 — TRASH_KEYWORDS: odrzuć sukienki, tospy, bluzki
                TRASH_KEYWORDS_ITEM = [
                    "blouse", "bluzka", "sukienka", "dress", "cute",
                    "coquette", " top,", "top z ", "crop top", "stanik",
                    "bra ", "bikini", "swimsuit", "kąpiel",
                    "kombinezon", "body ", "legginsy", "rajstopy",
                ]
                if not lego_sw_mode and not football_mode and not carhartt_mode:
                    if any(x in t_lo for x in TRASH_KEYWORDS_ITEM):
                        cnt_rejected += 1
                        continue

                item_score = 0
                if _has_brand:
                    item_score += 1
                if CATEGORY_KW and any(kw.lower() in t_lo for kw in CATEGORY_KW):
                    item_score += 2
                if _has_vintage:
                    item_score += 2
                if price and price < 80:
                    item_score += 1
                if any(tr in t_lo for tr in TRASH_KW):
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
                        continue

                _item_score_val = item_score

                # Fix #8 — block items without brand AND without grail signal
                if (
                    not lego_sw_mode and not carhartt_mode
                    and not football_mode and not grail_mode
                    and not _has_brand and not _has_vintage
                    and price < 40
                ):
                    cnt_rejected += 1
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
                    "item_score": _item_score_val,   # Part 2.1 — dla should_add_to_db
                    "ts": time.time(),                # Part 2.5 — dla rolling window
                    "age_min": age_min,               # Part 6 — sniper age boost
                })

                # BOT #1 — stop early gdy mamy wystarczająco dużo itemów
                if len(found) >= MAX_FOUND:
                    break

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

        # Step 6 — zbieramy wyniki wszystkich wyszukiwań, sortujemy i wysyłamy top
        cycle_candidates = []   # (confidence, search, item, eval_result)

        for search in SEARCHES:
            print(f"  ⏳ Sprawdzam: {search['name']}")
            market_price = market_prices.get(search["name"])
            new_items, all_ids = check_search(search, seen, market_price)
            print(f"  ✔ Gotowe: {search['name']} — nowych: {len(new_items)}")

            # FIX 2 — oznacz WSZYSTKIE widziane ID jako seen
            # (nie tylko wysłane) żeby nie wracały co cykl
            now = time.time()
            for _id in all_ids:
                if _id not in seen:
                    seen[_id] = now

            is_special = (
                search.get("football_mode") or
                search.get("lego_sw_mode") or
                search.get("carhartt_mode")
            )

            for item in new_items[:MAX_ALERTS_PER_SEARCH]:

                # Tryby specjalne — bypass engine, od razu do wysyłki
                if is_special:
                    cycle_candidates.append((10.0, search, item, None, now))
                    continue

                # ── Engine evaluation ─────────────────
                if engine:
                    eval_result    = engine.evaluate(item, search, market_price)

                    # PART 1 — skip items with no age data (engine already returned send_alert=False)
                    if eval_result.get("_skip_reason") == "no_age_data":
                        if DEBUG_ALERTS:
                            print(f"  ⏭  SKIP no_age_data | {item['title'][:40]}")
                        seen[item["id"]] = now
                        continue

                    # Part 6 — SNIPER BOOST: bardzo świeże itemy (≤ 3 min) → boost
                    age_min = eval_result.get("item_age_min")
                    if age_min is not None and age_min <= 3:
                        eval_result = dict(eval_result)
                        eval_result["confidence"]  = min(eval_result["confidence"] + 1.0, 10.0)
                        eval_result["flip_profit"] = eval_result.get("flip_profit", 0) + 5
                        if DEBUG_ALERTS:
                            print(f"  ⚡ SNIPER BOOST (age={age_min}min) | {item['title'][:40]}")

                    conf           = eval_result["confidence"]
                    has_db         = eval_result.get("db_data") is not None
                    flip_speed     = eval_result.get("scoring", {}).get("flip_speed", "MEDIUM")
                    flip_profit    = eval_result.get("flip_profit", 0)
                    is_grail       = eval_result.get("is_grail", False)
                    detected_brand = eval_result.get("brand", "?")
                    detected_cat   = eval_result.get("category", "?")
                    deal_tag       = eval_result.get("deal_tag", "WEAK")

                    # Fix #2 — nie skipuj znanych brandów vintage tylko z powodu niskiego conf
                    # DB może zaniżać wartość rzadkich modeli (ranger jacket, trucker itp.)
                    is_known_brand = detected_brand in {
                        "carhartt", "arcteryx", "arc'teryx", "salomon",
                        "supreme", "palace", "stussy", "stone island",
                        "cp company", "corteiz", "represent",
                    }
                    if has_db and conf < 5.5 and not is_grail and not is_known_brand:
                        if DEBUG_ALERTS:
                            print(f"  ⏭  skip conf={conf:.1f} brand={detected_brand} | {item['title'][:35]}")
                        seen[item["id"]] = now
                        continue

                    # Part 1 — SLOW flip: obniżony próg z 80 → 30 zł
                    if flip_speed == "SLOW" and flip_profit < 30 and not is_grail:
                        if DEBUG_ALERTS:
                            print(f"  ⏭  SLOW skip profit={flip_profit:.0f}zł | {item['title'][:35]}")
                        seen[item["id"]] = now
                        continue

                    if DEBUG_ALERTS:
                        grail_tag = " 💎GRAIL" if is_grail else ""
                        print(f"  ✅ conf={conf:.1f} {flip_speed} profit={flip_profit:.0f} {deal_tag}{grail_tag} brand={detected_brand} | {item['title'][:28]}")

                    cycle_candidates.append((conf, search, item, eval_result, now))
                else:
                    # Bez engine — stary fallback
                    msg = format_message(search, item)
                    photo = item.get("photo") or get_item_photo(item["id"], item["link"])
                    send_message(msg, photo_url=photo, item_link=item.get("link"))
                    seen[item["id"]] = now
                    print(f"  ✉️ {item['title'][:55]} | {item['price']:.0f} zł")

        # Step 6 — sortuj DESC po confidence, wyślij max 10 per cykl
        cycle_candidates.sort(key=lambda x: x[0], reverse=True)
        sent_this_cycle = 0
        MAX_PER_CYCLE   = 5

        for conf, search, item, eval_result, now in cycle_candidates:
            if sent_this_cycle >= MAX_PER_CYCLE:
                seen[item["id"]] = now
                continue

            photo = item.get("photo") or get_item_photo(item["id"], item["link"])

            # Tryby specjalne (football/lego_sw/carhartt)
            if eval_result is None:
                msg = format_message(search, item)
                send_message(msg, photo_url=photo, item_link=item.get("link"))
                seen[item["id"]] = now
                sent_this_cycle += 1
                tag = "⚽" if search.get("football_mode") else "🧱"
                print(f"  {tag} {item['title'][:55]} | {item['price']:.0f} zł")
                continue

            tier        = eval_result.get("tier")
            is_grail    = eval_result.get("is_grail", False)
            flip_profit = eval_result.get("flip_profit", 0)
            confidence  = eval_result.get("confidence", 0)

            # Fix #6+7 — DEBUG send respektuje nowe progi: profit>=30, conf>=6
            if DEBUG_ALERTS and flip_profit >= 30 and confidence >= 6.0:
                engine_msg = engine.format_alert(eval_result)
                b_tag = detected_brand or "⛔NO-BRAND"
                print(f"  📤 TG SEND: conf={confidence:.1f} profit={flip_profit:.0f} brand={b_tag} | {item['title'][:40]}")
                send_message(engine_msg, photo_url=photo, item_link=item.get("link"))
                seen[item["id"]] = now
                sent_this_cycle += 1
                continue

            # Fix 1 — minimalne progi profitu per tier (zapobiega spam 10 zł)
            MIN_PROFIT_TIER = {
                "INSANE":    10,
                "💎 GRAIL":  10,
                "GOOD":      25,
                "WATCH":     40,
            }
            min_p = MIN_PROFIT_TIER.get(tier, 40)
            if is_grail:
                min_p = 10   # grail override

            if flip_profit < min_p and not is_grail:
                print(f"  ⏭  profit skip ({flip_profit:.0f}<{min_p}zł) | {item['title'][:40]}")
                seen[item["id"]] = now
                continue

            # Fix 1 — tylko INSANE/GOOD/GRAIL wysyłamy przez engine format
            # WATCH i poniżej → tylko jeśli grail
            if tier in ("INSANE", "GOOD", "💎 GRAIL") or is_grail:
                engine_msg = engine.format_alert(eval_result)
                if DEBUG_ALERTS:
                    print(f"  📤 TG SEND: {engine_msg[:80]}")
                send_message(engine_msg, photo_url=photo, item_link=item.get("link"))
                seen[item["id"]] = now
                sent_this_cycle += 1
                tier_tag = "💎" if is_grail else ("🔴" if tier == "INSANE" else "🟡")
                print(f"  {tier_tag} [{tier}] conf={conf:.1f} profit={flip_profit:.0f} | {item['title'][:40]}")
            else:
                # WATCH / brak tier → pomijamy (zbyt słabe)
                seen[item["id"]] = now

        # ── PART 3 — FALLBACK: if 0 sent, re-scan with 120-min window ────────
        if sent_this_cycle == 0:
            print(f"  ⚠️ FALLBACK MODE — brak wyników, rozszerzam okno do 120 min")
            for search in SEARCHES:
                if search.get("football_mode") or search.get("lego_sw_mode") or search.get("carhartt_mode"):
                    continue  # special modes have their own validators, skip fallback
                fallback_search = dict(search, _fallback_mode=True)
                market_price    = market_prices.get(search["name"])
                fb_items, fb_ids = check_search(fallback_search, seen, market_price)
                if not fb_items:
                    continue
                now = time.time()
                for _id in fb_ids:
                    if _id not in seen:
                        seen[_id] = now
                for item in fb_items[:2]:  # max 2 per search in fallback
                    if not engine:
                        break
                    eval_result = engine.evaluate(item, search, market_price)
                    if not eval_result.get("send_alert"):
                        seen[item["id"]] = now
                        continue
                    tier        = eval_result.get("tier")
                    flip_profit = eval_result.get("flip_profit", 0)
                    is_grail    = eval_result.get("is_grail", False)
                    if tier not in ("INSANE", "GOOD", "💎 GRAIL") and not is_grail:
                        seen[item["id"]] = now
                        continue
                    photo      = item.get("photo") or get_item_photo(item["id"], item["link"])
                    engine_msg = engine.format_alert(eval_result)
                    send_message(engine_msg, photo_url=photo, item_link=item.get("link"))
                    seen[item["id"]] = now
                    sent_this_cycle += 1
                    print(f"  🔁 FALLBACK SEND | {item['title'][:55]} | {item['price']:.0f} zł")
                    if sent_this_cycle >= MAX_PER_CYCLE:
                        break
                if sent_this_cycle >= MAX_PER_CYCLE:
                    break

        print(f"  📊 Cykl #{cycle} zakończony — wysłano: {sent_this_cycle} alertów")

        save_seen(seen)
        time.sleep(SLEEP_BETWEEN_CYCLES)

    except Exception as e:
        print(f"Błąd głównej pętli: {e}")
        time.sleep(15)
