from flask import Flask, render_template, request
import requests
import math

app = Flask(__name__)

# FRED API key (your valid key)
FRED_API_KEY = "14290ebba38ce5ea815d8529a6242114"

# FRED Series IDs for rates
FRED_SERIES = {
    "conventional": "MORTGAGE30US",  # 30-Year Fixed
    "arm": "MORTGAGE5US"             # 5/1-Year ARM
}


def fetch_fred_rate(series_id):
    """Fetch latest rate from FRED API"""
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&sort_order=desc&limit=1"
        )
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return float(data["observations"][-1]["value"])
    except Exception as e:
        print("Error fetching FRED rate:", e)
        return None


def calculate_mortgage(principal, annual_rate, years):
    """Calculate monthly mortgage payment"""
    r = annual_rate / 100 / 12
    n = years * 12
    return principal * r * ((1 + r) ** n) / ((1 + r) ** n - 1)


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    chart_data = None
    rates = {}

    # Fetch latest mortgage rates
    rates["conventional"] = fetch_fred_rate(FRED_SERIES["conventional"]) or 6.75
    rates["arm"] = fetch_fred_rate(FRED_SERIES["arm"]) or 6.25

    if request.method == "POST":
        try:
            home_price = float(request.form["home_price"])
            down_payment = float(request.form["down_payment"])
            loan_term = int(request.form["loan_term"])
            zipcode = request.form.get("zipcode", "")
            interest_type = request.form["interest_type"]

            # Auto-select interest rate
            rate = rates["conventional"] if interest_type == "conventional" else rates["arm"]

            loan_amount = home_price - down_payment
            down_percent = (down_payment / home_price) * 100

            # Auto-calc PMI if < 20%
            pmi_rate = 0.75 if down_percent < 20 else 0
            monthly_pmi = (loan_amount * (pmi_rate / 100)) / 12

            monthly_payment = calculate_mortgage(loan_amount, rate, loan_term)
            total_payment = monthly_payment * loan_term * 12 + (monthly_pmi * loan_term * 12)
            total_interest = total_payment - loan_amount

            result = {
                "monthly_payment": round(monthly_payment + monthly_pmi, 2),
                "total_payment": round(total_payment, 2),
                "total_interest": round(total_interest, 2),
                "pmi": round(monthly_pmi, 2),
                "zipcode": zipcode,
                "rate": rate
            }

            # For chart display
            chart_data = {
                "Principal": loan_amount,
                "Interest": total_interest,
                "PMI": monthly_pmi * loan_term * 12,
            }

        except Exception as e:
            result = {"error": str(e)}

    return render_template("index.html", result=result, rates=rates, chart_data=chart_data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
