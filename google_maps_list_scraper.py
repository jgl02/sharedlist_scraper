#!/usr/bin/env python3
"""
Google Maps Saved List Scraper
Scrapes places from a public Google Maps saved list including notes.
Designed for use with n8n automation workflows via GitHub Actions.

Requirements:
    pip install selenium webdriver-manager beautifulsoup4 pandas

Usage:
    python google_maps_list_scraper.py --url "YOUR_GOOGLE_MAPS_LIST_URL" --city "Chicago" --output "output.csv"
    
    Or import and use programmatically:
    from google_maps_list_scraper import scrape_google_maps_list
    data = scrape_google_maps_list(url, city="Chicago")
"""

import argparse
import json
import re
import time
import timeit
from typing import Optional
from urllib.parse import unquote

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager


def setup_driver(headless: bool = True) -> webdriver.Chrome:
    """
    Initialize Chrome WebDriver with appropriate options.
    
    Args:
        headless: Run browser in headless mode (no GUI)
    
    Returns:
        Configured Chrome WebDriver instance
    """
    chrome_options = Options()
    
    if headless:
        chrome_options.add_argument("--headless=new")
    
    # Common options for stability
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Suppress logging
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    return driver


def scroll_to_load_all(driver: webdriver.Chrome, scroll_pause: float = 2.0, max_scrolls: int = 100) -> None:
    """
    Scroll the Google Maps sidebar to load all listings.
    
    Args:
        driver: Selenium WebDriver instance
        scroll_pause: Time to wait between scrolls (seconds)
        max_scrolls: Maximum number of scroll attempts
    """
    # Try multiple possible XPaths for the scrolling element
    scrolling_element_xpaths = [
        '/html/body/div[3]/div[9]/div[8]/div/div[1]/div/div/div[5]',
        '//div[@role="feed"]',
        '//div[contains(@class, "m6QErb") and contains(@class, "DxyBCb")]',
        '//div[@aria-label and contains(@class, "m6QErb")]',
    ]
    
    scrolling_element = None
    for xpath in scrolling_element_xpaths:
        try:
            scrolling_element = driver.find_element(By.XPATH, xpath)
            if scrolling_element:
                break
        except NoSuchElementException:
            continue
    
    if not scrolling_element:
        # Try CSS selector as fallback
        try:
            scrolling_element = driver.find_element(By.CSS_SELECTOR, 'div.m6QErb.DxyBCb.kA9KIf.dS8AEf')
        except NoSuchElementException:
            print("Warning: Could not find scrolling element. Attempting to scroll page body.")
            scrolling_element = driver.find_element(By.TAG_NAME, 'body')
    
    last_height = driver.execute_script("return arguments[0].scrollHeight", scrolling_element)
    scroll_count = 0
    
    print(f"Starting scroll... Initial height: {last_height}")
    
    while scroll_count < max_scrolls:
        # Scroll down
        driver.execute_script('arguments[0].scrollTo(0, arguments[0].scrollHeight)', scrolling_element)
        time.sleep(scroll_pause)
        
        # Calculate new scroll height
        new_height = driver.execute_script("return arguments[0].scrollHeight", scrolling_element)
        
        if new_height == last_height:
            print(f"Reached end after {scroll_count + 1} scrolls")
            break
        
        last_height = new_height
        scroll_count += 1
        print(f"Scroll {scroll_count}: height = {new_height}")
    
    if scroll_count >= max_scrolls:
        print(f"Warning: Reached maximum scroll limit ({max_scrolls})")


def extract_lat_lng(url: str) -> tuple:
    """
    Extract latitude and longitude from a Google Maps URL.
    
    Args:
        url: Google Maps place URL
    
    Returns:
        Tuple of (latitude, longitude) or (None, None) if not found
    """
    if not url:
        return None, None
    
    # Pattern for URLs like: @1.3059187,103.8293246,17z
    match = re.search(r'@(-?\d+\.?\d*),(-?\d+\.?\d*)', url)
    if match:
        return match.group(1), match.group(2)
    
    # Alternative pattern in URL path
    match = re.search(r'/place/[^/]+/@(-?\d+\.?\d*),(-?\d+\.?\d*)', url)
    if match:
        return match.group(1), match.group(2)
    
    return None, None


def extract_notes_from_page(driver: webdriver.Chrome) -> dict:
    """
    Extract notes for each place by finding textarea elements with aria-label="Note".
    Returns a dictionary mapping place identifiers to their notes.
    
    Args:
        driver: Selenium WebDriver instance
    
    Returns:
        Dictionary mapping place name/URL to note content
    """
    notes_dict = {}
    
    try:
        # Find all note textareas
        note_elements = driver.find_elements(By.CSS_SELECTOR, 'textarea[aria-label="Note"]')
        
        # Also try finding by class name patterns from the provided HTML
        if not note_elements:
            note_elements = driver.find_elements(By.CSS_SELECTOR, 'textarea.MP5iJf')
        
        print(f"Found {len(note_elements)} note elements")
        
        for i, note_elem in enumerate(note_elements):
            try:
                note_text = note_elem.get_attribute('value') or note_elem.text or ""
                if note_text.strip():
                    # Try to find the associated place name
                    parent = note_elem
                    place_name = None
                    
                    # Traverse up to find the place container
                    for _ in range(10):
                        try:
                            parent = parent.find_element(By.XPATH, '..')
                            # Look for place name in parent
                            place_elem = parent.find_elements(By.CSS_SELECTOR, 'div.fontHeadlineSmall, div.qBF1Pd')
                            if place_elem:
                                place_name = place_elem[0].text
                                break
                        except:
                            break
                    
                    if place_name:
                        notes_dict[place_name] = note_text.strip()
                    else:
                        notes_dict[f"place_{i}"] = note_text.strip()
                        
            except Exception as e:
                print(f"Error extracting note {i}: {e}")
                continue
                
    except Exception as e:
        print(f"Error finding note elements: {e}")
    
    return notes_dict


def parse_listings(soup: BeautifulSoup, notes_dict: dict = None, city: str = None) -> list:
    """
    Parse place listings from BeautifulSoup object.
    
    Args:
        soup: BeautifulSoup parsed HTML
        notes_dict: Dictionary of place names to notes
        city: City name to tag each place with
    
    Returns:
        List of dictionaries containing place information
    """
    places = []
    notes_dict = notes_dict or {}
    
    # Find all place containers - try multiple selectors
    place_containers = soup.find_all('div', class_='Nv2PK')
    
    if not place_containers:
        # Alternative selector
        place_containers = soup.find_all('div', {'jsaction': re.compile(r'mouseover:pane')})
    
    print(f"Found {len(place_containers)} place containers")
    
    for container in place_containers:
        place_data = {
            'place': None,
            'address': None,
            'category': None,
            'rating': None,
            'url': None,
            'note': None,
            'lat': None,
            'lng': None,
            'city': city  # Add city tag to each place
        }
        
        try:
            # Extract place name
            name_elem = container.find('div', class_='fontHeadlineSmall')
            if not name_elem:
                name_elem = container.find('div', class_='qBF1Pd')
            if name_elem:
                place_data['place'] = name_elem.get_text(strip=True)
            
            # Extract URL from anchor tag
            link_elem = container.find('a', href=True)
            if link_elem:
                place_data['url'] = link_elem['href']
                # Extract lat/lng from URL
                lat, lng = extract_lat_lng(place_data['url'])
                place_data['lat'] = lat
                place_data['lng'] = lng
            
            # Extract address and other details
            detail_divs = container.find_all('div', class_='W4Efsd')
            
            for div in detail_divs:
                text = div.get_text(strip=True)
                
                # Skip empty or very short text
                if not text or len(text) < 2:
                    continue
                
                # Check for rating (usually in format "4.5(123)")
                rating_match = re.search(r'^(\d+\.?\d*)\s*\(', text)
                if rating_match:
                    place_data['rating'] = rating_match.group(1)
                    continue
                
                # Check for category (usually single word or short phrase without numbers)
                if not place_data['category'] and len(text) < 30 and not any(c.isdigit() for c in text):
                    # Categories often contain specific keywords
                    if any(keyword in text.lower() for keyword in 
                           ['restaurant', 'cafe', 'bar', 'shop', 'store', 'hotel', 
                            'museum', 'park', 'food', 'cuisine', 'grill', 'bakery',
                            'ice cream', 'burger', 'pizza', 'sushi', 'steak']):
                        place_data['category'] = text
                        continue
                
                # Otherwise, it's likely an address (contains numbers and/or longer text)
                if not place_data['address'] and (any(c.isdigit() for c in text) or len(text) > 20):
                    # Clean up the address
                    # Remove common prefixes that might be caught
                    address = text
                    if ' · ' in address:
                        parts = address.split(' · ')
                        # The address is usually the part with numbers
                        for part in parts:
                            if any(c.isdigit() for c in part) and len(part) > 5:
                                address = part
                                break
                    place_data['address'] = address
            
            # Try to get category from different element if not found
            if not place_data['category']:
                category_spans = container.find_all('span', class_='W4Efsd')
                for span in category_spans:
                    text = span.get_text(strip=True)
                    if text and len(text) < 25 and not any(c.isdigit() for c in text):
                        place_data['category'] = text
                        break
            
            # Look for note in the container
            note_elem = container.find('textarea', {'aria-label': 'Note'})
            if note_elem:
                note_text = note_elem.get('value', '') or note_elem.text or ''
                if note_text.strip():
                    place_data['note'] = note_text.strip()
            
            # Also check notes dictionary
            if place_data['place'] and place_data['place'] in notes_dict:
                place_data['note'] = notes_dict[place_data['place']]
            
            # Only add if we got at least a place name
            if place_data['place']:
                places.append(place_data)
                
        except Exception as e:
            print(f"Error parsing container: {e}")
            continue
    
    return places


def scrape_google_maps_list(
    url: str,
    city: str = None,
    output_file: Optional[str] = None,
    headless: bool = True,
    scroll_pause: float = 2.0,
    max_scrolls: int = 100,
    return_format: str = 'dict'
) -> dict:
    """
    Main function to scrape a Google Maps saved list.
    
    Args:
        url: Google Maps list URL (must be public)
        city: City name to tag all places from this list
        output_file: Optional CSV file path to save results
        headless: Run browser in headless mode
        scroll_pause: Time between scrolls
        max_scrolls: Maximum scroll attempts
        return_format: 'dict' for JSON-compatible dict, 'dataframe' for pandas DataFrame
    
    Returns:
        Dictionary containing scraped data and metadata
    """
    start_time = timeit.default_timer()
    result = {
        'success': False,
        'message': '',
        'data': [],
        'count': 0,
        'execution_time': 0,
        'url': url,
        'city': city
    }
    
    driver = None
    
    try:
        print(f"Initializing browser...")
        driver = setup_driver(headless=headless)
        
        print(f"Loading URL: {url}")
        print(f"City tag: {city}")
        driver.get(url)
        
        # Wait for page to load
        time.sleep(3)
        
        # Try to wait for content to appear
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div.fontHeadlineSmall, div.qBF1Pd'))
            )
        except TimeoutException:
            print("Warning: Timeout waiting for place elements. Proceeding anyway...")
        
        print("Scrolling to load all listings...")
        scroll_to_load_all(driver, scroll_pause=scroll_pause, max_scrolls=max_scrolls)
        
        # Extract notes before parsing HTML (while page is still interactive)
        print("Extracting notes...")
        notes_dict = extract_notes_from_page(driver)
        print(f"Found {len(notes_dict)} notes")
        
        # Get page HTML
        print("Parsing page content...")
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Parse listings with city tag
        places = parse_listings(soup, notes_dict, city=city)
        
        print(f"Successfully extracted {len(places)} places")
        
        # Create DataFrame
        df = pd.DataFrame(places)
        
        # Reorder columns - city first for easy identification
        column_order = ['city', 'place', 'address', 'category', 'rating', 'note', 'lat', 'lng', 'url']
        df = df[[col for col in column_order if col in df.columns]]
        
        # Save to file if specified
        if output_file:
            if output_file.endswith('.json'):
                df.to_json(output_file, orient='records', indent=2)
            else:
                df.to_csv(output_file, index=False)
            print(f"Saved results to: {output_file}")
        
        execution_time = timeit.default_timer() - start_time
        
        result['success'] = True
        result['message'] = f'Successfully scraped {len(places)} places'
        result['count'] = len(places)
        result['execution_time'] = round(execution_time, 2)
        
        if return_format == 'dataframe':
            result['data'] = df
        else:
            result['data'] = df.to_dict('records')
        
    except Exception as e:
        result['message'] = f'Error: {str(e)}'
        print(f"Error during scraping: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if driver:
            driver.quit()
            print("Browser closed")
    
    return result


def main():
    """Command-line interface for the scraper."""
    parser = argparse.ArgumentParser(
        description='Scrape Google Maps saved lists',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python google_maps_list_scraper.py --url "https://www.google.com/maps/..." --city "Chicago" --output places.csv
  python google_maps_list_scraper.py --url "https://www.google.com/maps/..." --city "NYC" --output places.json --headless
        """
    )
    
    parser.add_argument(
        '--url', '-u',
        required=True,
        help='Google Maps list URL (must be public)'
    )
    parser.add_argument(
        '--city', '-c',
        required=False,
        default=None,
        help='City name to tag all places from this list'
    )
    parser.add_argument(
        '--output', '-o',
        default='google_maps_places.csv',
        help='Output file path (.csv or .json)'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        default=True,
        help='Run browser in headless mode (default: True)'
    )
    parser.add_argument(
        '--no-headless',
        action='store_true',
        help='Run browser with GUI (visible)'
    )
    parser.add_argument(
        '--scroll-pause',
        type=float,
        default=2.0,
        help='Pause between scrolls in seconds (default: 2.0)'
    )
    parser.add_argument(
        '--max-scrolls',
        type=int,
        default=100,
        help='Maximum number of scroll attempts (default: 100)'
    )
    parser.add_argument(
        '--json-output',
        action='store_true',
        help='Print JSON result to stdout (for n8n integration)'
    )
    
    args = parser.parse_args()
    
    headless = not args.no_headless
    
    result = scrape_google_maps_list(
        url=args.url,
        city=args.city,
        output_file=args.output,
        headless=headless,
        scroll_pause=args.scroll_pause,
        max_scrolls=args.max_scrolls
    )
    
    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        if result['success']:
            print(f"\n✓ {result['message']}")
            print(f"  City: {result['city']}")
            print(f"  Execution time: {result['execution_time']}s")
            print(f"  Output saved to: {args.output}")
        else:
            print(f"\n✗ {result['message']}")
    
    return 0 if result['success'] else 1


# For n8n Execute Command node - direct function call
def n8n_scrape(url: str, city: str = None, output_path: str = None) -> str:
    """
    Simplified function for n8n integration.
    Returns JSON string for easy parsing in n8n.
    
    Args:
        url: Google Maps list URL
        city: City name to tag all places
        output_path: Optional output file path
    
    Returns:
        JSON string with results
    """
    result = scrape_google_maps_list(
        url=url,
        city=city,
        output_file=output_path,
        headless=True,
        return_format='dict'
    )
    return json.dumps(result, indent=2)


if __name__ == '__main__':
    exit(main())
