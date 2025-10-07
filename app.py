import os
import logging
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__, template_folder="templates")
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use env var if available; fallback to your provided key if inserted here
FRED_API_KEY = os.environ.get("FRED_API_KEY", "14290ebba38ce5ea815d8529a6242114")

FRED_SERIES = {
    30: "MORTGAGE30US",
    15: "MORTGAGE15US",
    "ARM_5": "MORTGAGE5US"
}


def fetch_fred_latest(series_id):
    """Return latest numeric observation for given FRED series or None."""
    try:
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1
        }
        resp = requests.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=8)
        resp.raise_for_status()
        j = resp.json()
        obs = j.get("observations") or []
        if not obs:
            return None
        val = obs[0].get("value")
        # FRED sometimes returns "." to indicate missing
        if val in (None, ".", "", "NaN"):
            return None
        return float(val)
    except Exception as e:
        logger.warning("FRED fetch failed for %s: %s", series_id, e)
        return None


def get_interest_rate_for(loan_type: str, loan_term: int):
    """
    Return percentage (ex: 6.25) based on loan type/term using FRED where possible.
    """

    if loan_type == "Conventional":
        # exact series if available
        if loan_term in (15, 30):
            r = fetch_fred_latest(FRED_SERIES.get(loan_term))
            if r is not None:
                return round(r, 3)
        # try interpolation/extrapolation
        r30 = fetch_fred_latest(FRED_SERIES.get(30)) or None
        r15 = fetch_fred_latest(FRED_SERIES.get(15)) or None
        if r30 is not None and r15 is not None:
            if loan_term == 20:
                # linear between 15 and 30
                return round(r15 + (r30 - r15) * (5.0 / 15.0), 3)
            if loan_term == 10:
                # extrapolate a bit from 15-year
                return round(max(0.0, r15 - 0.3), 3)
        # fallback defaults
        fallback_map = {30: 6.8, 20: 6.5, 15: 6.0, 10: 5.5}
        return fallback_map.get(loan_term, 6.8)

    # ARM
    if loan_type == "ARM":
        r5 = fetch_fred_latest(FRED_SERIES.get("ARM_5")) or 6.2
        if loan_term == 5:
            return round(r5, 3)
        if loan_term == 3:
            return round(max(0.9 * r5, r5 - 0.25), 3)
        if loan_term == 7:
            return round(min(1.02 * r5, r5 + 0.25), 3)
        if loan_term == 10:
            return round(min(1.05 * r5, r5 + 0.5), 3)
        return round(r5, 3)

    return 6.8


def compute_pmi_percent(down_payment_percent: float) -> float:
    """Heuristic PMI annual % based on down payment percent."""
    dp = down_payment_percent
    if dp >= 20:
        return 0.0
    if dp >= 15:
        return 0.35
    if dp >= 10:
        return 0.65
    return 0.95


def estimate_home_insurance_annual(zipcode: str, home_value: float) -> float:
    """
    Light heuristic estimate of home insurance based on home value and zipcode prefix.
    This is NOT a substitute for a real insurance quote; can be replaced with a paid API.
    """
    try:
        prefix = int(str(zipcode).strip()[:2])
    except Exception:
        prefix = 99
    base_rate = 0.003  # 0.3% of home value baseline
    if prefix < 20:
        modifier = 1.05
    elif prefix < 50:
        modifier = 0.95
    else:
        modifier = 1.0
    return round(home_value * base_rate * modifier, 2)


def monthly_payment(principal: float, annual_rate_percent: float, years: int) -> float:
    """Standard loan payment formula (P&I)."""
    if principal <= 0 or years <= 0:
        return 0.0
    r = annual_rate_percent / 100.0 / 12.0
    n = years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


@app.route("/", methods=["GET"])
def index():
    # Serve page; front-end will query /_rate_hint and /calculate
    return render_template("index.html")


@app.route("/_rate_hint", methods=["GET"])
def rate_hint():
    """Return a single rate for the requested loan_type & loan_term."""
    loan_type = request.args.get("loan_type", "Conventional")
    try:
        loan_term = int(request.args.get("loan_term", 30))
    except Exception:
        loan_term = 30
    rate = get_interest_rate_for(loan_type, loan_term)
    return jsonify({"rate": rate})


@app.route("/calculate", methods=["POST"])
def calculate():
    """
    Expects JSON body with:
      zipcode, home_value, down_payment_value, down_payment_type ('%' or '$'),
      loan_type, loan_term, property_tax, pmi (optional override), home_ins (optional), hoa
    Returns JSON: loan_amount, interest_rate, monthly_total, breakdown
    """
    data = request.get_json(force=True)

    zipcode = str(data.get("zipcode", "")).strip()
    home_value = float(data.get("home_value") or 0.0)
    down_value = float(data.get("down_payment_value") or 0.0)
    down_type = data.get("down_payment_type", "%")
    loan_type = data.get("loan_type", "Conventional")
    try:
        loan_term = int(data.get("loan_term", 30))
    except Exception:
        loan_term = 30
    property_tax = float(data.get("property_tax") or 0.0)
    pmi_input = data.get("pmi")  # optional override
    home_ins_input = data.get("home_ins")
    hoa = float(data.get("hoa") or 0.0)

    # compute down payment (absolute) and percent
    if down_type == "%":
        down_amount = round(home_value * (down_value / 100.0), 2)
        down_percent = down_value
    else:
        down_amount = round(down_value, 2)
        down_percent = round((down_amount / home_value) * 100.0, 3) if home_value > 0 else 0.0

    loan_amount = max(0.0, round(home_value - down_amount, 2))

    # interest rate from FRED (national series) based on loan type & term
    interest_rate = get_interest_rate_for(loan_type, loan_term)

    # insurance annual
    if home_ins_input in (None, "", 0):
        home_ins_annual = estimate_home_insurance_annual(zipcode, home_value)
    else:
        home_ins_annual = float(home_ins_input)

    # pmi percent
    if pmi_input not in (None, "", 0):
        try:
            pmi_percent = float(pmi_input)
        except Exception:
            pmi_percent = compute_pmi_percent(down_percent)
    else:
        pmi_percent = compute_pmi_percent(down_percent)

    monthly_pi = monthly_payment(loan_amount, interest_rate, loan_term)
    monthly_property_tax = property_tax / 12.0
    monthly_insurance = home_ins_annual / 12.0
    monthly_pmi = 0.0
    if pmi_percent > 0:
        monthly_pmi = (loan_amount * (pmi_percent / 100.0)) / 12.0

    monthly_total = round(monthly_pi + monthly_property_tax + monthly_insurance + monthly_pmi + hoa, 2)

    chart_breakdown = {
        "Principal & Interest": round(monthly_pi, 2),
        "Property Tax": round(monthly_property_tax, 2),
        "Insurance": round(monthly_insurance, 2),
        "PMI": round(monthly_pmi, 2),
        "HOA": round(hoa, 2)
    }

    result = {
        "zipcode": zipcode,
        "home_value": round(home_value, 2),
        "down_amount": down_amount,
        "down_percent": round(down_percent, 3),
        "loan_amount": loan_amount,
        "interest_rate": round(interest_rate, 3),
        "monthly_total": monthly_total,
        "pmi_percent": round(pmi_percent, 3),
        "chart": chart_breakdown
    }
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
