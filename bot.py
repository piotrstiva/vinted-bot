import requests
from bs4 import BeautifulSoup
import time
import os
import json

# ─────────────────────────────────────────
#  🔑 USTAWIENIA — Railway Variables
# ─────────────────────────────────────────
TOKEN   = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
}

# ─────────────────────────────────────────
#  🔍 WYSZUKIWANIA — dodaj / edytuj swoje
# ─────────────────────────────────────────
SEARCHES = [
    {
        "name": "Nike Dunk 42",
        "url": "https://www.vinted.pl/catalog?search_text=carhartt&search_id=33346027533&brand_ids[]=362&brand_ids[]=872289&page=1&time=1776857351&catalog[]=1206&price_to=200&currency=PLN",

        # 💬 słowa kluczowe — oferta MUSI zawierać przynajmniej jedno
        "keywords": ["nike", "dunk", "air force", "jordan"],

        # 💰 filtr ceny (PLN)
        "min_price": 50,
        "max_price": 200,
    },
    # Możesz dodać więcej wyszukiwań:
    # {
    #     "name": "Adidas 41",
    #     "url": "TU_WKLEJ_LINK",
    #     "keywords": ["adidas", "yeezy", "ultraboost"],
    #     "min_price": 80,
    #     "max_price": 300,
    # },
]

# ─────────────────────────────────────────
#  💾 PAMIĘĆ — już widzianych ofert
#  (żeby nie wysyłać duplikatów)
# ─────────────────────────────────────────
SEEN_FILE = "seen_items.json"

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

# ─────────────────────────────────────────
#  📤 WYSYŁANIE NA TELEGRAM
# ─────────────────────────────────────────
def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code != 200:
            print(f"Telegram error: {r.text}")
    except Exception as e:
        print(f"Błąd wysyłania: {e}")

# ─────────────────────────────────────────
#  🕵️ POBIERANIE OFERT Z VINTED
# ─────────────────────────────────────────
def extract_price(text):
    """Wyciąga liczbę z tekstu, np. '150 zł' → 150"""
    import re
    nums = re.findall(r"\d+[\.,]?\d*", text.replace(" ", ""))
    if nums:
        return float(nums[0].replace(",", "."))
    return None

def check_search(search, seen):
    new_items = []
    try:
        r = requests.get(search["url"], headers=HEADERS, timeout=15)
        print(f"[{search['name']}] HTTP {r.status_code}")

        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")

        # Szukamy TYLKO bezpośrednich linków do ofert (/items/)
        all_links = soup.find_all("a", href=True)
        item_links = [
            a for a in all_links
            if "/items/" in a.get("href", "")
        ]

        print(f"[{search['name']}] Znaleziono ofert: {len(item_links)}")

        for tag in item_links:
            href = tag["href"]

            # Buduj pełny URL
            if not href.startswith("http"):
                href = "https://www.vinted.pl" + href

            # Wyciągnij ID oferty (unikalne)
            item_id = href.split("/items/")[1].split("-")[0].split("?")[0]

            # Pomijaj już widziane
            if item_id in seen:
                continue

            # Tekst oferty
            title = tag.get_text(" ", strip=True)

            # ── Filtr słów kluczowych ──
            keywords = search.get("keywords", [])
            if keywords:
                if not any(kw.lower() in title.lower() for kw in keywords):
                    continue

            # ── Filtr ceny ──
            price = extract_price(title)
            min_p = search.get("min_price")
            max_p = search.get("max_price")

            if price is not None:
                if min_p and price < min_p:
                    continue
                if max_p and price > max_p:
                    continue

            price_str = f"{price:.0f} zł" if price else "brak ceny"

            new_items.append({
                "id":    item_id,
                "title": title,
                "link":  href,
                "price": price_str,
            })

    except Exception as e:
        print(f"Błąd check_search [{search['name']}]: {e}")

    return new_items

# ─────────────────────────────────────────
#  ✉️ FORMAT WIADOMOŚCI
# ─────────────────────────────────────────
def format_message(search_name, item):
    return (
        f"🛍 <b>Nowa oferta!</b>\n"
        f"🔎 Wyszukiwanie: <i>{search_name}</i>\n\n"
        f"📦 {item['title']}\n\n"
        f"💰 Cena: <b>{item['price']}</b>\n\n"
        f"🔗 <a href=\"{item['link']}\">Otwórz ofertę na Vinted</a>"
    )

# ─────────────────────────────────────────
#  🚀 GŁÓWNA PĘTLA
# ─────────────────────────────────────────
print("✅ BOT URUCHOMIONY")
send_message("✅ Bot Vinted uruchomiony i działa!")

seen = load_seen()

while True:
    try:
        for search in SEARCHES:
            new_items = check_search(search, seen)

            for item in new_items:
                msg = format_message(search["name"], item)
                send_message(msg)
                seen.add(item["id"])
                print(f"✉️ Wysłano: {item['title'][:60]}")

            save_seen(seen)

        time.sleep(60)  # sprawdzaj co 60 sekund

    except Exception as e:
        print(f"Błąd głównej pętli: {e}")
        time.sleep(15)
