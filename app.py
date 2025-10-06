from flask import Flask, render_template, request, jsonify
import requests
import math
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== CONFIG ==========
# Replace with your FRED API key
FRED_API_KEY = "14290ebba38ce5ea815d8529a6242114"

# Map (loan term -> FRED series) where available
FRED_SERIES = {
    30: "MORTGAGE30US",   # 30-Year FRM
    15: "MORTGAGE15US",   # 15-Year FRM
    # no official 20yr/10yr series - we'll approximate when needed
    # ARM: use 5/1 ARM series as central reference
    "ARM_5": "MORTGAGE5US"
}


# ========== UTIL: FRED FETCH ==========
def fetch_fred_latest(series_id):
    """Fetch latest observation value for a FRED series id. Returns float or None."""
    try:
        url = (
            "https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        )
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        j = r.json()
        obs = j.get("observations") or []
        if not obs:
            return None
        val = obs[0].get("value")
        return float(val)
    except Exception as e:
        logger.warning("FRED fetch failed for %s: %s", series_id, e)
        return None


# ========== UTIL: Estimated Insurance ==========
def estimate_home_insurance_annual(zipcode: str, home_value: float) -> float:
    """
    Return an estimated annual homeowner insurance based on home value and zipcode prefix.
    This is only an estimate. Replace with a real insurance API for production (Zillow/InsureTech).
    """
    base_rate = 0.003  # 0.3% of home value as baseline
    # Slight regional modifier by zipcode prefix (simple heuristic)
    try:
        prefix = int(str(zipcode).strip()[:2])
        if prefix in range(0, 20):  # example: northeast-ish
            modifier = 1.05
        elif prefix in range(20, 50):  # midwest / central
            modifier = 0.95
        else:
            modifier = 1.00
    except Exception:
        modifier = 1.0
    return round(home_value * base_rate * modifier, 2)


# ========== UTIL: PMI ==========
def compute_pmi_percent(down_payment_percent: float) -> float:
    """
    Estimate PMI % (annual) based on down payment percent.
    Typical assumptions (approx):
      >= 20% => 0
      15-19.99% => 0.25 - 0.50
      10-14.99% => 0.5 - 0.8
      < 10% => 0.8 - 1.2
    Returns percentage (e.g. 0.75 => 0.75% p.a.)
    """
    dp = down_payment_percent
    if dp >= 20:
        return 0.0
    if dp >= 15:
        return 0.35
    if dp >= 10:
        return 0.65
    return 0.95


# ========== UTIL: Interest selection ==========
def get_interest_rate_for(loan_type: str, loan_term: int, zipcode: str):
    """
    Determine appropriate interest rate based on loan type & term.
    - For Conventional fixed terms: try to fetch from FRED when possible
    - For ARM terms: use MORTGAGE5US for 5/1 ARM; approximate for others
    Returns percentage (e.g. 6.25)
    """
    # Try exact FRED if present
    if loan_type == "Conventional":
        if loan_term in FRED_SERIES:
            rate = fetch_fred_latest(FRED_SERIES[loan_term])
            if rate is not None:
                return rate
        # interpolate fallback: try 30 and 15 if available
        r30 = fetch_fred_latest(FRED_SERIES.get(30))
        r15 = fetch_fred_latest(FRED_SERIES.get(15))
        if r30 and r15:
            # linear interpolation between 15 and 30-year for 20 & 10
            if loan_term == 20:
                return round(r15 + (r30 - r15) * (5 / 15), 2)  # 5/15 from 15->30
            if loan_term == 10:
                return round(r15 - (r15 - (r30 - (r30 - r15) * 0.2)), 2) if r15 else r30
        # last fallback: safe defaults
        fallback_map = {30: 6.8, 20: 6.5, 15: 6.0, 10: 5.5}
        return fallback_map.get(loan_term, 6.8)

    # ARM
    if loan_type == "ARM":
        # prefer 5/1 ARM series as best-known public series
        if loan_term == 5:
            r = fetch_fred_latest(FRED_SERIES.get("ARM_5"))
            if r is not None:
                return r
            return 6.2  # fallback
        # approximate other ARMs relative to 5/1 ARM
        r5 = fetch_fred_latest(FRED_SERIES.get("ARM_5")) or 6.2
        if loan_term == 3:
            return round(max(0.9 * r5, r5 - 0.25), 2)
        if loan_term == 7:
            return round(min(1.02 * r5, r5 + 0.25), 2)
        if loan_term == 10:
            return round(min(1.05 * r5, r5 + 0.5), 2)
        # default ARM fallback
        return r5

    # default
    return 6.8


# ========== UTIL: monthly PI calc ==========
def monthly_payment(principal: float, annual_rate_percent: float, years: int) -> float:
    if principal <= 0 or years <= 0:
        return 0.0
    r = annual_rate_percent / 100.0 / 12.0
    n = years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


# ========== ROUTES ==========
@app.route("/", methods=["GET", "POST"])
def index():
    # defaults
    context = {
        "result": None,
        "chart_data": {},   # always present to avoid Jinja undefined
        "rates_sample": {}, # show what we used
    }

    # On load, we can show a preview sample rate (30yr & 5/1)
    sample_30 = get_interest_rate_for("Conventional", 30, "")
    sample_5 = get_interest_rate_for("ARM", 5, "")
    context["rates_sample"] = {"30yr": sample_30, "5_1_ARM": sample_5}

    if request.method == "POST":
        # Read form values (fields preserved exactly per your spec)
        zipcode = request.form.get("zipcode", "").strip()
        home_value = float(request.form.get("home_value") or 0)
        down_value = float(request.form.get("down_payment_value") or 0)
        down_type = request.form.get("down_payment_type", "%")  # '%' or '$'
        loan_type = request.form.get("loan_type", "Conventional")  # Conventional or ARM
        loan_term = int(request.form.get("loan_term", 30))
        property_tax = float(request.form.get("property_tax") or 0)
        pmi_input = request.form.get("pmi")  # optional override percent
        home_ins = request.form.get("home_ins")
        hoa = float(request.form.get("hoa") or 0)

        # Determine down payment in $
        if down_type == "%":
            down_payment_amount = round(home_value * (down_value / 100.0), 2)
            down_percent = down_value
        else:
            down_payment_amount = down_value
            down_percent = round((down_payment_amount / home_value) * 100.0, 2) if home_value > 0 else 0.0

        # Loan amount AFTER down payment
        loan_amount_val = max(0.0, round(home_value - down_payment_amount, 2))

        # Interest rate fetch (real time via FRED where possible)
        interest_rate = get_interest_rate_for("Conventional" if loan_type == "Conventional" else "ARM", loan_term, zipcode)

        # Property tax & home insurance: convert yearly -> monthly later
        # If user typed home_ins, use it; else estimate via zipcode/home value
        if home_ins is None or home_ins == "":
            home_ins_annual = estimate_home_insurance_annual(zipcode, home_value)
        else:
            home_ins_annual = float(home_ins)

        # Determine PMI %
        if pmi_input and pmi_input != "":
            try:
                pmi_percent = float(pmi_input)
            except Exception:
                pmi_percent = compute_pmi_percent(down_percent)
        else:
            pmi_percent = compute_pmi_percent(down_percent)

        # Monthly calculations
        monthly_pi = monthly_payment(loan_amount_val, interest_rate, loan_term)
        monthly_property_tax = property_tax / 12.0
        monthly_insurance = home_ins_annual / 12.0
        monthly_pmi_amount = 0.0
        if pmi_percent > 0:
            monthly_pmi_amount = (loan_amount_val * (pmi_percent / 100.0)) / 12.0

        monthly_total = round(monthly_pi + monthly_property_tax + monthly_insurance + monthly_pmi_amount + hoa, 2)

        # Build chart data (principal/interest approximated using monthly_pi break)
        chart_data = {
            "Principal & Interest": round(monthly_pi, 2),
            "Property Tax": round(monthly_property_tax, 2),
            "Insurance": round(monthly_insurance, 2),
            "PMI": round(monthly_pmi_amount, 2),
            "HOA": round(hoa, 2)
        }

        context["result"] = {
            "zipcode": zipcode,
            "home_value": round(home_value, 2),
            "down_payment_amount": down_payment_amount,
            "down_percent": down_percent,
            "loan_amount": loan_amount_val,
            "interest_rate": round(interest_rate, 3),
            "monthly_pi": round(monthly_pi, 2),
            "monthly_property_tax": round(monthly_property_tax, 2),
            "monthly_insurance": round(monthly_insurance, 2),
            "monthly_pmi": round(monthly_pmi_amount, 2),
            "hoa": round(hoa, 2),
            "monthly_total": monthly_total,
            "loan_type": loan_type,
            "loan_term": loan_term,
            "pmi_percent": round(pmi_percent, 3)
        }
        context["chart_data"] = chart_data
        context["rates_sample"] = {"30yr": sample_30, "5_1_ARM": sample_5}

    # Always pass these variables so template doesn't error
    return render_template("index.html",
                           result=context.get("result"),
                           chart_data=context.get("chart_data", {}),
                           rates_sample=context.get("rates_sample"))
