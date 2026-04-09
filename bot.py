import requests
from bs4 import BeautifulSoup
import time
import json
import os

# 🔑 zmienne z Railway
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ⚙️ KONFIGURACJA
SEARCHES = [
    {
        "name": "Nike 42",
        "url": "https://www.vinted.pl/catalog?search_id=32942754045&catalog[]=1206&size_ids[]=208&size_ids[]=209&size_ids[]=210&page=1&time=1775767599&brand_ids[]=872289&brand_ids[]=362&price_to=200&currency=PLN&order=newest_first",
        "keywords": ["dunk", "low"],
        "brands": ["nike"],
        "min_price": 100,
        "max_price": 300
    }
]

STEAL_THRESHOLD = 0.6
SEEN_FILE = "seen.json"
headers = {"User-Agent": "Mozilla/5.0"}


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def send_photo(caption, link, image_url):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

    data = {
        "chat_id": CHAT_ID,
        "caption": caption,
        "photo": image_url,
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "🔎 Otwórz ofertę", "url": link}]
            ]
        }
    }

    requests.post(url, json=data)


def extract_price(text):
    try:
        text = text.replace("zł", "").replace(",", ".")
        numbers = "".join(c for c in text if c.isdigit() or c == ".")
        return float(numbers)
    except:
        return None


def calculate_average(prices):
    prices = [p for p in prices if p is not None]
    if not prices:
        return None
    return sum(prices) / len(prices)


def check_search(search, seen):
    results = []
    prices = []

    r = requests.get(search["url"], headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    items = soup.select("a[data-testid='item-link']")

    # średnia cena
    for item in items:
        text = item.get_text(" ", strip=True)
        price = extract_price(text)
        if price:
            prices.append(price)

    avg_price = calculate_average(prices)

    for item in items:
        link = "https://www.vinted.pl" + item.get("href")

        if link in seen:
            continue

        text = item.get_text(" ", strip=True).lower()

        # frazy
        if search.get("keywords"):
            if not any(k in text for k in search["keywords"]):
                continue

        # marki
        if search.get("brands"):
            if not any(b in text for b in search["brands"]):
                continue

        price = extract_price(text)

        if price:
            if price < search.get("min_price", 0):
                continue
            if price > search.get("max_price", 999999):
                continue

        # zdjęcie
        img_tag = item.find("img")
        image_url = img_tag["src"] if img_tag else None

        if not image_url:
            continue

        # steal finder
        is_steal = False
        if avg_price and price:
            if price < avg_price * STEAL_THRESHOLD:
                is_steal = True

        seen.add(link)
        results.append((text, price, link, image_url, search["name"], is_steal, avg_price))

    return results


# 🚀 START
seen = load_seen()

print("🔥 Bot działa...")

while True:
    try:
        for search in SEARCHES:
            print("CHECKING VINTED...")
            print(search["name"])
        
            new_items = check_search(search, seen)

            for title, price, link, image_url, name, is_steal, avg_price in new_items:

                if is_steal:
                    caption = f"""🚨 OKAZJA!

{name}
{title}

💰 {price} zł
📉 średnia: {round(avg_price)} zł
"""
                else:
                    caption = f"""🆕 {name}

{title}
💰 {price} zł
"""

                send_photo(caption, link, image_url)

        save_seen(seen)

        time.sleep(120)

    except Exception as e:
        print("Błąd:", e)
        time.sleep(120)
