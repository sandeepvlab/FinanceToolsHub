from flask import Flask, render_template, request
import requests

app = Flask(__name__)

# --- FRED API configuration ---
FRED_API_KEY = "YOUR_FRED_API_KEY"  # replace with your FRED API key
FRED_SERIES = {
    "30_yr_fixed": "MORTGAGE30US",
    "15_yr_fixed": "MORTGAGE15US",
    "5_1_ARM": "MORTGAGE5US"
}

def get_fred_rate(series_id):
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    obs = data.get("observations", [])
    if obs:
        return float(obs[0].get("value"))
    return None

def get_mortgage_rates():
    return {key: get_fred_rate(series) for key, series in FRED_SERIES.items()}

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    chart_data = None
    rates = None
    pmi_message = ""

    if request.method == "POST":
        try:
            zipcode = request.form.get("zipcode", "84044")
            home_value = float(request.form.get("home_value", 0))
            down_type = request.form.get("down_type", "amount")  # "amount" or "percent"
            down_value = float(request.form.get("down_payment", 0))
            loan_type = request.form.get("loan_type", "conventional")
            loan_term = int(request.form.get("loan_term", 30))
            interest_rate = float(request.form.get("interest_rate", 0))
            property_tax = float(request.form.get("property_tax", 0))
            home_ins = float(request.form.get("home_ins", 0))
            hoa = float(request.form.get("hoa", 0))

            # --- Down Payment Calculation ---
            if down_type == "percent":
                down_payment = home_value * (down_value / 100)
            else:
                down_payment = down_value

            # --- Fetch live rates from FRED ---
            rates = get_mortgage_rates()
            if interest_rate == 0:
                if loan_type.lower() == "conventional":
                    # pick closest fixed rate
                    if loan_term >= 30:
                        interest_rate = rates.get("30_yr_fixed", 6.0)
                    elif loan_term >= 15:
                        interest_rate = rates.get("15_yr_fixed", 5.5)
                    else:
                        interest_rate = rates.get("15_yr_fixed", 5.5)
                else:
                    interest_rate = rates.get("5_1_ARM", 5.7)

            # --- Loan Calculation ---
            loan_amount = home_value - down_payment
            monthly_rate = interest_rate / 100 / 12
            months = loan_term * 12

            if monthly_rate > 0:
                monthly_pi = loan_amount * (monthly_rate * (1 + monthly_rate)**months) / ((1 + monthly_rate)**months - 1)
            else:
                monthly_pi = loan_amount / months

            monthly_tax = property_tax / 12
            monthly_ins = home_ins / 12

            # --- PMI Calculation ---
            ltv = loan_amount / home_value
            monthly_pmi = 0
            if ltv > 0.8:
                monthly_pmi = loan_amount * 0.0075 / 12
                pmi_message = (
                    "Your down payment is less than 20%, so you will be required to pay "
                    "Private Mortgage Insurance (PMI). Estimated PMI typically ranges "
                    "from 0.5% to 1.5% of your loan amount per year."
                )

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
