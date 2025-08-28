import os
import re
import time
import requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from datetime import datetime

# -----------------------
# Config
# -----------------------
SKILLS = ["python", "sql", "machine learning", "pandas", "numpy", "visual studio"]
FRESHER_KEYS = ["fresher", "0 year", "0-1 year", "0 – 1 year", "entry level", "entry-level", "graduate", "campus"]
CITIES_PRIORITY = ["hyderabad", "chennai", "bangalore", "bengaluru", "india"]
HEADERS = {"User-Agent": "Mozilla/5.0"}

def looks_fresher(text: str) -> bool:
    t = text.lower()
    if any(k in t for k in FRESHER_KEYS):
        # exclude > 1 yr roles explicitly
        if re.search(r"\b([2-9]\+?\s*years?|[2-9]\s*yrs)\b", t):
            return False
        return True
    # Allow "0-1 years" style
    return bool(re.search(r"\b0\s*-\s*1\s*(years?|yrs?)\b", t))

def has_required_skills(text: str) -> bool:
    t = text.lower()
    return all(k in t for k in ["python", "sql"]) and any(k in t for k in ["machine learning", "pandas", "numpy", "visual studio"])

def prefer_hyd_offline(title, company, location, summary):
    t = " ".join([title, company, location or "", summary or ""]).lower()
    hyd = "hyderabad" in t
    # rough onsite detection
    onsite = any(k in t for k in ["onsite", "on-site", "work from office", "wfo", "office"])
    return (1 if hyd else 0) + (1 if onsite else 0)

def clean(text):
    return re.sub(r"\s+", " ", (text or "")).strip()

# -----------------------
# Fetchers (best-effort, tolerant of layout changes)
# -----------------------
def fetch_indeed():
    url = "https://in.indeed.com/jobs?q=Python+SQL+%22Machine+Learning%22+Pandas+NumPy+%22Visual+Studio%22+fresher&l=India&fromage=3"
    jobs = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, "lxml")
        cards = soup.select("a.tapItem") or soup.select(".job_seen_beacon")
        for c in cards:
            title = clean(c.select_one("h2.jobTitle, span[title]") and c.select_one("h2.jobTitle, span[title]").get_text())
            company = clean(c.select_one(".companyName") and c.select_one(".companyName").get_text())
            location = clean(c.select_one(".companyLocation") and c.select_one(".companyLocation").get_text())
            link = "https://in.indeed.com" + (c.get("href") or c.select_one("a") and c.select_one("a").get("href") or "")
            snippet = clean(c.select_one(".job-snippet") and c.select_one(".job-snippet").get_text(" "))
            text = " ".join([title, company, location, snippet])
            if looks_fresher(text) and has_required_skills(text):
                jobs.append({
                    "source": "Indeed",
                    "title": title, "company": company, "location": location, "link": link, "snippet": snippet
                })
    except Exception:
        pass
    return jobs

def fetch_naukri():
    # Broad fresher query; Naukri pages are dynamic but initial HTML often includes tuples
    url = "https://www.naukri.com/python-sql-machine-learning-pandas-numpy-visual-studio-0-years-jobs"
    jobs = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, "lxml")
        cards = soup.select(".srp-jobtuple, .jobTuple")
        for c in cards:
            a = c.select_one("a.title, a[href]")
            title = clean(a.get_text() if a else "")
            link = a["href"] if a and a.has_attr("href") else ""
            company = clean((c.select_one(".subTitle") or c.select_one(".companyInfo .comp-name") or c.select_one(".comp-name")).get_text() if c else "")
            location = clean((c.select_one(".loc") or c.select_one(".job-location")).get_text() if c else "")
            snippet = clean((c.select_one(".job-description") or c.select_one(".job-desc")).get_text(" ") if c else "")
            text = " ".join([title, company, location, snippet])
            if looks_fresher(text) and has_required_skills(text):
                jobs.append({
                    "source": "Naukri",
                    "title": title, "company": company, "location": location, "link": link, "snippet": snippet
                })
    except Exception:
        pass
    return jobs

def fetch_foundit():
    url = "https://www.foundit.in/srp/results?query=Python%20SQL%20Machine%20Learning%20Pandas%20NumPy%20Visual%20Studio&experience=0"
    jobs = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, "lxml")
        cards = soup.select("[data-job-id], .srpResultCard")
        for c in cards:
            a = c.select_one("a[href]")
            title = clean(a.get_text() if a else "")
            link = a["href"] if a and a.has_attr("href") else ""
            company = clean((c.select_one(".company-name") or c.select_one(".company")).get_text() if c else "")
            location = clean((c.select_one(".location") or c.select_one(".job-location")).get_text() if c else "India")
            snippet = clean((c.select_one(".job-descrip") or c.select_one(".job-desc")).get_text(" ") if c else "")
            text = " ".join([title, company, location, snippet])
            if looks_fresher(text) and has_required_skills(text):
                jobs.append({
                    "source": "Foundit",
                    "title": title, "company": company, "location": location, "link": link, "snippet": snippet
                })
    except Exception:
        pass
    return jobs

def collect_all():
    all_jobs = []
    for fn in (fetch_indeed, fetch_naukri, fetch_foundit):
        try:
            all_jobs.extend(fn())
            time.sleep(1)  # be polite
        except Exception:
            continue

    # Deduplicate by (title, company, link)
    seen = set()
    unique = []
    for j in all_jobs:
        key = (j["title"].lower(), j["company"].lower(), j["link"])
        if key in seen: 
            continue
        seen.add(key)
        unique.append(j)

    # Rank: prefer Hyderabad + onsite first, then Chennai/Bangalore, then India-wide
    unique.sort(key=lambda j: (
        -prefer_hyd_offline(j["title"], j["company"], j["location"], j["snippet"]),
        CITIES_PRIORITY.index(j["location"].lower()) if j["location"] and j["location"].lower() in CITIES_PRIORITY else 99,
        j["source"]
    ))
    return unique[:60]  # cap to avoid overly long emails

def render_html(jobs):
    if not jobs:
        return "<p>No matching fresher jobs found today.</p>"

    rows = []
    for j in jobs:
        rows.append(f"""
        <tr>
          <td>{j['source']}</td>
          <td><a href="{j['link']}" target="_blank">{j['title']}</a></td>
          <td>{j['company']}</td>
          <td>{j['location']}</td>
          <td style="max-width:600px">{j['snippet']}</td>
        </tr>""")
    table = f"""
    <table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;font-family:Arial;font-size:14px">
      <thead>
        <tr>
          <th>Source</th><th>Title</th><th>Company</th><th>Location</th><th>Summary</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>"""
    return f"""
    <p>Daily fresher jobs matching <b>Python, SQL, Machine Learning, Pandas, NumPy, Visual Studio</b> (India). Prefer Hyderabad if onsite.</p>
    {table}
    <p style="font-size:12px;color:#666">Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} IST</p>
    """

def send_email(html_body):
    sender = os.environ.get("GMAIL_SENDER")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("RECIPIENT", sender)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Daily Fresher Jobs (India) – {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, app_pw)
        server.sendmail(sender, [recipient], msg.as_string())

def main():
    jobs = collect_all()
    html = render_html(jobs)
    send_email(html)

if __name__ == "__main__":
    main()
