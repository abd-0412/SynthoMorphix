def calculate_tax(salary, tax_bracket="standard", deduction=1000):
    rate = 0.25 if tax_bracket == "standard" else 0.35
    taxable = max(0, salary - deduction)
    return taxable * rate

def process_employee():
    return calculate_tax(75000, tax_bracket="high", deduction=2500)
