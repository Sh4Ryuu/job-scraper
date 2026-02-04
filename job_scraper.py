import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import os
from datetime import datetime

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
# Format: "country1:domain1,country2:domain2"
DOMAINS = {}
for mapping in DOMAINS_STRING.split(","):
    if ":" in mapping:
        country, domain = mapping.split(":", 1)
        DOMAINS[country.strip().lower()] = domain.strip()

print(f"Configuration loaded: {len(LOCATIONS)} targets")


# ============ SLACK FUNCTIONS ============
def send_to_slack(all_jobs_by_location):
    """Send results to notification system"""

    total_jobs = sum(len(jobs) for jobs in all_jobs_by_location.values())

    if total_jobs == 0:
        message = {"text": "No matching results found.", "username": "Alert Bot"}
        requests.post(SLACK_WEBHOOK_URL, json=message)
        return

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{total_jobs} Results Found",
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

    # Add all results without grouping
    job_number = 1
    for location, jobs in all_jobs_by_location.items():
        for job in jobs:
            job_block = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{job_number}. {job['title']}*\n"
                    f"{job['company']}\n"
                    f"{job['location']}\n"
                    f"{job['salary']}",
                },
            }

            if job.get("link"):
                job_block["accessory"] = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View"},
                    "url": job["link"],
                }

            blocks.append(job_block)
            job_number += 1

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Total: {total_jobs} results*"},
        }
    )

    message = {"blocks": blocks, "username": "Alert Bot"}
    response = requests.post(SLACK_WEBHOOK_URL, json=message)

    if response.status_code == 200:
        print(f"Notification sent: {total_jobs} items")
    else:
        print(f"Notification failed")


# ============ CORE FUNCTIONS ============
def get_domain(location):
    """Get domain from configuration"""
    location_lower = location.lower()
    for key, domain in DOMAINS.items():
        if key in location_lower:
            return domain
    return "www.indeed.com"


def scrape_location(location):
    """Execute search"""
    print(f"Processing target {LOCATIONS.index(location) + 1}/{len(LOCATIONS)}...")

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=chrome_options
    )

    results = []

    try:
        domain = get_domain(location)
        driver.get(f"https://{domain}")
        time.sleep(2)

        try:
            search_input = driver.find_element(By.ID, "text-input-what")
            search_input.send_keys(JOB_TITLE)

            location_input = driver.find_element(By.ID, "text-input-where")
            location_input.clear()
            location_input.send_keys(location)
            location_input.submit()

            time.sleep(4)
        except:
            driver.quit()
            return results

        try:
            cards = driver.find_elements(By.CLASS_NAME, "job_seen_beacon")

            for card in cards[:MAX_JOBS_PER_LOCATION]:
                try:
                    title = card.find_element(By.CSS_SELECTOR, "h2.jobTitle span").text
                    company = card.find_element(
                        By.CSS_SELECTOR, "[data-testid='company-name']"
                    ).text
                    job_location = card.find_element(
                        By.CSS_SELECTOR, "[data-testid='text-location']"
                    ).text

                    try:
                        link_element = card.find_element(
                            By.CSS_SELECTOR, "h2.jobTitle a"
                        )
                        job_id = link_element.get_attribute("data-jk")
                        link = f"https://{domain}/viewjob?jk={job_id}"
                    except:
                        link = None

                    try:
                        salary = card.find_element(
                            By.CSS_SELECTOR, "[data-testid='attribute_snippet_testid']"
                        ).text
                    except:
                        salary = "Not listed"

                    results.append(
                        {
                            "title": title,
                            "company": company,
                            "location": job_location,
                            "salary": salary,
                            "link": link,
                        }
                    )

                except:
                    continue

            print(f"  Found {len(results)} items")

        except:
            print("  No items found")

    except:
        print("  Error occurred")

    finally:
        driver.quit()

    return results


# ============ MAIN ============
def main():
    print("Starting search process...")

    all_results = {}

    for location in LOCATIONS:
        results = scrape_location(location)
        all_results[location] = results
        time.sleep(3)

    total = sum(len(r) for r in all_results.values())
    print(f"\nTotal items found: {total}")

    send_to_slack(all_results)

    print("Process completed")


if __name__ == "__main__":
    main()
