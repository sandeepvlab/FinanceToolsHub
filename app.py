from flask import Flask, render_template, request, jsonify
import requests
import math
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRED_API_KEY = "14290ebba38ce5ea815d8529a6242114"

FRED_SERIES = {
    30: "MORTGAGE30US",
    15: "MORTGAGE15US",
    "ARM_5": "MORTGAGE5US"
}


def fetch_fred_latest(series_id):
    """Fetch latest observation from FRED."""
    try:
        url = (
            "https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        )
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        if obs and obs[0].get("value") not in ("", None):
            return float(obs[0]["value"])
    except Exception as e:
        logger.warning("FRED fetch failed for %s: %s", series_id, e)
    return None


def get_interest_rate(loan_type, term):
    """Return best available real-time rate."""
    if loan_type == "Conventional":
        if term in FRED_SERIES:
            val = fetch_fred_latest(FRED_SERIES[term])
            if val:
                return val
        # interpolate 20/10 from 30/15
        r30 = fetch_fred_latest(FRED_SERIES[30]) or 6.8
        r15 = fetch_fred_latest(FRED_SERIES[15]) or 6.2
        if term == 20:
            return round(r15 + (r30 - r15) * (5 / 15), 2)
        if term == 10:
            return round(r15 - (r30 - r15) * 0.3, 2)
        return r30
    else:
        r5 = fetch_fred_latest(FRED_SERIES["ARM_5"]) or 6.3
        if term == 3:
            return round(r5 - 0.25, 2)
        if term == 7:
            return round(r5 + 0.25, 2)
        if term == 10:
            return round(r5 + 0.5, 2)
        return r5


def estimate_home_insurance(zipcode, value):
    base_rate = 0.003
    return round(value * base_rate, 2)


def compute_pmi(dp_percent):
    if dp_percent >= 20:
        return 0
    if dp_percent >= 15:
        return 0.35
    if dp_percent >= 10:
        return 0.65
    return 0.95


def monthly_payment(principal, rate, years):
    if principal <= 0 or years <= 0:
        return 0
    r = rate / 100 / 12
    n = years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/calculate", methods=["POST"])
def calculate():
    data = request.json
    zipcode = data.get("zipcode", "")
    home_value = float(data.get("home_value", 0))
    down_value = float(data.get("down_payment", 0))
    down_type = data.get("down_type", "%")
    loan_type = data.get("loan_type", "Conventional")
    term = int(data.get("term", 30))
    property_tax = float(data.get("property_tax", 0))
    home_ins = float(data.get("home_ins", 0))
    hoa = float(data.get("hoa", 0))

    # Calculate downpayment
    if down_type == "%":
        down_amount = home_value * down_value / 100
    else:
        down_amount = down_value

    loan_amount = max(0, home_value - down_amount)
    dp_percent = 100 * down_amount / home_value if home_value else 0

    # Fetch real rate
    rate = get_interest_rate(loan_type, term)

    # Insurance estimate if blank
    if home_ins == 0:
        home_ins = estimate_home_insurance(zipcode, home_value)

    # PMI
    pmi_percent = compute_pmi(dp_percent)
    monthly_pmi = (loan_amount * pmi_percent / 100) / 12

    monthly_pi = monthly_payment(loan_amount, rate, term)
    monthly_tax = property_tax / 12
    monthly_ins = home_ins / 12
    total = monthly_pi + monthly_tax + monthly_ins + monthly_pmi + hoa

    return jsonify({
        "loan_amount": round(loan_amount, 2),
        "interest_rate": round(rate, 3),
        "monthly_total": round(total, 2),
        "breakdown": {
            "Principal & Interest": round(monthly_pi, 2),
            "Property Tax": round(monthly_tax, 2),
            "Insurance": round(monthly_ins, 2),
            "PMI": round(monthly_pmi, 2),
            "HOA": round(hoa, 2)
        }
    })


if __name__ == "__main__":
    app.run(debug=True)
