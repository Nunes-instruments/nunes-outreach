import os, re, json, sqlite3, random, time, smtplib, imaplib, email, urllib.parse
from email.message import EmailMessage
from dotenv import load_dotenv
load_dotenv()
E = os.environ.get
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outreach.db")
TEST = E("TEST_MODE", "1") == "1"
GST_RE = r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]\b"
def is_gstin(g):
    g = (g or "").upper()
    if not re.fullmatch(GST_RE, g): return False
    cs = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"; t = 0
    for i, ch in enumerate(g[:14]):
        v = cs.index(ch) * (1 if i % 2 == 0 else 2); t += v // 36 + v % 36
    return cs[(36 - t % 36) % 36] == g[14]

def conn():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init():
    with conn() as c:
        c.executescript("""
CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY, lead TEXT, product TEXT, name TEXT, company TEXT,
 phone TEXT DEFAULT '', email TEXT DEFAULT '', wa_status TEXT DEFAULT 'pending', mail_status TEXT DEFAULT 'pending',
 sent_at TEXT, followups INTEGER DEFAULT 0, reply TEXT, parsed TEXT, stopped INTEGER DEFAULT 0,
 UNIQUE(product, phone, email));
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP, contact_id INT, channel TEXT, kind TEXT, body TEXT);""")
        cols = {r[1] for r in c.execute("pragma table_info(contacts)")}
        for n, t in (("rating", "REAL"), ("gstin", "TEXT"), ("verified", "INTEGER DEFAULT 0"), ("price_inr", "REAL"), ("score", "REAL"), ("rnk", "INTEGER")):
            if n not in cols: c.execute(f"ALTER TABLE contacts ADD COLUMN {n} {t}")

def norm_phone(p):
    d = re.sub(r"\D", "", p or "")
    if len(d) == 10: d = "91" + d
    return d if 11 <= len(d) <= 13 else ""

def excluded(*vals):
    default_terms = "nunes,testinstrumentation,test instrumentation,nunes instrumentation,nunes instruments"
    terms = [t.strip().lower() for t in (E("EXCLUDE") or default_terms).split(",") if t.strip()]
    s = " ".join(str(v or "") for v in vals).lower()
    s_compact = re.sub(r"[^a-z0-9]", "", s)
    for t in terms:
        t_clean = t.lower()
        t_compact = re.sub(r"[^a-z0-9]", "", t_clean)
        if t_clean in s or (t_compact and t_compact in s_compact):
            return True
    return False

def add_contact(lead, product, name, company, phone, mail, rating=None, gstin=""):
    phone, mail = norm_phone(phone), (mail or "").strip().lower()
    if not (phone or mail) or excluded(name, company, mail): return False
    with conn() as c:
        try:
            g = (gstin or "").upper(); g = g if is_gstin(g) else ""
            c.execute("INSERT INTO contacts(lead,product,name,company,phone,email,rating,gstin,verified) VALUES(?,?,?,?,?,?,?,?,?)",
                      (lead, product, name, company, phone, mail, rating, g, 1 if g else 0)); return True
        except sqlite3.IntegrityError: return False

def llm(system, user, json_mode=False):
    from openai import OpenAI
    kw = {"response_format": {"type": "json_object"}} if json_mode else {}
    r = OpenAI(api_key=E("OPENAI_API_KEY")).chat.completions.create(
        model=E("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kw)
    return r.choices[0].message.content.strip()

QS = ("1) Are you a dealer or manufacturer? 2) Best Price 3) Catalogue 4) Product video 5) Proof (photos/past supply) "
      "6) Shipping / delivery lead time 7) Does the price include GST or not?")

def compose(c, followup=False):
    who = c["name"] or "Sir/Madam"
    if followup:
        base = f"Hello {who}, a gentle reminder about our enquiry for *{c['product']}*. Kindly share the price, catalogue and delivery date (and whether GST is included). Thank you."
    else:
        base = (f"Hello {who}, this is {E('SENDER_NAME','Sivanesan')} from {E('MY_COMPANY','Purchase Team')}. We are looking to buy *{c['product']}*. "
                f"Please share: {QS} Thank you.")
    if E("OPENAI_API_KEY"):
        try:
            return llm("Rewrite this business WhatsApp message in slightly different polite wording. Keep ALL questions and facts, "
                       "keep it short, plain text, no emojis. Return only the message.", base)
        except Exception: pass
    return base

def parse_reply(text):
    out = {}
    if E("OPENAI_API_KEY"):
        try:
            out = json.loads(llm("Extract from a supplier reply JSON with keys: role (dealer/manufacturer/unknown), price, gst_included "
                "(yes/no/unknown), shipping_date, catalog (yes/no), video (yes/no), proof (yes/no), price_inr (number, INR per unit, null if unknown), gstin, summary. Never guess; use unknown/null.", text, True))
            if out.get("price_inr") or out.get("price"):
                return out
        except Exception: pass

    # Rule-based / Regex fallback parsing
    t = text.lower()
    # Extract price
    pm = re.search(r"(?:rs\.?|inr|₹|price\s*[:=]?)\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    price_val = None
    if pm:
        try: price_val = float(pm.group(1).replace(",", ""))
        except Exception: pass
    else:
        # Check standalone numbers (e.g. 15000/- or 45000)
        nums = re.findall(r"\b(\d{3,7})(?:\s*/-|\s*inr|\s*rs)?\b", text, re.IGNORECASE)
        if nums:
            try: price_val = float(nums[0])
            except Exception: pass

    # GST check
    gst_inc = "unknown"
    if re.search(r"(inclusive|included|incl|with gst)", t): gst_inc = "yes"
    elif re.search(r"(exclusive|extra|\+\s*18%|\+gst|plus gst|excluding)", t): gst_inc = "no"

    # Role
    role = "dealer" if "dealer" in t else ("manufacturer" if ("mfr" in t or "manufactur" in t) else "unknown")

    # Shipping
    sm = re.search(r"(\d+\s*(?:to\s*\d+\s*)?(?:days?|weeks?)|ready\s*stock|dispatch\s*today|tomorrow)", t)
    ship = sm.group(1) if sm else "unknown"

    g = re.search(GST_RE, text.upper())
    return {
        "role": role,
        "price": str(price_val) if price_val else "",
        "price_inr": price_val,
        "gst_included": gst_inc,
        "shipping_date": ship,
        "catalog": "yes" if re.search(r"(catalog|catalogue|pdf|datasheet|attached)", t) else "no",
        "video": "yes" if re.search(r"(video|clip|sent video)", t) else "no",
        "proof": "yes" if re.search(r"(photo|image|proof|test)", t) else "no",
        "gstin": g.group(0) if g else "",
        "summary": text[:200].strip()
    }

def send_mail(to, subject, body):
    m = EmailMessage(); m["From"] = E("GMAIL_USER"); m["To"] = to; m["Subject"] = subject
    if E("BCC_EMAIL"): m["Bcc"] = E("BCC_EMAIL")
    m.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(E("GMAIL_USER"), E("GMAIL_APP_PASSWORD")); s.send_message(m)

def mail_reply(addr):
    m = imaplib.IMAP4_SSL("imap.gmail.com"); m.login(E("GMAIL_USER"), E("GMAIL_APP_PASSWORD")); m.select("INBOX")
    ids = m.search(None, "FROM", f'"{addr}"')[1][0].split()
    if not ids: return None
    em = email.message_from_bytes(m.fetch(ids[-1], "(RFC822)")[1][0][1])
    for p in em.walk():
        if p.get_content_type() == "text/plain":
            return p.get_payload(decode=True).decode(errors="ignore")[:2000]

class WA:
    def __init__(self, profile_name=None):
        self.profile_name = profile_name or E("WA_PROFILE_NAME", "default")
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.p = sync_playwright().start()
        profile_dir = os.path.join(os.path.dirname(DB), f"wa_profile_{self.profile_name}")
        self.ctx = self.p.chromium.launch_persistent_context(profile_dir, headless=False)
        self.pg = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.pg.on("dialog", lambda d: d.accept())
        self.pg.goto("https://web.whatsapp.com")
        print(f"WhatsApp Web [{self.profile_name}]: Scan QR if shown...")
        self.pg.wait_for_selector("#pane-side", timeout=240000)
        return self
    def __exit__(self, *a):
        try: self.ctx.close(); self.p.stop()
        except Exception: pass
    def _open(self, phone, text=""):
        self.pg.goto(f"https://web.whatsapp.com/send?phone={phone}&text={urllib.parse.quote(text)}")
        try: self.pg.wait_for_selector("footer div[contenteditable='true']", timeout=30000); return True
        except Exception: return False
    def send(self, phone, text):
        if not self._open(phone, text): return "no_whatsapp"
        time.sleep(2); self.pg.keyboard.press("Enter"); time.sleep(3); return "sent"
    def last_replies(self, phone):
        if not self._open(phone): return None
        time.sleep(3)
        return "\n".join(e.inner_text() for e in self.pg.query_selector_all("div.message-in")[-3:]) or None

def update_desk(lead_id, price, supplier, phone="", email="", remark=""):
    import requests
    base_url = E("DASHBOARD_URL", "http://desktop-chkr5ga.tail28e6b9.ts.net:8081").rstrip("/")
    url = f"{base_url}/api/requests/{lead_id}"
    try:
        data = {
            "price": str(price),
            "supplier": supplier or "",
            "phone": phone or "",
            "email": email or "",
            "purchaseRemark": remark or "",
            "status": "priced"
        }
        res = requests.patch(url, data=data, timeout=15)
        print(f"Updated Price Desk for lead {lead_id}: HTTP {res.status_code}")
        return res.status_code in (200, 204)
    except Exception as e:
        print(f"Failed to update Price Desk ({lead_id}):", e)
        return False

def discover(product, limit=15):
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True); pg = b.new_page()
        pg.goto("https://dir.indiamart.com/search.mp?ss=" + urllib.parse.quote(product)); pg.wait_for_timeout(4000)
        links = list({a.get_attribute("href") for a in pg.query_selector_all("a[href*='/proddetail/']") if a.get_attribute("href")})[:limit]
        for l in links:
            try:
                pg.goto(l); pg.wait_for_timeout(2500); t = pg.inner_text("body")
                ph = re.findall(r"(?:\+91[\s-]?)?[6-9]\d{9}", t); em = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", t)
                rt = re.search(r"\b([1-5](?:\.\d)?)\s*(?:/\s*5|★|out of 5)", t); g = re.search(GST_RE, t)
                co = pg.title().split("|")[-1].strip()
                if not excluded(co, em[0] if em else "", l):
                    out.append(dict(company=co, phone=ph[0] if ph else "", email=em[0] if em else "", url=l,
                                    rating=float(rt.group(1)) if rt else None, gstin=g.group(0) if g else ""))
            except Exception: pass
        b.close()
    return out
