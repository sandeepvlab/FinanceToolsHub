from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests, math, logging

app = Flask(__name__)
CORS(app)  # ✅ allows frontend to make POST calls safely (fixes 405 errors)
logging.basicConfig(level=logging.INFO)

# Your FRED API key
FRED_API_KEY = "14290ebba38ce5ea815d8529a6242114"

# FRED Series mapping
FRED_SERIES = {
    30: "MORTGAGE30US",
    15: "MORTGAGE15US",
    "ARM_5": "MORTGAGE5US"
}

def fetch_fred_latest(series_id):
    try:
        url = (
            "https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        j = r.json()
        obs = j.get("observations", [])
        if not obs:
            return None
        val = obs[0].get("value")
        return float(val)
    except Exception as e:
        logging.warning("FRED fetch failed for %s: %s", series_id, e)
        return None


def get_interest_rate_for(loan_type, loan_term, zipcode=""):
    """Return the best possible mortgage rate based on FRED data."""
    if loan_type == "Conventional":
        if loan_term in FRED_SERIES:
            rate = fetch_fred_latest(FRED_SERIES[loan_term])
            if rate:
                return rate
        r30 = fetch_fred_latest(FRED_SERIES.get(30))
        r15 = fetch_fred_latest(FRED_SERIES.get(15))
        if r30 and r15:
            if loan_term == 20:
                return round((r30 + r15) / 2, 2)
            if loan_term == 10:
                return round(r15 - 0.3, 2)
        return r30 or 6.8

    if loan_type == "ARM":
        r5 = fetch_fred_latest(FRED_SERIES.get("ARM_5")) or 6.2
        if loan_term == 3:
            return round(r5 - 0.25, 2)
        if loan_term == 7:
            return round(r5 + 0.25, 2)
        if loan_term == 10:
            return round(r5 + 0.5, 2)
        return r5
    return 6.8


def compute_pmi_percent(down_percent):
    if down_percent >= 20:
        return 0.0
    if down_percent >= 15:
        return 0.35
    if down_percent >= 10:
        return 0.65
    return 0.95


def estimate_home_insurance_annual(zipcode, home_value):
    base_rate = 0.003
    prefix = int(str(zipcode)[:2]) if zipcode else 99
    if prefix < 20:
        mod = 1.05
    elif prefix < 50:
        mod = 0.95
    else:
        mod = 1.0
    return round(home_value * base_rate * mod, 2)


def monthly_payment(principal, annual_rate, years):
    if principal <= 0:
        return 0.0
    r = annual_rate / 100 / 12
    n = years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/calculate", methods=["POST"])
def calculate():
    data = request.get_json()
    zipcode = data.get("zipcode", "")
    home_value = float(data.get("home_value", 0))
    down_value = float(data.get("down_payment_value", 0))
    down_type = data.get("down_payment_type", "%")
    loan_type = data.get("loan_type", "Conventional")
    loan_term = int(data.get("loan_term", 30))
    property_tax = float(data.get("property_tax", 0))
    pmi_input = data.get("pmi", "")
    home_ins = data.get("home_ins", "")
    hoa = float(data.get("hoa", 0))

    # Down payment
    if down_type == "%":
        down_payment_amount = home_value * (down_value / 100)
        down_percent = down_value
    else:
        down_payment_amount = down_value
        down_percent = (down_payment_amount / home_value) * 100 if home_value else 0

    loan_amount = max(0, home_value - down_payment_amount)
    rate = get_interest_rate_for(loan_type, loan_term, zipcode)
    pmi_percent = compute_pmi_percent(down_percent) if not pmi_input else float(pmi_input)
    insurance_annual = (
        float(home_ins)
        if home_ins
        else estimate_home_insurance_annual(zipcode, home_value)
    )

    monthly_pi = monthly_payment(loan_amount, rate, loan_term)
    monthly_total = round(
        monthly_pi + (property_tax / 12) + (insurance_annual / 12)
        + ((loan_amount * (pmi_percent / 100)) / 12) + hoa,
        2
    )

    return jsonify({
        "loan_amount": round(loan_amount, 2),
        "interest_rate": round(rate, 3),
        "monthly_payment": monthly_total
    })


if __name__ == "__main__":
    app.run(debug=True)
