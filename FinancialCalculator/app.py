from flask import Flask, render_template, request

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None

    if request.method == 'POST':
        try:
            home_value = float(request.form.get('home_value', 0))
            down_payment = float(request.form.get('down_payment', 0))
            down_payment_type = request.form.get('down_payment_type')  # $, %
            loan_amount_input = request.form.get('loan_amount')
            interest_rate = float(request.form.get('interest_rate', 0))
            loan_term = int(request.form.get('loan_term', 30))
            property_tax = float(request.form.get('property_tax', 0))
            pmi = float(request.form.get('pmi', 0))
            home_ins = float(request.form.get('home_ins', 0))
            hoa = float(request.form.get('hoa', 0))
            loan_type = request.form.get('loan_type')
            buy_refi = request.form.get('buy_refi')

            # Convert down payment percentage to dollars
            if down_payment_type == '%':
                down_payment = home_value * (down_payment / 100)

            # Determine loan amount
            loan_amount = float(loan_amount_input) if loan_amount_input else home_value - down_payment

            # Monthly rate
            monthly_rate = interest_rate / 100 / 12
            months = loan_term * 12

            # Monthly principal & interest
            if monthly_rate > 0:
                monthly_pi = loan_amount * (monthly_rate * (1 + monthly_rate)**months) / ((1 + monthly_rate)**months - 1)
            else:
                monthly_pi = loan_amount / months

            # Other monthly costs
            monthly_tax = property_tax / 12
            monthly_ins = home_ins / 12
            monthly_pmi = loan_amount * (pmi / 100 / 12)
            total_monthly = monthly_pi + monthly_tax + monthly_ins + monthly_pmi + hoa

	    result = {
	    	"loan_amount": round(loan_amount, 2),
    		"monthly_payment": round(total_monthly, 2),
    		"details": {
        		"principal_interest": round(monthly_pi, 2),
        		"tax": round(monthly_tax, 2),
        		"insurance": round(monthly_ins, 2),
        		"pmi": round(monthly_pmi, 2),
        		"hoa": round(hoa, 2)
    			}
		}

