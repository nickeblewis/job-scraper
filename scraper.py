import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import re

REED_SEARCH_URL = "https://www.reed.co.uk/jobs"
ADZUNA_SEARCH_URL = "https://www.adzuna.co.uk/jobs/search"

COMPANY_BLACKLIST = {
    "Robert Half",
}

REED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Adzuna requires Sec-Fetch headers or it returns 403/Too Many Requests
ADZUNA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


# ---------------------------------------------------------------------------
# Reed
# ---------------------------------------------------------------------------

def _fetch_reed(keywords, location="", distance=50, pages=1, wfh=False, job_type="perm"):
    types = ["perm", "contract"] if job_type == "both" else [job_type]
    jobs = []
    seen_urls = set()
    for jtype in types:
        for page in range(1, pages + 1):
            params = {
                "keywords": keywords,
                "location": location,
                "proximity": distance,
                "pageno": page,
                jtype: "true",
            }
            if wfh:
                params["wfh"] = "true"
            response = requests.get(REED_SEARCH_URL, params=params, headers=REED_HEADERS)
            response.raise_for_status()
            page_jobs = _parse_reed(response.text)
            if not page_jobs:
                break
            for job in page_jobs:
                if job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    jobs.append(job)
    return jobs


def _parse_reed(html):
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
        is_wfh = any(
            "Work from home" in li.get_text()
            for li in card.select("ul[data-qa='job-metadata'] li")
        )

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
            "work_from_home": is_wfh,
            "date_posted": date_posted,
            "source": "Reed",
            "url": url,
        })
    return jobs


# ---------------------------------------------------------------------------
# Adzuna
# ---------------------------------------------------------------------------

def _adzuna_location(location):
    """Adzuna rejects full UK postcodes (e.g. 'RG7 1SS'). Strip to the outward code ('RG7')."""
    if re.match(r'^[A-Z]{1,2}\d{1,2}[A-Z]?\s+\d[A-Z]{2}$', location.strip(), re.IGNORECASE):
        return location.strip().split()[0]
    return location


def _fetch_adzuna(keywords, location="", distance=50, pages=1, wfh=False, job_type="perm"):
    jobs = []
    seen_urls = set()
    types = ["perm", "contract"] if job_type == "both" else [job_type]
    adzuna_location = _adzuna_location(location)

    for jtype in types:
        for page in range(1, pages + 1):
            params = {
                "q": keywords,
                "w": adzuna_location,
                "r": distance,
                "sort": "date",
                "p": page,
            }
            if jtype == "perm":
                params["perm"] = 1
            elif jtype == "contract":
                params["contract"] = 1
            if wfh:
                params["q"] = f"{keywords} remote"

            response = requests.get(ADZUNA_SEARCH_URL, params=params, headers=ADZUNA_HEADERS)
            response.raise_for_status()
            page_jobs = _parse_adzuna(response.text)
            if not page_jobs:
                break
            for job in page_jobs:
                if job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    jobs.append(job)
    return jobs


def _parse_adzuna(html):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("article[data-aid]"):
        title_el = card.select_one("h2 a[data-js='jobLink']")
        company_el = card.select_one("div.ui-company")
        location_el = card.select_one("div.ui-location")
        salary_el = card.select_one("div.ui-salary")

        title = " ".join(title_el.get_text(" ", strip=True).split()) if title_el else ""
        company = company_el.get("data-company-name") or (company_el.get_text(strip=True) if company_el else "")
        location = location_el.get_text(strip=True) if location_el else ""

        # Salary: if it's a JOBSWORTH estimate rather than a real figure, discard it
        salary = ""
        if salary_el:
            raw_salary = salary_el.get_text(" ", strip=True)
            if "JOBSWORTH" not in raw_salary.upper():
                salary = re.sub(r'\s*\b(TOP MATCH|CLOSING SOON|NEW)\b.*', '', raw_salary, flags=re.IGNORECASE).strip()

        href = title_el.get("href", "") if title_el else ""
        url = "https://www.adzuna.co.uk" + href if href.startswith("/") else href

        snippet = card.get_text(" ", strip=True).lower()
        is_wfh = any(kw in snippet for kw in ("remote", "work from home", "wfh"))

        jobs.append({
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "job_type": "",   # not shown on Adzuna listing cards
            "work_from_home": is_wfh,
            "date_posted": "",  # not shown on Adzuna listing cards
            "source": "Adzuna",
            "url": url,
        })
    return jobs


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

def get_jobs(keywords, location="", distance=50, pages=1, wfh=False, job_type="perm",
             sources=("reed", "adzuna")):
    """
    sources: tuple of "reed" and/or "adzuna"
    job_type: "perm", "contract", or "both"
    wfh: True to include work-from-home roles only
    """
    all_jobs = []
    seen_urls = set()

    fetchers = {"reed": _fetch_reed, "adzuna": _fetch_adzuna}
    for source in sources:
        fetch = fetchers.get(source)
        if not fetch:
            print(f"Unknown source: {source!r}")
            continue
        for job in fetch(keywords, location, distance=distance, pages=pages,
                         wfh=wfh, job_type=job_type):
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                all_jobs.append(job)

    return all_jobs


def _parse_date(date_str):
    """Convert date strings from any source to a datetime for sorting."""
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
    sources_input = input("Sources — reed, adzuna, or both [both]: ").strip().lower()
    if sources_input == "reed":
        sources = ("reed",)
    elif sources_input == "adzuna":
        sources = ("adzuna",)
    else:
        sources = ("reed", "adzuna")

    jobs = get_jobs(keywords, location, distance=distance, pages=pages,
                    wfh=wfh, job_type=job_type, sources=sources)
    if jobs:
        save_jobs(sort_jobs_by_date(filter_blacklisted(jobs)))
    else:
        print("No jobs found.")
