#!/usr/bin/env python3
"""
Google Maps Saved List Scraper (v5 - January 2025)
Scrapes places from a public Google Maps saved list including notes.

Based on live inspection of Google Maps HTML structure:
- Each place is a <button> element inside <main>
- Place name is in first child <div> (generic)
- Rating is in <img aria-label="X.X stars N Reviews">
- Category follows rating
- Notes appear as expanded text below selected items OR in textarea elements

Requirements:
    pip install selenium webdriver-manager pandas

Usage:
    python google_maps_list_scraper.py --url "YOUR_URL" --city "Barcelona" --output "output.json"
"""

import argparse
import json
import re
import time
import timeit
from typing import Optional, List, Dict
import os

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, 
    NoSuchElementException, 
    StaleElementReferenceException,
    ElementClickInterceptedException
)
from webdriver_manager.chrome import ChromeDriverManager


def setup_driver(headless: bool = True) -> webdriver.Chrome:
    """Initialize Chrome WebDriver."""
    chrome_options = Options()
    
    if headless:
        chrome_options.add_argument("--headless=new")
    
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_argument("--lang=en-US")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.implicitly_wait(5)
    
    return driver


def wait_for_list_load(driver: webdriver.Chrome, timeout: int = 20) -> bool:
    """Wait for the Google Maps list to load."""
    print("Waiting for list to load...")
    
    try:
        # Wait for main content area
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'main'))
        )
        time.sleep(3)
        
        # Wait for at least one place button to appear
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'main button'))
        )
        print("List loaded successfully")
        return True
        
    except TimeoutException:
        print("Warning: Timeout waiting for list to load")
        return False


def get_place_buttons(driver: webdriver.Chrome) -> List:
    """Get all place buttons from the list, filtering out utility buttons."""
    
    all_buttons = driver.find_elements(By.CSS_SELECTOR, 'main button')
    place_buttons = []
    
    # Words that indicate utility buttons (not places)
    skip_words = [
        'delete', 'share', 'add a place', 'joined', 'edit', 'more options',
        'note', 'close', 'back', 'search', 'menu', 'collapse', 'add note'
    ]
    
    for btn in all_buttons:
        try:
            # Get aria-label and text
            aria = (btn.get_attribute('aria-label') or '').lower()
            text = btn.text.strip().lower()
            
            # Skip utility buttons
            if any(skip in aria for skip in skip_words):
                continue
            if any(skip in text for skip in skip_words):
                continue
            
            # Skip empty buttons
            if not btn.text.strip():
                continue
            
            # Skip single-character buttons
            if len(btn.text.strip()) <= 1:
                continue
            
            # This looks like a place button
            place_buttons.append(btn)
            
        except StaleElementReferenceException:
            continue
        except Exception:
            continue
    
    return place_buttons


def scroll_and_collect_places(driver: webdriver.Chrome, scroll_pause: float = 2.0, max_scrolls: int = 100) -> int:
    """Scroll the list to load all places."""
    print("Scrolling to load all places...")
    
    last_count = 0
    no_change_count = 0
    scroll_count = 0
    
    # Find scrollable element
    try:
        main_elem = driver.find_element(By.CSS_SELECTOR, 'main')
    except:
        main_elem = driver.find_element(By.TAG_NAME, 'body')
    
    while scroll_count < max_scrolls:
        # Count current places
        place_buttons = get_place_buttons(driver)
        current_count = len(place_buttons)
        
        print(f"Scroll {scroll_count + 1}: Found {current_count} places")
        
        # Check if we've reached the end
        if current_count == last_count:
            no_change_count += 1
            if no_change_count >= 3:
                print(f"Reached end of list")
                break
        else:
            no_change_count = 0
        
        last_count = current_count
        
        # Scroll down using multiple methods
        try:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", main_elem)
        except:
            pass
        
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        except:
            pass
        
        try:
            ActionChains(driver).send_keys(Keys.END).perform()
        except:
            pass
        
        time.sleep(scroll_pause)
        scroll_count += 1
    
    final_count = len(get_place_buttons(driver))
    print(f"Scrolling complete. Found {final_count} places.")
    return final_count


def click_place_and_extract(driver: webdriver.Chrome, button, city: str, index: int) -> Optional[Dict]:
    """
    Click on a place button to select it and extract all data including notes.
    """
    place_data = {
        'city': city,
        'place': None,
        'address': None,
        'category': None,
        'rating': None,
        'review_count': None,
        'price_range': None,
        'note': None,
        'website': None,
        'phone': None,
        'lat': None,
        'lng': None,
        'url': None
    }
    
    try:
        # First, extract basic info from the button text
        full_text = button.text.strip()
        if not full_text:
            return None
        
        lines = full_text.split('\n')
        
        # First line is the place name
        if lines:
            place_name = lines[0].strip()
            if place_name.lower() in ['delete', 'share', 'add a place', 'joined', 'note', 'add note']:
                return None
            place_data['place'] = place_name
        
        # Extract rating from img aria-label
        try:
            rating_img = button.find_element(By.CSS_SELECTOR, 'img[aria-label*="star"]')
            aria = rating_img.get_attribute('aria-label') or ''
            match = re.match(r'(\d+\.?\d*)\s*stars?\s*([0-9,]+)\s*Reviews?', aria, re.IGNORECASE)
            if match:
                place_data['rating'] = match.group(1)
                place_data['review_count'] = match.group(2).replace(',', '')
        except NoSuchElementException:
            pass
        
        # Parse remaining lines
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            
            # Skip rating lines (already extracted)
            if re.match(r'^\d+\.?\d*$', line):
                continue
            if re.match(r'^\([0-9,]+\)$', line):
                continue
            
            # Price range
            if re.match(r'^[€$£¥]', line) or 'priced' in line.lower():
                place_data['price_range'] = line
                continue
            
            # Address with "Nearby Address:" prefix
            if 'nearby address:' in line.lower():
                place_data['address'] = line.split(':', 1)[1].strip()
                continue
            
            # Short text without numbers = category
            if len(line) < 50 and not any(c.isdigit() for c in line):
                if line.lower() not in ['temporarily closed', 'permanently closed']:
                    if not place_data['category']:
                        place_data['category'] = line
                continue
            
            # Longer text with numbers = address
            if any(c.isdigit() for c in line) and len(line) > 5:
                if not place_data['address']:
                    place_data['address'] = line
        
        # Now click the button to select it and reveal the note
        try:
            button.click()
            time.sleep(0.5)
        except ElementClickInterceptedException:
            # Try scrolling the button into view
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            time.sleep(0.3)
            button.click()
            time.sleep(0.5)
        
        # After clicking, look for the note in the expanded area
        # Notes appear in textarea elements or as plain text below the place
        try:
            # Method 1: Find textarea with aria-label="Note" near this button
            parent = button.find_element(By.XPATH, '..')
            note_areas = parent.find_elements(By.CSS_SELECTOR, 'textarea[aria-label="Note"]')
            for note_area in note_areas:
                note_text = note_area.get_attribute('value') or note_area.text
                if note_text and note_text.strip():
                    place_data['note'] = note_text.strip()
                    break
        except:
            pass
        
        if not place_data['note']:
            try:
                # Method 2: Look for note text that appears after clicking
                # Notes often contain URLs or are multi-line text below the place info
                grandparent = button.find_element(By.XPATH, '../..')
                all_text = grandparent.text
                
                # Look for text that's not part of the button
                button_text = button.text
                remaining_text = all_text.replace(button_text, '').strip()
                
                # If there's remaining text and it's not a utility word
                if remaining_text:
                    skip_texts = ['delete', 'note', 'add note', '+']
                    lines = remaining_text.split('\n')
                    note_lines = []
                    for line in lines:
                        line = line.strip()
                        if line and line.lower() not in skip_texts and len(line) > 2:
                            # Check if it looks like a note (contains URL or is descriptive text)
                            if 'http' in line.lower() or 'www.' in line.lower():
                                note_lines.append(line)
                            elif len(line) > 10 and not re.match(r'^[\d\.\(\)]+$', line):
                                note_lines.append(line)
                    
                    if note_lines:
                        place_data['note'] = '\n'.join(note_lines)
            except:
                pass
        
        # Get the URL from the current page if it changed
        current_url = driver.current_url
        if '/place/' in current_url:
            place_data['url'] = current_url
            # Extract lat/lng from URL
            lat_lng_match = re.search(r'@(-?\d+\.?\d*),(-?\d+\.?\d*)', current_url)
            if lat_lng_match:
                place_data['lat'] = lat_lng_match.group(1)
                place_data['lng'] = lat_lng_match.group(2)
        
        return place_data
        
    except StaleElementReferenceException:
        print(f"  Stale element at index {index}, skipping")
        return None
    except Exception as e:
        print(f"  Error extracting place {index}: {e}")
        return None


def extract_all_places(driver: webdriver.Chrome, city: str) -> List[Dict]:
    """Extract all places from the list by clicking each one."""
    places = []
    seen_names = set()
    
    print("\nExtracting place details...")
    
    # Get all place buttons
    place_buttons = get_place_buttons(driver)
    total = len(place_buttons)
    print(f"Found {total} places to process")
    
    for i, button in enumerate(place_buttons):
        try:
            # Re-find buttons periodically as DOM may change
            if i > 0 and i % 10 == 0:
                place_buttons = get_place_buttons(driver)
                if i < len(place_buttons):
                    button = place_buttons[i]
                else:
                    break
            
            # Extract data
            place_data = click_place_and_extract(driver, button, city, i)
            
            if place_data and place_data['place']:
                # Skip duplicates
                if place_data['place'] in seen_names:
                    continue
                
                seen_names.add(place_data['place'])
                places.append(place_data)
                
                note_indicator = " (has note)" if place_data.get('note') else ""
                print(f"  [{i+1}/{total}] {place_data['place']}{note_indicator}")
            
        except Exception as e:
            print(f"  [{i+1}/{total}] Error: {e}")
            continue
    
    print(f"\nExtracted {len(places)} places total")
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
    """Main function to scrape a Google Maps saved list."""
    
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
        print("=" * 60)
        print("Google Maps List Scraper v5")
        print("=" * 60)
        print(f"URL: {url}")
        print(f"City: {city}")
        print("=" * 60)
        
        print("\nInitializing browser...")
        driver = setup_driver(headless=headless)
        
        print(f"Loading URL...")
        driver.get(url)
        
        # Wait for page
        time.sleep(5)
        if not wait_for_list_load(driver, timeout=20):
            raise Exception("Failed to load list page")
        
        # Scroll to load all places
        scroll_and_collect_places(driver, scroll_pause=scroll_pause, max_scrolls=max_scrolls)
        
        # Wait after scrolling
        time.sleep(2)
        
        # Extract all places
        places = extract_all_places(driver, city=city)
        
        # Create DataFrame
        df = pd.DataFrame(places)
        
        # Reorder columns
        column_order = ['city', 'place', 'address', 'category', 'rating', 'review_count', 
                       'price_range', 'note', 'phone', 'website', 'lat', 'lng', 'url']
        df = df[[col for col in column_order if col in df.columns]]
        
        # Save to file
        if output_file:
            os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
            
            if output_file.endswith('.json'):
                df.to_json(output_file, orient='records', indent=2)
            else:
                df.to_csv(output_file, index=False)
            print(f"\nSaved results to: {output_file}")
        
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
        print(f"\nError during scraping: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if driver:
            driver.quit()
            print("\nBrowser closed")
    
    return result


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(description='Scrape Google Maps saved lists')
    
    parser.add_argument('--url', '-u', required=True, help='Google Maps list URL')
    parser.add_argument('--city', '-c', default=None, help='City name to tag places')
    parser.add_argument('--output', '-o', default='google_maps_places.json', help='Output file path')
    parser.add_argument('--headless', action='store_true', default=True)
    parser.add_argument('--no-headless', action='store_true', help='Show browser window')
    parser.add_argument('--scroll-pause', type=float, default=2.0)
    parser.add_argument('--max-scrolls', type=int, default=100)
    parser.add_argument('--json-output', action='store_true', help='Print JSON to stdout')
    
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
        output = {
            'success': result['success'],
            'message': result['message'],
            'count': result['count'],
            'execution_time': result['execution_time'],
            'city': result['city'],
            'data': result['data']
        }
        print(json.dumps(output))
    else:
        print("\n" + "=" * 60)
        if result['success']:
            print(f"✓ {result['message']}")
            print(f"  City: {result['city']}")
            print(f"  Execution time: {result['execution_time']}s")
        else:
            print(f"✗ {result['message']}")
        print("=" * 60)
    
    return 0 if result['success'] else 1


if __name__ == '__main__':
    exit(main())
