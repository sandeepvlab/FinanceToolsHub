from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# --- Example: fetching rates from a legal public API or placeholder ---
def get_mortgage_rates():
    # Placeholder static rates; replace with legal API fetch if needed
    return {
        "30_yr_fixed": 6.23,
        "20_yr_fixed": 5.85,
        "15_yr_fixed": 5.22,
        "10_yr_fixed": 4.90,
        "5_1_ARM": 5.74
    }

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    chart_data = None
    rates = get_mortgage_rates()

    if request.method == "POST":
        try:
            home_value = float(request.form.get("home_value", 0))
            down_type = request.form.get("down_type", "$")
            down_payment_val = float(request.form.get("down_payment", 0))
            
            # Calculate down payment in dollars
            if down_type == "%":
                down_payment = home_value * down_payment_val / 100
            else:
                down_payment = down_payment_val

            loan_type = request.form.get("loan_type", "Conventional")
            loan_term = int(request.form.get("loan_term", 30))
            interest_rate = float(request.form.get("interest_rate", 5))
            property_tax = float(request.form.get("property_tax", 0))
            home_ins = float(request.form.get("home_ins", 0))
            hoa = float(request.form.get("hoa", 0))

            # PMI calculation if down <20%
            pmi_rate = 0
            pmi_msg = ""
            if down_payment / home_value < 0.2:
                pmi_rate = 0.0075  # typical 0.75% annual
                pmi_msg = "Your down payment is less than 20%, PMI applies (~0.5-1.5% of loan amount per year)."

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
            monthly_pmi = loan_amount * pmi_rate / 12
            total_monthly = monthly_pi + monthly_tax + monthly_ins + monthly_pmi + hoa

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
                "pmi_msg": pmi_msg,
                "loan_type": loan_type
            }

        except Exception as e:
            result = {"error": str(e)}

    return render_template("index.html", result=result, chart_data=chart_data, rates=rates)
    

if __name__ == "__main__":
    app.run(debug=True)
