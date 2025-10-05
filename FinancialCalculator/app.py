from flask import Flask, render_template, request, jsonify
import math
import random

app = Flask(__name__)

# --- Simulated API for current mortgage rates based on ZIP ---
def get_mortgage_rates(zipcode):
    # Mock data for demo (you can connect to real APIs like Freddie Mac later)
    random.seed(int(zipcode) if zipcode.isdigit() else 1000)
    return {
        "30_yr_fixed": round(random.uniform(5.5, 6.5), 2),
        "15_yr_fixed": round(random.uniform(4.7, 5.5), 2),
        "5_1_ARM": round(random.uniform(5.3, 6.0), 2)
    }

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    chart_data = None
    rates = None

    if request.method == "POST":
        try:
            zipcode = request.form.get("zipcode", "84044")
            home_value = float(request.form.get("home_value", 0))
            down_payment = float(request.form.get("down_payment", 0))
            interest_rate = float(request.form.get("interest_rate", 0))
            loan_term = int(request.form.get("loan_term", 30))
            property_tax = float(request.form.get("property_tax", 0))
            home_ins = float(request.form.get("home_ins", 0))
            pmi = float(request.form.get("pmi", 0))
            hoa = float(request.form.get("hoa", 0))

            rates = get_mortgage_rates(zipcode)

            # Calculate loan amount
            loan_amount = home_value - down_payment
            monthly_rate = interest_rate / 100 / 12
            months = loan_term * 12

            # Principal & interest
            if monthly_rate > 0:
                monthly_pi = loan_amount * (monthly_rate * (1 + monthly_rate)**months) / ((1 + monthly_rate)**months - 1)
            else:
                monthly_pi = loan_amount / months

            monthly_tax = property_tax / 12
            monthly_ins = home_ins / 12
            monthly_pmi = loan_amount * (pmi / 100 / 12)
            total_monthly = monthly_pi + monthly_tax + monthly_ins + monthly_pmi + hoa

            # Pie chart data
            chart_data = {
                "Principal & Interest": round(monthly_pi, 2),
                "Tax": round(monthly_tax, 2),
                "Insurance": round(monthly_ins, 2),
                "PMI": round(monthly_pmi, 2),
                "HOA": round(hoa, 2)
            }

            result = {
                "loan_amount": round(loan_amount, 2),
                "monthly_payment": round(total_monthly, 2),
                "details": chart_data,
                "zipcode": zipcode,
                "rates": rates
            }

        except Exception as e:
            result = {"error": str(e)}

    return render_template("index.html", result=result, chart_data=chart_data, rates=rates)


if __name__ == "__main__":
    app.run(debug=True)
