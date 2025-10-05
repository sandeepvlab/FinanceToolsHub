from flask import Flask, render_template, request
import requests
import random

app = Flask(__name__)

# FRED API endpoint for 30-year fixed mortgage rate
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
API_KEY = "YOUR_FRED_API_KEY"  # Replace with your FRED API key

def get_mortgage_rate():
    params = {
        'series_id': 'MORTGAGE30US',
        'api_key': API_KEY,
        'file_type': 'json',
        'frequency': 'w',  # Weekly data
        'limit': 1,  # Get the most recent observation
    }
    response = requests.get(FRED_API_URL, params=params)
    data = response.json()
    if data['observations']:
        return float(data['observations'][0]['value'])
    else:
        return 6.5  # Default rate if API fails

def get_mortgage_rates(zipcode):
    random.seed(int(zipcode) if zipcode.isdigit() else 1000)
    return {
        "30_yr_fixed": round(random.uniform(5.5, 6.5), 2),
        "20_yr_fixed": round(random.uniform(5.3, 6.2), 2),
        "15_yr_fixed": round(random.uniform(4.7, 5.5), 2),
        "10_yr_fixed": round(random.uniform(4.5, 5.0), 2),
        "ARM_1": round(random.uniform(5.0, 6.0), 2),
        "ARM_3": round(random.uniform(5.0, 6.0), 2),
        "ARM_5": round(random.uniform(5.0, 6.0), 2),
        "ARM_7": round(random.uniform(5.0, 6.0), 2),
        "ARM_10": round(random.uniform(5.0, 6.0), 2)
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
            down_payment_value = float(request.form.get("down_payment_value", 0))
            down_payment_type = request.form.get("down_payment_type", "$")
            loan_type = request.form.get("loan_type", "Conventional")
            loan_term = request.form.get("loan_term", 30)
            property_tax = float(request.form.get("property_tax", 0))
            home_ins = float(request.form.get("home_ins", 0))
            pmi_input = float(request.form.get("pmi", 0))
            hoa = float(request.form.get("hoa", 0))

            rates = get_mortgage_rates(zipcode)

            # Calculate down payment if % selected
            if down_payment_type == "%":
                down_payment = home_value * down_payment_value / 100
            else:
                down_payment = down_payment_value

            loan_amount = home_value - down_payment

            # Determine interest rate based on loan type and term
            if loan_type == "Conventional":
                loan_term = int(loan_term)
                interest_rate = rates.get(f"{loan_term}_yr_fixed", 6.0)
            elif loan_type == "ARM":
                interest_rate = rates.get(f"ARM_{loan_term}", 6.0)
            else:
                interest_rate = 6.0

            # Principal & Interest
            monthly_rate = interest_rate / 100 / 12
            months = int(loan_term) * 12
            if monthly_rate > 0:
                monthly_pi = loan_amount * (monthly_rate * (1 + monthly_rate)**months) / ((1 + monthly_rate)**months - 1)
            else:
                monthly_pi = loan_amount / months

            # PMI: if down payment <20%, estimate 0.75% yearly
            ltv = loan_amount / home_value
            if ltv > 0.8:
                monthly_pmi = loan_amount * 0.75 / 100 / 12
                pmi_message = "Down payment <20%, PMI estimated at 0.75% of loan amount per year."
            else:
                monthly_pmi = 0
                pmi_message = None

            monthly_tax = property_tax / 12
            monthly_ins = home_ins / 12
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
                "zipcode": zipcode,
                "rates": rates,
                "pmi_message": pmi_message
            }

        except Exception as e:
            result = {"error": str(e)}

    return render_template("index.html", result=result, chart_data=chart_data, rates=rates)

if __name__ == "__main__":
    app.run(debug=True)
