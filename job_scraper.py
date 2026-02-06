import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import os
from datetime import datetime
import base64

# ============ ALL CONFIG FROM GITHUB SECRETS ============
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
JOB_TITLE = os.environ.get("JOB_TITLE")
LOCATIONS_STRING = os.environ.get("JOB_LOCATIONS")
DOMAINS_STRING = os.environ.get("DOMAIN_MAPPINGS")
MAX_JOBS_PER_LOCATION = int(os.environ.get("MAX_JOBS_PER_LOCATION", "10"))

# Validate
if not all([SLACK_WEBHOOK_URL, JOB_TITLE, LOCATIONS_STRING, DOMAINS_STRING]):
    raise ValueError("Required configuration missing")

# Parse locations
LOCATIONS = [loc.strip() for loc in LOCATIONS_STRING.split(",")]

# Parse domain mappings from secret
DOMAINS = {}
for mapping in DOMAINS_STRING.split(","):
    if ":" in mapping:
        country, domain = mapping.split(":", 1)
        DOMAINS[country.strip().lower()] = domain.strip()

print(f"Configuration loaded: {len(LOCATIONS)} targets")
print(f"Searching for: '{JOB_TITLE}'")


# ============ SLACK FUNCTIONS ============
def send_debug_screenshot(screenshot_b64, location, error_msg):
    """Send debug screenshot to Slack when scraping fails"""
    try:
        # Create a simple message with the error
        message = {
            "text": f"🔍 Debug Info for {location}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Debug Info - {location}*\n{error_msg}\n\n_Screenshot shows what the bot sees_"
                    }
                }
            ],
            "username": "Debug Bot"
        }
        requests.post(SLACK_WEBHOOK_URL, json=message)
        print(f"  Debug info sent to Slack")
    except Exception as e:
        print(f"  Failed to send debug screenshot: {e}")


def send_to_slack(all_jobs_by_location, debug_info=None):
    """Send results to notification system"""

    total_jobs = sum(len(jobs) for jobs in all_jobs_by_location.values())

    if total_jobs == 0:
        debug_text = ""
        if debug_info:
            debug_text = f"\n\n*Debug Information:*\n{debug_info}"
        
        message = {
            "text": f"No matching results found.{debug_text}", 
            "username": "Job Alert Bot"
        }
        requests.post(SLACK_WEBHOOK_URL, json=message)
        return

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🎯 {total_jobs} Jobs Found",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"_Updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_",
            },
        },
        {"type": "divider"},
    ]

    # Add all results
    job_number = 1
    for location, jobs in all_jobs_by_location.items():
        if jobs:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📍 {location}* - {len(jobs)} jobs"
                }
            })
            
        for job in jobs:
            job_block = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{job_number}. {job['title']}*\n"
                    f"🏢 {job['company']}\n"
                    f"📍 {job['location']}\n"
                    f"💰 {job['salary']}",
                },
            }

            if job.get("link"):
                job_block["accessory"] = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Apply", "emoji": True},
                    "url": job["link"],
                    "action_id": f"button_{job_number}"
                }

            blocks.append(job_block)
            job_number += 1

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Total: {total_jobs} jobs across {len([j for j in all_jobs_by_location.values() if j])} locations*"},
        }
    )

    message = {"blocks": blocks, "username": "Job Alert Bot"}
    response = requests.post(SLACK_WEBHOOK_URL, json=message)

    if response.status_code == 200:
        print(f"✅ Notification sent: {total_jobs} jobs")
    else:
        print(f"❌ Notification failed: {response.status_code}")


# ============ CORE FUNCTIONS ============
def get_domain(location):
    """Get domain from configuration"""
    location_lower = location.lower()
    for key, domain in DOMAINS.items():
        if key in location_lower:
            return domain
    return "www.indeed.com"


def scrape_location(location):
    """Execute search with improved error handling"""
    print(f"\n{'='*50}")
    print(f"Processing: {location}")
    print(f"{'='*50}")

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")  # Updated headless mode
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), 
        options=chrome_options
    )
    
    # Remove webdriver property
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    results = []
    debug_messages = []

    try:
        domain = get_domain(location)
        url = f"https://{domain}"
        print(f"  🌐 Domain: {domain}")
        print(f"  🔍 Searching for: '{JOB_TITLE}'")
        print(f"  📍 Location: '{location}'")
        
        driver.get(url)
        time.sleep(3)  # Increased wait time

        try:
            # Try to find the search inputs with wait
            wait = WebDriverWait(driver, 10)
            
            # Try multiple possible selectors for the "what" field
            what_selectors = [
                "text-input-what",
                "what",
                "job-search-bar-keywords"
            ]
            
            search_input = None
            for selector in what_selectors:
                try:
                    search_input = wait.until(
                        EC.presence_of_element_located((By.ID, selector))
                    )
                    print(f"  ✅ Found search input with ID: {selector}")
                    break
                except:
                    continue
            
            if not search_input:
                debug_messages.append("❌ Could not find job title search input")
                raise Exception("Search input not found")
            
            search_input.clear()
            search_input.send_keys(JOB_TITLE)
            time.sleep(1)

            # Try multiple possible selectors for the "where" field
            where_selectors = [
                "text-input-where",
                "where",
                "job-search-bar-location"
            ]
            
            location_input = None
            for selector in where_selectors:
                try:
                    location_input = driver.find_element(By.ID, selector)
                    print(f"  ✅ Found location input with ID: {selector}")
                    break
                except:
                    continue
                    
            if not location_input:
                debug_messages.append("❌ Could not find location search input")
                raise Exception("Location input not found")
                
            location_input.clear()
            location_input.send_keys(location)
            time.sleep(1)
            location_input.send_keys(Keys.RETURN)
            
            print(f"  ⏳ Waiting for results to load...")
            time.sleep(6)  # Increased wait for results

            # Take screenshot for debugging
            screenshot = driver.get_screenshot_as_base64()
            current_url = driver.current_url
            print(f"  📸 Current URL: {current_url}")

        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            debug_messages.append(error_msg)
            print(f"  ❌ {error_msg}")
            screenshot = driver.get_screenshot_as_base64()
            send_debug_screenshot(screenshot, location, "\n".join(debug_messages))
            driver.quit()
            return results

        try:
            # Try multiple selectors for job cards
            job_card_selectors = [
                "job_seen_beacon",
                "jobsearch-ResultsList",
                "slider_container",
                "job_card",
                "cardOutline"
            ]
            
            cards = []
            selector_used = None
            
            for selector in job_card_selectors:
                try:
                    cards = driver.find_elements(By.CLASS_NAME, selector)
                    if cards:
                        selector_used = selector
                        print(f"  ✅ Found {len(cards)} elements with class: {selector}")
                        break
                except:
                    continue
            
            if not cards:
                # Try CSS selector as fallback
                try:
                    cards = driver.find_elements(By.CSS_SELECTOR, "[data-jk]")
                    if cards:
                        selector_used = "data-jk attribute"
                        print(f"  ✅ Found {len(cards)} job cards using data-jk attribute")
                except:
                    pass
            
            if not cards:
                error_msg = "No job cards found on page"
                debug_messages.append(f"❌ {error_msg}")
                debug_messages.append(f"Page title: {driver.title}")
                debug_messages.append(f"URL: {driver.current_url}")
                print(f"  ❌ {error_msg}")
                screenshot = driver.get_screenshot_as_base64()
                send_debug_screenshot(screenshot, location, "\n".join(debug_messages))
                driver.quit()
                return results

            print(f"  📋 Processing up to {MAX_JOBS_PER_LOCATION} jobs...")
            
            for idx, card in enumerate(cards[:MAX_JOBS_PER_LOCATION], 1):
                try:
                    # Try multiple selectors for job title
                    title = None
                    title_selectors = [
                        "h2.jobTitle span",
                        "h2.jobTitle",
                        ".jobTitle",
                        "[data-testid='job-title']",
                        "a[data-jk] span"
                    ]
                    
                    for selector in title_selectors:
                        try:
                            title_elem = card.find_element(By.CSS_SELECTOR, selector)
                            title = title_elem.text
                            if title:
                                break
                        except:
                            continue
                    
                    if not title:
                        continue

                    # Try multiple selectors for company
                    company = "Not listed"
                    company_selectors = [
                        "[data-testid='company-name']",
                        ".companyName",
                        "span.companyName"
                    ]
                    
                    for selector in company_selectors:
                        try:
                            company = card.find_element(By.CSS_SELECTOR, selector).text
                            if company:
                                break
                        except:
                            continue

                    # Try multiple selectors for location
                    job_location = location
                    location_selectors = [
                        "[data-testid='text-location']",
                        ".companyLocation",
                        "div.companyLocation"
                    ]
                    
                    for selector in location_selectors:
                        try:
                            job_location = card.find_element(By.CSS_SELECTOR, selector).text
                            if job_location:
                                break
                        except:
                            continue

                    # Get job link
                    link = None
                    try:
                        link_element = card.find_element(By.CSS_SELECTOR, "h2.jobTitle a")
                        job_id = link_element.get_attribute("data-jk")
                        if job_id:
                            link = f"https://{domain}/viewjob?jk={job_id}"
                    except:
                        try:
                            job_id = card.get_attribute("data-jk")
                            if job_id:
                                link = f"https://{domain}/viewjob?jk={job_id}"
                        except:
                            pass

                    # Get salary
                    salary = "Not listed"
                    salary_selectors = [
                        "[data-testid='attribute_snippet_testid']",
                        ".salary-snippet",
                        ".salaryText"
                    ]
                    
                    for selector in salary_selectors:
                        try:
                            salary = card.find_element(By.CSS_SELECTOR, selector).text
                            if salary:
                                break
                        except:
                            continue

                    results.append(
                        {
                            "title": title,
                            "company": company,
                            "location": job_location,
                            "salary": salary,
                            "link": link,
                        }
                    )
                    
                    print(f"    ✓ Job {idx}: {title[:50]}...")

                except Exception as e:
                    print(f"    ✗ Job {idx}: Failed to parse ({str(e)})")
                    continue

            print(f"  ✅ Successfully scraped {len(results)} jobs")

        except Exception as e:
            error_msg = f"Failed to parse results: {str(e)}"
            debug_messages.append(f"❌ {error_msg}")
            print(f"  ❌ {error_msg}")
            screenshot = driver.get_screenshot_as_base64()
            send_debug_screenshot(screenshot, location, "\n".join(debug_messages))

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        debug_messages.append(f"❌ {error_msg}")
        print(f"  ❌ {error_msg}")
        try:
            screenshot = driver.get_screenshot_as_base64()
            send_debug_screenshot(screenshot, location, "\n".join(debug_messages))
        except:
            pass

    finally:
        driver.quit()

    return results


# ============ MAIN ============
def main():
    print("\n" + "="*60)
    print("🚀 STARTING JOB SEARCH PROCESS")
    print("="*60)

    all_results = {}
    total_start = time.time()

    for idx, location in enumerate(LOCATIONS, 1):
        print(f"\n[{idx}/{len(LOCATIONS)}] Target: {location}")
        results = scrape_location(location)
        all_results[location] = results
        
        if idx < len(LOCATIONS):
            wait_time = 5
            print(f"  ⏳ Waiting {wait_time}s before next location...")
            time.sleep(wait_time)

    total_time = time.time() - total_start
    total = sum(len(r) for r in all_results.values())
    
    print("\n" + "="*60)
    print(f"📊 FINAL RESULTS")
    print("="*60)
    print(f"Total jobs found: {total}")
    print(f"Total time: {total_time:.1f}s")
    print(f"Locations searched: {len(LOCATIONS)}")
    
    for location, jobs in all_results.items():
        print(f"  • {location}: {len(jobs)} jobs")

    debug_info = None
    if total == 0:
        debug_info = "Scraped all locations but found no jobs. Check debug screenshots above."
    
    send_to_slack(all_results, debug_info)

    print("\n✅ Process completed")


if __name__ == "__main__":
    main()
