import requests
from bs4 import BeautifulSoup
import time
import os

# 🔑 Railway Variables
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

headers = {"User-Agent": "Mozilla/5.0"}

# 👉 TU WSTAW SWOJE WYSZUKIWANIA
SEARCHES = [
    {
        "name": "Nike 42",
         "url": "https://www.vinted.pl/catalog?search_id=32942754045&catalog[]=1206&size_ids[]=208&size_ids[]=209&size_ids[]=210&page=1&time=1775767599&brand_ids[]=872289&brand_ids[]=362&price_to=200&currency=PLN&order=newest_first"    }
]


def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text
    }
    requests.post(url, data=data)


def check_search(search):
    try:
        print("CHECKING VINTED...")
        print(search["name"])

        r = requests.get(search["url"], headers=headers)

        print("HTTP STATUS:", r.status_code)

        soup = BeautifulSoup(r.text, "html.parser")

        items = soup.find_all("a")

        print("ITEMS FOUND:", len(items) if items else 0)

        results = []

        for item in items[:10]:  # limit testowy
            text = item.get_text(" ", strip=True)

            if not text:
                continue

            link = item.get("href")

            if link:
                if not link.startswith("http"):
                    link = "https://www.vinted.pl" + link

                results.append((text, link))

        return results

    except Exception as e:
        print("ERROR:", e)
        return []


print("BOT STARTED")

while True:
    try:
        for search in SEARCHES:
            results = check_search(search)

            for title, link in results:
                message = f"""🆕 {search['name']}

{title}

🔗 {link}
"""
                send_message(message)

        time.sleep(60)

    except Exception as e:
        print("CRASH:", e)
        time.sleep(10)
