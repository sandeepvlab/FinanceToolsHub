from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# === FRED API Key ===
FRED_API_KEY = "14290ebba38ce5ea815d8529a6242114"

def get_mortgage_rates():
    """
    Fetch 30-year fixed and 5/1 ARM mortgage rates from FRED
    """
    rates = {"30_yr_fixed": None, "5_1_ARM": None}
    try:
        url_fixed = f"https://api.stlouisfed.org/fred/series/observations?series_id=MORTGAGE30US&api_key={FRED_API_KEY}&file_type=json&frequency=w&limit=1"
        url_arm = f"https://api.stlouisfed.org/fred/series/observations?series_id=MORTGAGE5US&api_key={FRED_API_KEY}&file_type=json&frequency=w&limit=1"

        res_fixed = requests.get(url_fixed)
        res_arm = requests.get(url_arm)
        res_fixed.raise_for_status()
        res_arm.raise_for_status()

        data_fixed = res_fixed.json()
        data_arm = res_arm.json()

        rates["30_yr_fixed"] = float(data_fixed['observations'][-1]['value'])
        rates["5_1_ARM"] = float(data_arm['observations'][-1]['value'])

    except Exception as e:
        print("Error fetching FRED rates:", e)
        rates["30_yr_fixed"] = 6.5  # fallback default
        rates["5_1_ARM"] = 5.8       # fallback default

    return rates


def calculate_pmi(down_payment_percent):
    """
    PMI logic:
    Typically 0.3% - 1.5% if downpayment < 20%
    """
    if down_payment_percent >= 20:
        return 0.0
    else:
        # Linear scale: higher PMI for smaller downpayment
        return round(0.75 + (20 - down_payment_percent) * 0.05, 2)


@app.route("/", methods=["GET", "POST"])
def index():
    rates = get_mortgage_rates()
    result = {}

    if request.method == "POST":
        price = float(request.form.get("price", 0))
        down_payment_val = float(request.form.get("down_payment", 0))
        dp_type = request.form.get("dp_type", "%")
        loan_term = int(request.form.get("loan_term", 30))
        rate_type = request.form.get("rate_type", "30_yr_fixed")

        # Convert DP $ -> %
        if dp_type == "$":
            down_payment_percent = (down_payment_val / price) * 100
        else:
            down_payment_percent = down_payment_val

        loan_amount = price * (1 - down_payment_percent / 100)
        rate = rates.get(rate_type, 6.5) / 100

        # PMI
        pmi = calculate_pmi(down_payment_percent)

        # Monthly mortgage calculation
        n_payments = loan_term * 12
        if rate > 0:
            monthly_payment = loan_amount * (rate/12 * (1 + rate/12)**n_payments) / ((1 + rate/12)**n_payments - 1)
        else:
            monthly_payment = loan_amount / n_payments

        monthly_payment += loan_amount * pmi / 12 / 100  # Add PMI

        result = {
            "loan_amount": round(loan_amount, 2),
            "monthly_payment": round(monthly_payment, 2),
            "pmi": round(pmi, 2),
            "down_payment_percent": round(down_payment_percent, 2),
            "rates": rates
        }

    return render_template("index.html", result=result, rates=rates)


if __name__ == "__main__":
    app.run(debug=True)
