from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests, os, logging

app = Flask(__name__, template_folder="templates")
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRED_API_KEY = os.environ.get("FRED_API_KEY", "14290ebba38ce5ea815d8529a6242114")

FRED_SERIES = {
    30: "MORTGAGE30US",
    15: "MORTGAGE15US",
    "ARM_5": "MORTGAGE5US"
}


def fetch_fred_latest(series_id):
    """Fetch latest observation from FRED"""
    try:
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1
        }
        r = requests.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        obs = data.get("observations", [])
        if not obs:
            return None
        val = obs[0].get("value")
        return float(val) if val not in (".", "", None) else None
    except Exception as e:
        logger.warning(f"FRED fetch failed for {series_id}: {e}")
        return None


def get_interest_rate_for(loan_type: str, loan_term: int):
    """Return interest rate from FRED based on loan type and term"""
    if loan_type == "Conventional":
        if loan_term in (15, 30):
            val = fetch_fred_latest(FRED_SERIES.get(loan_term))
            if val:
                return round(val, 3)
        # Fallback interpolation
        r30 = fetch_fred_latest(FRED_SERIES.get(30)) or 6.8
        r15 = fetch_fred_latest(FRED_SERIES.get(15)) or 6.2
        if loan_term == 20:
            return round((r30 + r15) / 2, 3)
        if loan_term == 10:
            return round(r15 - 0.3, 3)
        return round(r30, 3)

    elif loan_type == "ARM":
        r5 = fetch_fred_latest(FRED_SERIES.get("ARM_5")) or 6.0
        if loan_term == 3:
            return round(r5 - 0.25, 3)
        if loan_term == 5:
            return round(r5, 3)
        if loan_term == 7:
            return round(r5 + 0.25, 3)
        if loan_term == 10:
            return round(r5 + 0.5, 3)
        return round(r5, 3)

    return 6.8


def compute_pmi_percent(down_payment_percent):
    if down_payment_percent >= 20:
        return 0
    if down_payment_percent >= 15:
        return 0.35
    if down_payment_percent >= 10:
        return 0.65
    return 0.95


def estimate_home_insurance_annual(zipcode, home_value):
    try:
        prefix = int(str(zipcode)[:2])
    except:
        prefix = 99
    base_rate = 0.003
    if prefix < 20:
        factor = 1.05
    elif prefix < 50:
        factor = 0.95
    else:
        factor = 1.0
    return round(home_value * base_rate * factor, 2)


def monthly_payment(principal, rate, years):
    r = rate / 100 / 12
    n = years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/_rate_hint")
def rate_hint():
    loan_type = request.args.get("loan_type", "Conventional")
    loan_term = int(request.args.get("loan_term", 30))
    zipcode = request.args.get("zipcode", "")
    rate = get_interest_rate_for(loan_type, loan_term)
    return jsonify({"rate": rate})


@app.route("/calculate", methods=["POST"])
def calculate():
    data = request.get_json()
    zipcode = str(data.get("zipcode", "")).strip()
    home_value = float(data.get("home_value", 0))
    down_value = float(data.get("down_payment_value", 0))
    down_type = data.get("down_payment_type", "%")
    loan_type = data.get("loan_type", "Conventional")
    loan_term = int(data.get("loan_term", 30))
    property_tax = float(data.get("property_tax", 0))
    hoa = float(data.get("hoa", 0))

    # Down payment
    if down_type == "%":
        down_amt = home_value * (down_value / 100)
    else:
        down_amt = down_value
    down_percent = (down_amt / home_value) * 100 if home_value > 0 else 0
    loan_amt = home_value - down_amt

    # Interest rate
    rate = get_interest_rate_for(loan_type, loan_term)

    # PMI and Insurance
    pmi = compute_pmi_percent(down_percent)
    home_ins = estimate_home_insurance_annual(zipcode, home_value)
    monthly_pi = monthly_payment(loan_amt, rate, loan_term)
    monthly_total = monthly_pi + (property_tax / 12) + (home_ins / 12) + hoa + ((loan_amt * (pmi / 100)) / 12)

    return jsonify({
        "loan_amount": round(loan_amt, 2),
        "down_percent": round(down_percent, 2),
        "interest_rate": round(rate, 3),
        "pmi_percent": round(pmi, 2),
        "home_ins": round(home_ins, 2),
        "monthly_payment": round(monthly_total, 2)
    })


if __name__ == "__main__":
    app.run(debug=True)
