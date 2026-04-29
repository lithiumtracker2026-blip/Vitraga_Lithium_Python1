import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from insert_queries import check_stock_news_url_exists
from database_operations import insert_substack_post, check_substack_url_exists
from database_config import get_curser
import re
import os
import logging

try:
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    ChromeDriverManager = None


def init_driver():
    """Initialize Chrome WebDriver"""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--disable-setuid-sandbox")
        chrome_options.add_argument("--window-size=1024,768")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        
        # Try to use webdriver_manager first (best for containers)
        if ChromeDriverManager:
            try:
                driver = webdriver.Chrome(
                    service=Service(ChromeDriverManager().install()),
                    options=chrome_options
                )
                logging.info("Chrome WebDriver initialized with webdriver_manager")
            except Exception as e:
                logging.warning(f"webdriver_manager failed: {e}, trying direct path...")
                # Fallback to direct paths if webdriver_manager fails
                chrome_options.binary_location = "/usr/bin/chromium"
                service = Service("/usr/bin/chromedriver")
                driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            # Fallback if webdriver_manager not available
            chrome_options.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=chrome_options)
        
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(5)
        return driver
    except Exception as e:
        logging.error(f"Failed to initialize Chrome WebDriver: {str(e)}")
        return None


def wait_and_find_element(driver, by, value, timeout=10):
    """Helper function to wait for and find an element"""
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )
        return element
    except TimeoutException:
        return None


def scrape_substack_lithium_posts(cursor=None, max_posts=10):
    """
    Scrapes lithium-related posts from Substack.
    """
    driver = None
    scraped_data = []
    try:
        driver = init_driver()
        if not driver:
            logging.error("Failed to initialize WebDriver - Substack scraping will be skipped")
            return []

        # Navigate to the search page
        print("Navigating to Substack search page...")
        search_url = "https://substack.com/search/lithium?sort=new&searching=all_posts&include_recommendations=false"
        driver.get(search_url)

        # Wait for the search results to load
        print("Waiting for search results...")
        wait_and_find_element(driver, By.CLASS_NAME, "search-result")
        time.sleep(2)

        # Scroll to load more content
        print("Loading more content...")
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        # Find article links
        print("Finding article links...")
        links = driver.find_elements(By.CSS_SELECTOR, "a.post-preview-title")
        if not links:
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")

        print(f"Found {len(links)} links")

        # Extract unique URLs
        urls, seen_urls = [], set()
        for link in links:
            url = link.get_attribute('href')
            if url and url not in seen_urls and '/p/' in url:
                urls.append(url)
                seen_urls.add(url)
                if len(urls) >= max_posts:
                    break

        print(f"Found {len(urls)} unique URLs to scrape")

        # Scrape each article
        for url in urls:
            try:
                print(f"Scraping URL: {url}")
                driver.get(url)

                article = wait_and_find_element(driver, By.TAG_NAME, "article", timeout=10)
                if not article:
                    print("Article content not found, skipping...")
                    continue

                # Title
                title = None
                for selector in ["h1.post-title", "h1.title", "h1"]:
                    title_elem = wait_and_find_element(driver, By.CSS_SELECTOR, selector, timeout=5)
                    if title_elem:
                        title = title_elem.text.strip()
                        break

                # Content
                content_elem = wait_and_find_element(driver, By.CSS_SELECTOR, "div.available-content", timeout=5) or article
                content = content_elem.text.strip() if content_elem else ""

                # Date
                date = datetime.now().strftime("%Y-%m-%d")
                date_elem = wait_and_find_element(driver, By.TAG_NAME, "time", timeout=5)
                if date_elem:
                    date_str = date_elem.get_attribute("datetime")
                    if date_str:
                        date = date_str.split("T")[0]

                # Image
                image_url = ""
                try:
                    img_elem = article.find_element(By.TAG_NAME, "img")
                    if img_elem:
                        image_url = img_elem.get_attribute("src")
                except:
                    pass

                if title and content:
                    scraped_data.append({
                        "title": title,
                        "url": url,
                        "content": content,
                        "subtitle": "",
                        "image_url": image_url,
                        "date": date
                    })
                    print(f"Successfully scraped: {title[:50]}...")
                else:
                    print("Skipping article due to missing title or content")

            except Exception as e:
                print(f"Error scraping URL {url}: {str(e)}")
                continue

        print(f"Successfully scraped {len(scraped_data)} Substack posts")
        return scraped_data

    except Exception as e:
        print(f"Error in scraping Substack: {str(e)}")
        return []
    finally:
        if driver:
            driver.quit()



def insert_substack_posts_to_db(cursor, connection, posts):
    """
    Inserts scraped Substack posts into the database using insert_substack_post.
    
    Parameters:
        cursor (psycopg2.cursor): Database cursor
        connection (psycopg2.connection): Database connection
        posts (list): List of formatted post dictionaries
    """
    successful_inserts = 0
    for post in posts:
        try:
            # Check if URL already exists
            if not check_substack_url_exists(cursor, post["url"]):
                insert_substack_post(
                    cursor=cursor,
                    connection=connection,
                    **post
                )
                successful_inserts += 1
                print(f"Successfully inserted: {post['title'][:50]}...")
            else:
                print(f"Skipping duplicate post: {post['title'][:50]}...")
        except Exception as e:
            print(f"Error inserting post '{post['title'][:50]}...': {str(e)}")
            continue
    
    print(f"Inserted {successful_inserts} out of {len(posts)} posts")


def ensure_table_exists(cursor, connection):
    """
    Ensures that the lithium_substack table exists in the database.
    Creates it if it doesn't exist.
    """
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_app_lithiumsubstack (
                id VARCHAR(255) PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                content TEXT,
                subtitle TEXT,
                image_url TEXT,
                date DATE NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.commit()
        print("Table api_app_lithiumsubstack is ready")
    except Exception as e:
        print(f"Error ensuring table exists: {str(e)}")
        raise e


if __name__ == "__main__":
    # When run directly, scrape and insert into database
    connection, cursor = get_curser()
    
    try:
        # Ensure table exists
        ensure_table_exists(cursor, connection)
        
        print("Starting Substack lithium posts scraping...")
        posts = scrape_substack_lithium_posts(cursor)
        if posts:
            print(f"Found {len(posts)} posts. Inserting into database...")
            insert_substack_posts_to_db(cursor, connection, posts)
        else:
            print("No posts found to insert")
    except Exception as e:
        print(f"Error in main execution: {str(e)}")
    finally:
        connection.close()
        print("Database connection closed")

