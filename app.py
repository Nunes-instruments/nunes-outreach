import os, json, html
from flask import Flask, redirect, request
from core import conn, init

init()
app = Flask(__name__)

PAUSE_FILE = "/tmp/PAUSE" if os.environ.get("VERCEL") else os.path.join(os.path.dirname(__file__), "PAUSE")

@app.route("/")
def home():
    with conn() as c:
        rows = c.execute("SELECT * FROM contacts ORDER BY product, rnk IS NULL, rnk, id DESC").fetchall()
    
    total = len(rows)
    pending_wa = sum(1 for r in rows if r["wa_status"] == "pending" and r["phone"])
    pending_mail = sum(1 for r in rows if r["mail_status"] == "pending" and r["email"])
    quoted = sum(1 for r in rows if r["price_inr"] and r["price_inr"] > 0)
    paused = os.path.exists(PAUSE_FILE)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nunes Supplier Outreach & Price Desk</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>body {{ font-family: 'Inter', sans-serif; }}</style>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen">
    <div class="max-w-7xl mx-auto px-4 py-8">
        <!-- Header -->
        <div class="flex flex-col md:flex-row md:items-center md:justify-between pb-6 border-b border-slate-200 gap-4">
            <div>
                <h1 class="text-2xl font-bold text-slate-900 flex items-center gap-2">
                    <span class="p-2 bg-indigo-600 text-white rounded-lg">🚀</span>
                    Nunes Supplier Outreach & Price Desk
                </h1>
                <p class="text-sm text-slate-500 mt-1">Automated Supplier Sourcing, WhatsApp / Email RFQ & Live Price Desk Tracker</p>
            </div>
            <div class="flex items-center gap-3">
                <a href="/{'resume' if paused else 'pause'}" class="px-4 py-2 rounded-lg font-medium text-sm transition shadow-sm {'bg-amber-600 hover:bg-amber-700 text-white' if paused else 'bg-slate-800 hover:bg-slate-900 text-white'}">
                    {'▶ Resume Outreach' if paused else '⏸ Pause Outreach'}
                </a>
                <button onclick="window.location.reload()" class="px-3 py-2 bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 text-sm font-medium rounded-lg shadow-sm">
                    🔄 Refresh
                </button>
            </div>
        </div>

        <!-- Metric Cards -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 my-6">
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Suppliers</div>
                <div class="text-2xl font-bold text-slate-900 mt-1">{total}</div>
                <div class="text-xs text-indigo-600 mt-1">Discovered across India</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Pending WhatsApp</div>
                <div class="text-2xl font-bold text-emerald-600 mt-1">{pending_wa}</div>
                <div class="text-xs text-slate-500 mt-1">Ready for RFQ dispatch</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Pending Email</div>
                <div class="text-2xl font-bold text-blue-600 mt-1">{pending_mail}</div>
                <div class="text-xs text-slate-500 mt-1">BCC: sivanesanbai@gmail.com</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Quotes Received</div>
                <div class="text-2xl font-bold text-purple-600 mt-1">{quoted}</div>
                <div class="text-xs text-slate-500 mt-1">Auto-patched to Price Desk</div>
            </div>
        </div>

        <!-- Filter bar -->
        <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm mb-6 flex flex-col md:flex-row gap-4 items-center justify-between">
            <div class="relative w-full md:w-96">
                <input type="text" id="searchInput" onkeyup="filterTable()" placeholder="Search product, company, phone, city..." class="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
                <span class="absolute left-3 top-2.5 text-slate-400">🔍</span>
            </div>
            <div class="text-xs text-slate-500">
                Auto-refreshes every 30s • Excluded: <span class="font-semibold text-rose-600">Nunes & Testinstrumentation</span>
            </div>
        </div>

        <!-- Table -->
        <div class="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm" id="contactsTable">
                    <thead class="bg-slate-100 text-slate-700 text-xs font-semibold uppercase tracking-wider border-b border-slate-200">
                        <tr>
                            <th class="py-3 px-4">Product</th>
                            <th class="py-3 px-4">Company</th>
                            <th class="py-3 px-4">Phone (WhatsApp)</th>
                            <th class="py-3 px-4">Email</th>
                            <th class="py-3 px-4">Status</th>
                            <th class="py-3 px-4">Quoted Price</th>
                            <th class="py-3 px-4">GST Included?</th>
                            <th class="py-3 px-4">Shipping</th>
                            <th class="py-3 px-4">Rating</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-200 text-slate-700">
"""

    for r in rows:
        p = json.loads(r["parsed"] or "{}")
        wa_badge = f'<span class="px-2 py-0.5 text-xs rounded-full font-medium {"bg-emerald-100 text-emerald-700" if r["wa_status"]=="sent" else "bg-amber-100 text-amber-700"}">WA: {r["wa_status"]}</span>'
        price_display = f'<span class="font-bold text-slate-900">₹{r["price_inr"]:,.2f}</span>' if r["price_inr"] else '<span class="text-slate-400 text-xs">Awaiting quote</span>'
        gst_display = p.get("gst_included") or ("Yes" if r["verified"] else "-")
        rating_val = f'⭐ {r["rating"]}' if r["rating"] else '-'

        html_content += f"""
                        <tr class="hover:bg-slate-50 transition">
                            <td class="py-3 px-4 font-semibold text-slate-900">{html.escape(str(r["product"] or ""))}</td>
                            <td class="py-3 px-4">{html.escape(str(r["company"] or r["name"] or ""))}</td>
                            <td class="py-3 px-4 font-mono text-xs">{html.escape(str(r["phone"] or ""))}</td>
                            <td class="py-3 px-4 text-xs text-slate-500">{html.escape(str(r["email"] or ""))}</td>
                            <td class="py-3 px-4">{wa_badge}</td>
                            <td class="py-3 px-4">{price_display}</td>
                            <td class="py-3 px-4 text-xs">{html.escape(str(gst_display))}</td>
                            <td class="py-3 px-4 text-xs text-slate-600">{html.escape(str(p.get("shipping_date") or "-"))}</td>
                            <td class="py-3 px-4 text-xs font-semibold text-amber-600">{rating_val}</td>
                        </tr>
"""

    html_content += """
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        function filterTable() {
            let input = document.getElementById("searchInput").value.toLowerCase();
            let rows = document.querySelectorAll("#contactsTable tbody tr");
            rows.forEach(r => {
                let text = r.innerText.toLowerCase();
                r.style.display = text.includes(input) ? "" : "none";
            });
        }
    </script>
</body>
</html>"""
    return html_content

@app.route("/pause")
def pause():
    open(PAUSE_FILE, "w").close()
    return redirect("/")

@app.route("/resume")
def resume():
    if os.path.exists(PAUSE_FILE):
        try: os.remove(PAUSE_FILE)
        except Exception: pass
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
