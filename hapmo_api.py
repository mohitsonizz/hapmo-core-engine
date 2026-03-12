from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.sync_api import sync_playwright
import re
import sqlite3
import json
from datetime import datetime, timedelta

app = FastAPI(title="Hapmo Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- DATABASE ----------------

def init_db():
    conn = sqlite3.connect("hapmo_cache.db")
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_cache (
            query TEXT PRIMARY KEY,
            result_json TEXT,
            timestamp DATETIME
        )
    ''')

    conn.commit()
    conn.close()

init_db()

# ---------------- HELPERS ----------------

def clean_price(price_str):
    try:
        clean_str = re.sub(r'[^0-9]', '', price_str)
        return int(clean_str)
    except:
        return 9999999


def block_heavy_resources(route):
    if route.request.resource_type in ["image", "stylesheet", "media", "font"]:
        route.abort()
    else:
        route.continue_()

# ---------------- AMAZON SCRAPER ----------------

def get_amazon_data(page, search_query):

    page.route("**/*", block_heavy_resources)

    url = f"https://www.amazon.in/s?k={search_query.replace(' ', '+')}"

    try:

        page.goto(url, timeout=20000)

        page.wait_for_selector(".s-main-slot", timeout=10000)

        first_product = page.locator(
            'div[data-component-type="s-search-result"]'
        ).first

        title_el = first_product.locator(
            ".a-size-medium.a-color-base.a-text-normal"
        ).first

        price_el = first_product.locator(".a-price-whole").first

        title = title_el.inner_text() if title_el.count() else "Not found"

        price_str = price_el.inner_text() if price_el.count() else "0"

        return {
            "store": "Amazon",
            "title": title,
            "price": f"₹{price_str}",
            "price_int": clean_price(price_str),
            "link": url
        }

    except Exception as e:

        print("Amazon Error:", e)

        return {
            "store": "Amazon",
            "title": "Error fetching",
            "price": "N/A",
            "price_int": 9999999,
            "link": url
        }

# ---------------- FLIPKART SCRAPER ----------------

def get_flipkart_data(page, search_query):

    page.route("**/*", block_heavy_resources)

    url = f"https://www.flipkart.com/search?q={search_query.replace(' ', '+')}"

    try:

        page.goto(url, timeout=20000)

        # Close login popup
        try:
            page.locator("button:has-text('✕')").click(timeout=3000)
        except:
            pass

        # wait for products
        page.wait_for_selector("a[href*='/p/']", timeout=15000)

        first_product = page.locator("a[href*='/p/']").first

        title = first_product.get_attribute("title")

        if not title:
            title = first_product.inner_text()

        container = first_product.locator("xpath=ancestor::div[1]")

        text = container.inner_text()

        price_match = re.search(r'₹[0-9,]+', text)

        price_str = price_match.group(0) if price_match else "0"

        link = first_product.get_attribute("href")

        if link:
            link = "https://www.flipkart.com" + link
        else:
            link = url

        return {
            "store": "Flipkart",
            "title": title if title else "Not found",
            "price": price_str,
            "price_int": clean_price(price_str),
            "link": link
        }

    except Exception as e:

        print("Flipkart Error:", e)

        return {
            "store": "Flipkart",
            "title": "Error fetching",
            "price": "N/A",
            "price_int": 9999999,
            "link": url
        }

# ---------------- SEARCH API ----------------

@app.get("/search")
def search_product(q: str):

    query_clean = q.strip().lower()

    conn = sqlite3.connect("hapmo_cache.db")

    cursor = conn.cursor()

    cursor.execute(
        "SELECT result_json, timestamp FROM search_cache WHERE query=?",
        (query_clean,)
    )

    row = cursor.fetchone()

    if row:

        saved_time = datetime.fromisoformat(row[1])

        if datetime.now() - saved_time < timedelta(hours=12):

            conn.close()

            return json.loads(row[0])

    # -------- SCRAPING --------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        # Bot ko aur zyada "Human" banate hain
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}, # Badi screen size
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9,hi;q=0.8", # Normal language settings
                "Referer": "https://www.google.com/" # Flipkart ko lagega hum Google search karke aaye hain
            }
        )

        amazon_page = context.new_page()

        amazon_result = get_amazon_data(amazon_page, q)

        amazon_page.close()

        flipkart_page = context.new_page()

        flipkart_result = get_flipkart_data(flipkart_page, q)

        flipkart_page.close()

        browser.close()

    # -------- SORT RESULTS --------

    results = [amazon_result, flipkart_result]

    results.sort(key=lambda x: x["price_int"])

    final_response = {
        "status": "success",
        "search_query": q,
        "winner": results[0]["store"] if results[0]["price_int"] != 9999999 else "None",
        "data": results
    }

    cursor.execute(
        '''
        INSERT OR REPLACE INTO search_cache (query, result_json, timestamp)
        VALUES (?, ?, ?)
        ''',
        (query_clean, json.dumps(final_response), datetime.now().isoformat())
    )

    conn.commit()

    conn.close()

    return final_response

