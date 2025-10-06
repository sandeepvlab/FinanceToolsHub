from flask import Flask, render_template, request, jsonify
import requests
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== CONFIG =====
FRED_API_KEY = "14290ebba38ce5ea815d8529a6242114"

# Map (loan term -> FRED series) where available
FRED_SERIES = {
    30: "MORTGAGE30US",
    15: "MORTGAGE15US",
    "ARM_5": "MORTGAGE5US"
}


# ===== UTILITIES =====
def fetch_fred_latest(series_id):
    try:
        url = (
            "https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        )
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        if not obs:
            return None
        return float(obs[0]["value"])
    except Exception as e:
        logger.warning("FRED fetch failed for %s: %s", series_id, e)
        return None


def estimate_home_insurance(zipcode, home_value):
    base_rate = 0.003
    try:
        prefix = int(str(zipcode)[:2])
        if prefix in range(0, 20):
            modifier = 1.05
        elif prefix in range(20, 50):
            modifier = 0.95
        else:
            modifier = 1.0
    except:
        modifier = 1.0
    return round(home_value * base_rate * modifier, 2)


def compute_pmi_percent(down_percent):
    if down_percent >= 20:
        return 0.0
    elif down_percent >= 15:
        return 0.35
    elif down_percent >= 10:
        return 0.65
    return 0.95


def get_interest_rate(loan_type, loan_term):
    if loan_type == "Conventional":
        if loan_term in FRED_SERIES:
            rate = fetch_fred_latest(FRED_SERIES[loan_term])
            if rate: return rate
        # interpolate 20yr/10yr
        r30 = fetch_fred_latest(FRED_SERIES.get(30))
        r15 = fetch_fred_latest(FRED_SERIES.get(15))
        if r30 and r15:
            if loan_term == 20:
                return round(r15 + (r30 - r15) * (5 / 15), 2)
            if loan_term == 10:
                return round(r15 - (r15 - (r30 - (r30 - r15) * 0.2)), 2)
        fallback = {30:6.8, 20:6.5, 15:6.0, 10:5.5}
        return fallback.get(loan_term, 6.8)
    if loan_type == "ARM":
        r5 = fetch_fred_latest(FRED_SERIES.get("ARM_5")) or 6.2
        if loan_term == 3: return round(r5 - 0.25,2)
        if loan_term == 5: return r5
        if loan_term == 7: return round(r5 + 0.25,2)
        if loan_term == 10: return round(r5 + 0.5,2)
    return 6.8


def monthly_payment(principal, annual_rate, years):
    if principal <= 0 or years <= 0: return 0
    r = annual_rate/100/12
    n = years*12
    if r == 0: return principal/n
    return principal*(r*(1+r)**n)/((1+r)**n-1)


# ===== ROUTES =====
@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    chart_data = {}
    if request.method == "POST":
        zipcode = request.form.get("zipcode")
        home_value = float(request.form.get("home_value") or 0)
        down_value = float(request.form.get("down_payment") or 0)
        down_type = request.form.get("down_type", "%")
        loan_type = request.form.get("loan_type")
        loan_term = int(request.form.get("loan_term"))
        property_tax = float(request.form.get("property_tax") or 0)
        home_ins = request.form.get("home_ins")
        hoa = float(request.form.get("hoa") or 0)

        # Down payment
        if down_type == "%":
            down_amount = round(home_value * down_value/100,2)
            down_percent = down_value
        else:
            down_amount = down_value
            down_percent = round(down_amount/home_value*100,2) if home_value>0 else 0

        loan_amount = max(0.0, home_value - down_amount)
        interest_rate = get_interest_rate(loan_type, loan_term)
        home_ins_annual = float(home_ins) if home_ins else estimate_home_insurance(zipcode, home_value)
        pmi_percent = compute_pmi_percent(down_percent)
        monthly_pi = monthly_payment(loan_amount, interest_rate, loan_term)
        monthly_property_tax = property_tax/12
        monthly_ins = home_ins_annual/12
        monthly_pmi = loan_amount*(pmi_percent/100)/12
        monthly_total = round(monthly_pi + monthly_property_tax + monthly_ins + monthly_pmi + hoa,2)

        chart_data = {
            "Principal & Interest": round(monthly_pi,2),
            "Property Tax": round(monthly_property_tax,2),
            "Insurance": round(monthly_ins,2),
            "PMI": round(monthly_pmi,2),
            "HOA": round(hoa,2)
        }

        result = {
            "loan_amount": loan_amount,
            "interest_rate": round(interest_rate,3),
            "monthly_pi": round(monthly_pi,2),
            "monthly_property_tax": round(monthly_property_tax,2),
            "monthly_insurance": round(monthly_ins,2),
            "monthly_pmi": round(monthly_pmi,2),
            "hoa": round(hoa,2),
            "monthly_total": monthly_total,
            "chart_data": chart_data
        }

    return render_template("index.html", result=result)


@app.route("/_rate_hint")
def rate_hint():
    loan_type = request.args.get("loan_type", "Conventional")
    loan_term = int(request.args.get("loan_term", 30))
    rate = get_interest_rate(loan_type, loan_term)
    return jsonify({"rate": rate})


if __name__ == "__main__":
    app.run(debug=True)
