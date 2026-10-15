# Nunes Supplier Outreach & Price Desk Automation

Automated supplier intelligence, RFQ dispatching (WhatsApp Web multi-account & Email with BCC), AI reply parsing, and auto-updating into Price Desk.

## Features
- **Price Desk Auto-Polling**: Connects to `http://desktop-chkr5ga.tail28e6b9.ts.net:8081/api/requests` to import unquoted/pending requests.
- **India-wide Supplier Sourcing**: Searches manufacturers, dealers, and traders across India.
- **Strict Negative Filter**: Excludes `nunes instrumentation` and `testinstrumentation` (own companies).
- **Multi-Account WhatsApp Web**: Automate outreach with multiple profiles (`python run.py send [profile_name]`).
- **Email Outreach with BCC**: Sends professional RFQs with BCC to `sivanesanbai@gmail.com`.
- **AI & Heuristic Reply Extraction**: Parses price, GST inclusive/exclusive status, catalogs, video proof, and delivery dates.
- **Price Desk Auto-Patch**: Automatically updates quoted details back to the Price Desk portal.
- **Web Dashboard**: Live tracking dashboard on port 5050 / Vercel.

## Quick Start
```bash
# Install dependencies
pip install -r requirements.txt playwright
playwright install chromium

# Import leads from Price Desk
python run.py import

# Start WhatsApp RFQ outreach
python run.py send sivanesan

# Check for supplier replies & auto-update Price Desk
python run.py replies sivanesan

# Run 24/7 background loop
python run.py loop sivanesan

# Start Web Dashboard
python run.py dashboard
```
