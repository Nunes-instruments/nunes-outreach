import sys, os, csv, json, random, time, datetime as dt, requests
from core import *
init()
def pick(d, *ks):
    for k in ks:
        if d.get(k): return str(d[k]).strip()
    return ""
def tofloat(x):
    try: return float(x)
    except Exception: return None
def cmd_import(path=None):
    n = 0
    if path:
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            n += add_contact(pick(r, "lead"), pick(r, "product"), pick(r, "name"), pick(r, "company"), pick(r, "phone"), pick(r, "email"), tofloat(pick(r, "rating")), pick(r, "gstin"))
    else:
        url = E("DASHBOARD_URL", "http://desktop-chkr5ga.tail28e6b9.ts.net:8081").rstrip("/") + E("LEADS_PATH", "/api/requests")
        try:
            res = requests.get(url, timeout=30).json()
            requests_list = res.get("requests", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
        except Exception as e:
            print("Failed to fetch leads from dashboard:", e)
            return

        print(f"Loaded {len(requests_list)} requests from Price Desk.")
        for r in requests_list:
            lead_id = pick(r, "id")
            prod = pick(r, "product")
            if not prod: continue
            
            # Check existing supplier info if any
            supp = pick(r, "supplier")
            phone = pick(r, "phone")
            mail = pick(r, "email")
            if phone or mail:
                if add_contact(lead_id, prod, "", supp, phone, mail):
                    n += 1
            
            # If price is empty or pending, discover Indian suppliers automatically
            price = pick(r, "price")
            status = pick(r, "status")
            if not price or status in ("process", "assigned", "pending"):
                print(f"Auto-discovering suppliers across India for: {prod}...")
                for d in discover(prod, limit=10):
                    if add_contact(lead_id, prod, "", d["company"], d["phone"], d["email"], d["rating"], d["gstin"]):
                        print(f"  + Added: {d['company']} | {d['phone']}")
                        n += 1
    print("Import & Discovery complete. Contacts added:", n)

def cmd_discover(product):
    for d in discover(product):
        if add_contact("discover", product, "", d["company"], d["phone"], d["email"], d["rating"], d["gstin"]): print("added", d["company"])

def today(ch):
    with conn() as c:
        return c.execute("select count(*) from log where channel=? and date(ts)=date('now') and kind!='test'", (ch,)).fetchone()[0]

def cmd_send(followup=False, profile=None):
    if os.path.exists("PAUSE"): return print("PAUSED")
    if not TEST and not 10 <= dt.datetime.now().hour < 18: return print("Outside 10-18 business hours (set TEST_MODE=1 to bypass)")
    days, mx = int(E("FOLLOWUP_DAYS", 2)), int(E("MAX_FOLLOWUPS", 2))
    q = ("select * from contacts where stopped=0 and reply is null and followups<? and sent_at<datetime('now',?)", (mx, f"-{days} days")) if followup \
        else ("select * from contacts where stopped=0 and (wa_status='pending' or mail_status='pending')", ())
    with conn() as c: rows = c.execute(*q).fetchall()
    if TEST: rows = rows[:3]
    wl, ml = int(E("DAILY_WA_LIMIT", 50)), int(E("DAILY_MAIL_LIMIT", 100))
    wa = None
    try:
        for r in rows:
            if os.path.exists("PAUSE"): break
            text, kind = compose(r, followup), "test" if TEST else ("followup" if followup else "first")
            ph, ml_to = (E("TEST_PHONE"), E("TEST_EMAIL")) if TEST else (r["phone"], r["email"])
            ws, ms = r["wa_status"], r["mail_status"]
            if ph and (ws == "pending" or followup and ws == "sent") and today("wa") < wl:
                wa = wa or WA(profile).__enter__(); ws = wa.send(ph, text)
                with conn() as c: c.execute("insert into log(contact_id,channel,kind,body) values(?,?,?,?)", (r["id"], "wa", kind, text))
                print(r["id"], "wa", ws); time.sleep(random.randint(15, 30))
            if ml_to and (ms == "pending" or followup and ms == "sent") and today("mail") < ml:
                try: send_mail(ml_to, f"Enquiry: {r['product']}", text); ms = "sent"
                except Exception as e: ms = "failed"; print("mail", e)
                with conn() as c: c.execute("insert into log(contact_id,channel,kind,body) values(?,?,?,?)", (r["id"], "mail", kind, text))
                print(r["id"], "mail", ms); time.sleep(random.randint(10, 20))
            if not TEST:
                with conn() as c: c.execute("update contacts set wa_status=?,mail_status=?,sent_at=datetime('now'),followups=followups+? where id=?",
                                            (ws, ms, 1 if followup else 0, r["id"]))
    finally:
        if wa: wa.__exit__()

def cmd_rank():
    wait, req = float(E("RANK_AFTER_HOURS", 24)), E("REQUIRE_VERIFIED", "0") == "1"
    rows_out = []
    with conn() as c:
        prods = [x[0] for x in c.execute("select product from contacts group by product having min(sent_at) < datetime('now', ?)", (f"-{wait} hours",))]
        for p in prods:
            rows = c.execute("select * from contacts where product=? and price_inr>0 and stopped=0" + (" and verified=1" if req else ""), (p,)).fetchall()
            if not rows: continue
            lo = min(r["price_inr"] for r in rows)
            ranked = sorted(((0.6 * lo / r["price_inr"] + 0.3 * (r["rating"] or 3) / 5 + 0.1 * r["verified"], r) for r in rows), key=lambda x: -x[0])
            for i, (s, r) in enumerate(ranked, 1):
                c.execute("update contacts set score=?,rnk=? where id=?", (round(s, 3), i, r["id"]))
                sp = json.loads(r["parsed"] or "{}")
                rows_out.append([p, i, r["company"], r["name"], r["phone"], r["email"], r["price_inr"], sp.get("gst_included"),
                                 sp.get("shipping_date"), r["rating"], "yes" if r["verified"] else "no", r["gstin"], round(s, 3)])
    with open("best_suppliers.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["product", "rank", "company", "contact_name", "phone", "email", "price_inr_incl_gst", "gst_included_in_quote",
                                       "shipping_date", "rating", "gst_verified", "gstin", "score"]); w.writerows(rows_out)
    for x in rows_out:
        if x[1] == 1: print("BEST", x[0], "->", x[2], x[6], x[5], x[4])
    print("saved best_suppliers.csv")

def cmd_replies(profile=None):
    with conn() as c: rows = c.execute("select * from contacts where reply is null and sent_at is not null").fetchall()
    wa = None
    try:
        for r in rows:
            txt = None
            if r["email"]:
                try: txt = mail_reply(r["email"])
                except Exception as e: print("imap", e)
            if not txt and r["wa_status"] == "sent" and r["phone"]:
                wa = wa or WA(profile).__enter__(); txt = wa.last_replies(r["phone"])
            if txt:
                p = parse_reply(txt); pr = p.get("price_inr")
                try: pr = float(pr) * (1 + float(E("GST_RATE", 18)) / 100 if p.get("gst_included") == "no" else 1) if pr else None
                except Exception: pr = None
                g = str(p.get("gstin") or "").upper(); ok = is_gstin(g)
                with conn() as c: c.execute("update contacts set reply=?,parsed=?,price_inr=?,gstin=?,verified=? where id=?",
                                            (txt, json.dumps(p), pr, g if ok else r["gstin"], 1 if ok else r["verified"], r["id"]))
                print("reply from", r["id"])
                # Auto-update Price Desk if price or quotation details obtained
                if pr and r["lead"] and r["lead"] != "discover":
                    remark = f"Auto-Quoted: INR {pr} (GST: {p.get('gst_included', 'unknown')}). Shipping: {p.get('shipping_date', '')}"
                    update_desk(r["lead"], pr, r["company"], r["phone"], r["email"], remark)
    finally:
        if wa: wa.__exit__()

def cmd_loop(profile=None):
    while True:
        for f in (cmd_import, lambda: cmd_send(False, profile), lambda: cmd_replies(profile), cmd_rank, lambda: cmd_send(True, profile)):
            try: f()
            except Exception as e: print("step error:", e)
        print("sleeping 15 min..."); time.sleep(900)

if __name__ == "__main__":
    a = sys.argv[1:] + [None, None]
    cmd = a[0] or "dashboard"
    profile = a[2] if a[2] else (a[1] if a[1] and a[0] not in ("import", "discover") else None)
    
    if cmd == "import": cmd_import(a[1])
    elif cmd == "discover": cmd_discover(" ".join([x for x in a[1:-2] if x]))
    elif cmd == "send": cmd_send(False, profile)
    elif cmd == "followup": cmd_send(True, profile)
    elif cmd == "replies": cmd_replies(profile)
    elif cmd == "loop": cmd_loop(profile)
    elif cmd == "rank": cmd_rank()
    elif cmd == "dashboard": __import__("app").app.run(host="0.0.0.0", port=5050)
    else: print("Unknown command:", cmd)

