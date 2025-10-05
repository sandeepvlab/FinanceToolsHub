from flask import Flask, render_template, request
import requests
import random
from bs4 import BeautifulSoup  # for scraping Freddie Mac site as fallback

app = Flask(__name__)

# FRED API endpoint for 30-year fixed mortgage rate (as fallback or complementary source)
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_API_KEY = "YOUR_FRED_API_KEY"  # Replace with your FRED API key

# Freddie Mac PMMS URL (weekly published) — we’ll try to scrape
FREDDIE_PMMS_URL = "https://www.freddiemac.com/pmms"

def fetch_freddie_rates():
    """Try to get the latest 30-year and 15-year fixed rates from Freddie Mac PMMS by scraping."""
    try:
        resp = requests.get(FREDDIE_PMMS_URL, timeout=10)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        # The PMMS archive page shows e.g. “30-Yr FRM 6.30%” and “15-Yr FRM 5.49%” in a table or section
        # We need to inspect the page structure; here is a heuristic:
        # Look for text like “30-Yr FRM” or “30-Yr FRM” in a <td> or <th> and parse following sibling
        # (You’d need to adjust based on actual DOM structure.)
        rate30 = None
        rate15 = None
        # Simplest: find all table cells, check if they contain "30-Yr" or "30-Year" etc.
        for td in soup.find_all(['td','th']):
            txt = td.get_text(strip=True)
            if '30-Yr' in txt or '30-Year' in txt or '30-Yr FRM' in txt:
                # get next sibling or parent cell
                try:
                    cell = td.find_next_sibling()
                    val = cell.get_text(strip=True).replace('%','')
                    rate30 = float(val)
                except Exception:
                    pass
            if '15-Yr' in txt or '15-Year' in txt or '15-Yr FRM' in txt:
                try:
                    cell = td.find_next_sibling()
                    val = cell.get_text(strip=True).replace('%','')
                    rate15 = float(val)
                except Exception:
                    pass
        return {
            "30yr": rate30,
            "15yr": rate15
        }
    except Exception as e:
        print("Error fetching Freddie rates:", e)
        return {
            "30yr": None,
            "15yr": None
        }

def fetch_fred_rate_30yr():
    params = {
        'series_id': 'MORTGAGE30US',
        'api_key': FRED_API_KEY,
        'file_type': 'json',
        'frequency': 'w',
        'limit': 1
    }
    try:
        resp = requests.get(FRED_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        j = resp.json()
        obs = j.get('observations', [])
        if obs:
            val = obs[0].get('value')
            return float(val)
    except Exception as e:
        print("Error fetching FRED rate:", e)
    return None

def get_mortgage_rates(zipcode):
    """Return a dict of current rates by loan type, using Freddie Mac + fallback + random for ARMs."""
    fr = fetch_freddie_rates()
    rate30 = fr.get("30yr")
    rate15 = fr.get("15yr")

    # Fallback if scraping failed
    if rate30 is None:
        rate30 = fetch_fred_rate_30yr()
    if rate15 is None:
        # we might approximate 15-yr by an offset from 30-yr, or fallback to random
        rate15 = round(random.uniform(4.0, 6.5), 2)

    # Now build a rates dict
    random.seed(int(zipcode) if zipcode.isdigit() else 1000)
    rates = {
        "30_yr_fixed": round(rate30, 2) if rate30 is not None else round(random.uniform(5.5, 7.0), 2),
        "15_yr_fixed": round(rate15, 2),
        # For 20, 10, etc., either interpolate or random fallback
        "20_yr_fixed": round(random.uniform(5.3, 6.5), 2),
        "10_yr_fixed": round(random.uniform(4.5, 5.5), 2),
        # ARMs (1, 3, 5, 7, 10 year)
        "ARM_1": round(random.uniform(5.0, 6.5), 2),
        "ARM_3": round(random.uniform(5.0, 6.5), 2),
        "ARM_5": round(random.uniform(5.0, 6.5), 2),
        "ARM_7": round(random.uniform(5.0, 6.5), 2),
        "ARM_10": round(random.uniform(5.0, 6.5), 2)
    }
    return rates

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    chart_data = None
    rates = None

    if request.method == "POST":
        try:
            zipcode = request.form.get("zipcode", "")
            # If zipcode blank, you might get from client-side via JS and POST it
            home_value = float(request.form.get("home_value", 0))
            down_val = float(request.form.get("down_payment_value", 0))
            down_type = request.form.get("down_payment_type", "%")
            loan_type = request.form.get("loan_type", "Conventional")
            loan_term = int(request.form.get("loan_term", 30))
            property_tax = float(request.form.get("property_tax", 0))
            home_ins = float(request.form.get("home_ins", 0))
            pmi_input = float(request.form.get("pmi", 0))
            hoa = float(request.form.get("hoa", 0))

            rates = get_mortgage_rates(zipcode)

            # Compute down payment $ based on type
            if down_type == "%":
                down_payment = home_value * down_val / 100.0
                dp_percent = down_val
            else:
                down_payment = down_val
                dp_percent = (down_payment / home_value) * 100 if home_value > 0 else 0

            loan_amount = home_value - down_payment

            # Choose interest rate
            interest_rate = None
            if loan_type == "Conventional":
                if loan_term == 30:
                    interest_rate = rates.get("30_yr_fixed")
                elif loan_term == 15:
                    interest_rate = rates.get("15_yr_fixed")
                elif loan_term == 20:
                    interest_rate = rates.get("20_yr_fixed")
                elif loan_term == 10:
                    interest_rate = rates.get("10_yr_fixed")
                else:
                    interest_rate = rates.get("30_yr_fixed")
            elif loan_type == "ARM":
                # Match ARM term keys
                key = f"ARM_{loan_term}"
                interest_rate = rates.get(key, rates.get("30_yr_fixed"))
            else:
                interest_rate = rates.get("30_yr_fixed")

            # Monthly principal & interest
            monthly_rate = interest_rate / 100.0 / 12.0
            months = loan_term * 12
            if monthly_rate > 0:
                monthly_pi = loan_amount * (monthly_rate * (1 + monthly_rate)**months) / ((1 + monthly_rate)**months - 1)
            else:
                monthly_pi = loan_amount / months if months > 0 else 0

            # PMI logic: if down payment < 20%, use either user input or default 0.75%
            if dp_percent < 20:
                if pmi_input > 0:
                    monthly_pmi = (loan_amount * (pmi_input / 100.0)) / 12.0
                else:
                    monthly_pmi = (loan_amount * 0.75 / 100.0) / 12.0
                    pmi_message = "Down payment < 20%, PMI estimated at 0.75% annual."
            else:
                monthly_pmi = 0.0
                pmi_message = None

            monthly_tax = property_tax / 12.0
            monthly_ins = home_ins / 12.0

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
    app.run(debug=True, host="0.0.0.0")
