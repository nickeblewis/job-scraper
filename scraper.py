import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import re

REED_SEARCH_URL = "https://www.reed.co.uk/jobs"

COMPANY_BLACKLIST = {
    "Robert Half",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def get_jobs(keywords, location="", distance=50, pages=1, wfh=False, job_type="perm"):
    """
    job_type: "perm", "contract", or "both"
    wfh: True to filter for work-from-home roles only
    """
    types = ["perm", "contract"] if job_type == "both" else [job_type]
    all_jobs = []
    seen_urls = set()
    for jtype in types:
        for page in range(1, pages + 1):
            params = {
                "keywords": keywords,
                "location": location,
                "proximity": distance,
                "pageno": page,
            }
            params[jtype] = "true"
            if wfh:
                params["wfh"] = "true"
            response = requests.get(REED_SEARCH_URL, params=params, headers=HEADERS)
            response.raise_for_status()
            page_jobs = parse_jobs(response.text)
            if not page_jobs:
                break
            for job in page_jobs:
                if job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    all_jobs.append(job)
    return all_jobs


def parse_jobs(html):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("article[data-qa='job-card']"):
        title_el = card.select_one("a[data-qa='job-card-title']")
        posted_by_el = card.select_one("div[data-qa='job-posted-by']")
        company_el = posted_by_el.select_one("a") if posted_by_el else None
        location_el = card.select_one("li[data-qa='job-metadata-location']")
        salary_el = card.select_one("li[data-qa='job-metadata-salary']")
        job_type_svg = card.select_one("li svg[aria-label='Clock']")
        job_type_el = job_type_svg.parent if job_type_svg else None
        wfh = any(
            "Work from home" in li.get_text()
            for li in card.select("ul[data-qa='job-metadata'] li")
        )

        # Date is the text in the posted-by div before " by Company"
        date_posted = ""
        if posted_by_el:
            raw = posted_by_el.get_text(" ", strip=True)
            date_posted = raw.split(" by ")[0].strip()

        href = title_el.get("href", "") if title_el else ""
        url = "https://www.reed.co.uk" + href if href.startswith("/") else href

        jobs.append({
            "title": title_el.get_text(strip=True) if title_el else "",
            "company": company_el.get_text(strip=True) if company_el else "",
            "location": location_el.get_text(strip=True) if location_el else "",
            "salary": salary_el.get_text(strip=True) if salary_el else "",
            "job_type": job_type_el.get_text(strip=True) if job_type_el else "",
            "work_from_home": wfh,
            "date_posted": date_posted,
            "url": url,
        })
    return jobs


def _parse_date(date_str):
    """Convert Reed date strings to a datetime for sorting purposes."""
    now = datetime.now()
    s = date_str.strip().lower()
    if not s:
        return datetime.min
    m = re.match(r"(\d+)\s*hr", s)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.match(r"(\d+)\s*day", s)
    if m:
        return now - timedelta(days=int(m.group(1)))
    if s == "yesterday":
        return now - timedelta(days=1)
    if s in ("today", "just now"):
        return now
    try:
        return datetime.strptime(date_str.strip(), "%d %B %Y")
    except ValueError:
        pass
    try:
        dt = datetime.strptime(f"{date_str.strip()} {now.year}", "%d %B %Y")
        if dt > now:
            dt = dt.replace(year=now.year - 1)
        return dt
    except ValueError:
        pass
    return datetime.min


def filter_blacklisted(jobs):
    return [j for j in jobs if j.get("company", "") not in COMPANY_BLACKLIST]


def sort_jobs_by_date(jobs):
    return sorted(
        jobs,
        key=lambda j: (_parse_date(j.get("date_posted", "")), j.get("job_type", "")),
        reverse=True,
    )


def save_jobs(jobs, filename=None):
    if filename is None:
        filename = f"jobs_{datetime.now().date()}.csv"
    df = pd.DataFrame(jobs)
    df.to_csv(filename, index=False)
    print(f"Saved {len(jobs)} jobs to {filename}")


if __name__ == "__main__":
    keywords = input("Job title or keywords: ")
    location = input("Location [RG7 1SS]: ").strip() or "RG7 1SS"
    distance_input = input("Search radius in miles [50]: ").strip()
    distance = int(distance_input) if distance_input.isdigit() else 50
    pages_input = input("Number of pages to scrape [1]: ").strip()
    pages = int(pages_input) if pages_input.isdigit() else 1
    job_type_input = input("Job type — perm, contract, or both [perm]: ").strip().lower()
    job_type = job_type_input if job_type_input in ("perm", "contract", "both") else "perm"
    wfh_input = input("Work from home only? y/n [n]: ").strip().lower()
    wfh = wfh_input == "y"

    jobs = get_jobs(keywords, location, distance=distance, pages=pages, wfh=wfh, job_type=job_type)
    if jobs:
        save_jobs(sort_jobs_by_date(filter_blacklisted(jobs)))
    else:
        print("No jobs found. The page structure may have changed — check the CSS selectors in parse_jobs().")
