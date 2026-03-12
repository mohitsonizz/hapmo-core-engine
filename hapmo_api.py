from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.sync_api import sync_playwright
import re
import sqlite3
import json
from datetime import datetime, timedelta

# Initialize the API Server
app = FastAPI(title="Hapmo Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATABASE SETUP (Built-in SQLite) ---
def init_db():
    conn = sqlite3.connect("hapmo_cache.db")
    cursor = conn.cursor()
    # Create a table to store search results
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_cache (
            query TEXT PRIMARY KEY,
            result_json TEXT,
            timestamp DATETIME
        )
    ''')
    conn.commit()
    conn.close()

init_db() # Run database setup on startup

def clean_price(price_str):
    try:
        clean_str = re.sub(r'[^0-9]', '', price_str)
        return int(clean_str)
    except ValueError:
        return 9999999

def get_amazon_data(page, search_query):
    url = f"https://www.amazon.in/s?k={search_query.replace(' ', '+')}"
    try:
        page.goto(url, timeout=15000)
        page.wait_for_selector(".s-main-slot", timeout=10000)
        first_organic_product = page.locator('div[data-component-type="s-search-result"]').first
        
        title_element = first_organic_product.locator(".a-size-medium.a-color-base.a-text-normal").first
        price_element = first_organic_product.locator(".a-price-whole").first
        
        title = title_element.inner_text() if title_element.count() > 0 else "Not found"
        price_str = price_element.inner_text() if price_element.count() > 0 else "0"
        
        return {"store": "Amazon", "title": title, "price": f"₹{price_str}", "price_int": clean_price(price_str), "link": url}
    except Exception:
        return {"store": "Amazon", "title": "Error fetching", "price": "N/A", "price_int": 9999999, "link": url}

def get_flipkart_data(page, search_query):
    url = f"https://www.flipkart.com/search?q={search_query.replace(' ', '+')}"
    try:
        page.goto(url, timeout=15000)
        page.wait_for_selector("div[data-id]", timeout=10000)
        first_product = page.locator("div[data-id]").first
        image_locator = first_product.locator("img").first
        title = image_locator.get_attribute("alt") if image_locator.count() > 0 else "Not found"
        
        product_text = first_product.inner_text()
        price_match = re.search(r'₹[0-9,]+', product_text)
        price_str = price_match.group(0) if price_match else "0"
        
        return {"store": "Flipkart", "title": title, "price": price_str, "price_int": clean_price(price_str), "link": url}
    except Exception:
        return {"store": "Flipkart", "title": "Error fetching", "price": "N/A", "price_int": 9999999, "link": url}

@app.get("/search")
def search_product(q: str):
    # Normalize the query (lowercase, remove extra spaces) to ensure matching
    query_clean = q.strip().lower()
    
    # 1. CHECK DATABASE FIRST (The Speed Boost)
    conn = sqlite3.connect("hapmo_cache.db")
    cursor = conn.cursor()
    cursor.execute("SELECT result_json, timestamp FROM search_cache WHERE query=?", (query_clean,))
    row = cursor.fetchone()
    
    if row:
        saved_time = datetime.fromisoformat(row[1])
        # If the data is less than 12 hours old, return it instantly!
        if datetime.now() - saved_time < timedelta(hours=12):
            print(f"⚡ FAST CACHE HIT: Returning saved data for '{query_clean}' in 0.1 seconds!")
            conn.close()
            return json.loads(row[0])
            
    # 2. IF NOT IN DATABASE, SCRAPE THE WEB (Takes 15 seconds)
    print(f"🐌 CACHE MISS: Scraping live internet for '{query_clean}'...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context()
        amazon_page = context.new_page()
        flipkart_page = context.new_page()
        
        amazon_result = get_amazon_data(amazon_page, q)
        flipkart_result = get_flipkart_data(flipkart_page, q)
        
        browser.close()
        
    results = [amazon_result, flipkart_result]
    results.sort(key=lambda x: x['price_int'])
    
    final_response = {
        "status": "success",
        "search_query": q,
        "winner": results[0]["store"] if results[0]["price_int"] != 9999999 else "None",
        "data": results
    }
    
    # 3. SAVE THE NEW DATA TO DATABASE FOR NEXT TIME
    cursor.execute('''
        INSERT OR REPLACE INTO search_cache (query, result_json, timestamp) 
        VALUES (?, ?, ?)
    ''', (query_clean, json.dumps(final_response), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    

    return final_response
