from flask import Flask, render_template, request, jsonify
import requests
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----- CONFIG -----
FRED_API_KEY = "14290ebba38ce5ea815d8529a6242114"
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"

# public FRED series used
FRED_SERIES = {
    30: "MORTGAGE30US",
    15: "MORTGAGE15US",
    "ARM_5": "MORTGAGE5US"
}


# ----- Utilities -----
def fetch_fred_latest(series_id):
    """Return latest numeric observation for series_id or None."""
    try:
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1
        }
        r = requests.get(FRED_API_URL, params=params, timeout=8)
        r.raise_for_status()
        j = r.json()
        obs = j.get("observations") or []
        if not obs:
            return None
        val = obs[0].get("value")
        # FRED sometimes returns "." to mean missing - handle it
        if val is None or val == "." or val == "" or val.lower() == "nan":
            return None
        return float(val)
    except Exception as e:
        logger.warning("FRED fetch failed for %s: %s", series_id, e)
        return None


def get_interest_rate_for(loan_type: str, loan_term: int):
    """
    Return an annual rate (percent) based on loan_type and loan_term.
    Uses FRED series where available and reasonable fallbacks / interpolation.
    """
    loan_type = loan_type or "Conventional"
    # Conventional
    if loan_type == "Conventional":
        # If exact series exists (30,15) use it
        if loan_term in FRED_SERIES:
            v = fetch_fred_latest(FRED_SERIES[loan_term])
            if v is not None:
                return round(v, 3)
        # interpolate if possible between 15 & 30 for 20 & 10
        r30 = fetch_fred_latest(FRED_SERIES.get(30))
        r15 = fetch_fred_latest(FRED_SERIES.get(15))
        if r30 is not None and r15 is not None:
            if loan_term == 20:
                return round(r15 + (r30 - r15) * (5.0 / 15.0), 3)
            if loan_term == 10:
                # linear extrapolation toward 15->10
                return round(r15 - (r15 - ((r30 + r15) / 2)) * 0.5, 3)
        # final fallbacks
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

    # default safe value
    return 6.8


def compute_pmi_percent(down_percent: float) -> float:
    """Simple PMI heuristic (annual %). You can tune this later."""
    if down_percent >= 20:
        return 0.0
    if down_percent >= 15:
        return 0.35
    if down_percent >= 10:
        return 0.65
    return 0.95


def estimate_home_insurance_annual(zipcode: str, home_value: float) -> float:
    """
    Cheap heuristic estimate for home insurance by home value and zipcode prefix.
    Replace with a real API if you want market-accurate numbers.
    """
    base_rate = 0.003  # 0.3% annual
    try:
        prefix = int(str(zipcode).strip()[:2])
        if prefix < 20:
            modifier = 1.05
        elif prefix < 50:
            modifier = 0.95
        else:
            modifier = 1.0
    except Exception:
        modifier = 1.0
    return round(home_value * base_rate * modifier, 2)


def monthly_payment(principal: float, annual_rate_percent: float, years: int) -> float:
    """Standard mortgage monthly PI payment."""
    if principal <= 0 or years <= 0:
        return 0.0
    r = annual_rate_percent / 100.0 / 12.0
    n = years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


# ----- Routes -----
@app.route("/", methods=["GET"])
def index():
    # Serve page; frontend will call /_rate_hint and /calculate
    return render_template("index.html")


@app.route("/_rate_hint")
def rate_hint():
    """
    Return real-time rate for the requested loan type & term.
    Query params: loan_type (Conventional|ARM), loan_term (int), zipcode (optional), use_zip (1|0)
    Note: FRED rates are national; zipcode doesn't change Freddie Mac series but we accept it for UX toggles.
    """
    lt = request.args.get("loan_type", "Conventional")
    try:
        term = int(request.args.get("loan_term", 30))
    except Exception:
        term = 30
    rate = get_interest_rate_for(lt, term)
    return jsonify({"rate": rate})


@app.route("/calculate", methods=["POST"])
def calculate():
    """
    Expects JSON payload with keys:
      zipcode, use_zip (bool), home_value, down_payment_value, down_payment_type ('%' or '$'),
      loan_type, loan_term, property_tax, pmi_override (optional), home_ins (optional), hoa
    Returns full JSON breakdown including chart_data.
    """
    data = request.get_json(force=True)
    # Robust parsing with defaults
    zipcode = str(data.get("zipcode", "")).strip()
    use_zip = bool(data.get("use_zip", True))

    home_value = float(data.get("home_value") or 0.0)
    down_value = float(data.get("down_payment_value") or 0.0)
    down_type = data.get("down_payment_type", "%")
    loan_type = data.get("loan_type", "Conventional")
    loan_term = int(data.get("loan_term") or 30)
    property_tax = float(data.get("property_tax") or 0.0)
    pmi_override = data.get("pmi")  # may be None
    home_ins_input = data.get("home_ins")  # may be None/empty
    hoa = float(data.get("hoa") or 0.0)

    # DOWN PAYMENT -> absolute and percent
    if down_type == "%":
        down_amount = round(home_value * down_value / 100.0, 2)
        down_percent = down_value
    else:
        down_amount = round(down_value, 2)
        down_percent = round((down_amount / home_value) * 100.0, 2) if home_value > 0 else 0.0

    loan_amount = max(0.0, round(home_value - down_amount, 2))

    # Interest rate resolved by loan_type & loan_term (we ignore zipcode for FRED lookup because FRED is national)
    interest_rate = get_interest_rate_for(loan_type, loan_term)

    # Home insurance annual
    if home_ins_input is None or str(home_ins_input).strip() == "":
        home_ins_annual = estimate_home_insurance_annual(zipcode, home_value)
    else:
        home_ins_annual = float(home_ins_input)

    # PMI percent
    if pmi_override not in (None, "", 0):
        try:
            pmi_percent = float(pmi_override)
        except Exception:
            pmi_percent = compute_pmi_percent(down_percent)
    else:
        pmi_percent = compute_pmi_percent(down_percent)

    # Monthly numbers
    monthly_pi = monthly_payment(loan_amount, interest_rate, loan_term)
    monthly_property_tax = property_tax / 12.0
    monthly_insurance = home_ins_annual / 12.0
    monthly_pmi = 0.0
    if pmi_percent > 0:
        monthly_pmi = (loan_amount * (pmi_percent / 100.0)) / 12.0

    monthly_total = round(monthly_pi + monthly_property_tax + monthly_insurance + monthly_pmi + hoa, 2)

    chart_data = {
        "Principal & Interest": round(monthly_pi, 2),
        "Property Tax": round(monthly_property_tax, 2),
        "Insurance": round(monthly_insurance, 2),
        "PMI": round(monthly_pmi, 2),
        "HOA": round(hoa, 2)
    }

    response = {
        "zipcode": zipcode,
        "use_zip": use_zip,
        "home_value": round(home_value, 2),
        "down_amount": round(down_amount, 2),
        "down_percent": round(down_percent, 3),
        "loan_amount": round(loan_amount, 2),
        "interest_rate": round(interest_rate, 3),
        "monthly_pi": round(monthly_pi, 2),
        "monthly_property_tax": round(monthly_property_tax, 2),
        "monthly_insurance": round(monthly_insurance, 2),
        "monthly_pmi": round(monthly_pmi, 2),
        "hoa": round(hoa, 2),
        "monthly_total": monthly_total,
        "pmi_percent": round(pmi_percent, 3),
        "chart_data": chart_data
    }
    return jsonify(response)


if __name__ == "__main__":
    # Production: remove debug=True
    app.run(debug=True, host="0.0.0.0", port=5000)
