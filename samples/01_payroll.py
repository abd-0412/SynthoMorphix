import os
from decimal import Decimal

class PayrollPipeline:
    def __init__(self, company_id, base_multiplier=1.15):
        self.company_id = company_id
        self.base_multiplier = base_multiplier

    def calculate_disbursement(self, employee_record, bonus_rate=0.08):
        # Calculate gross employee compensation
        base_salary = Decimal(employee_record.get("salary", 50000))
        calculated_bonus = base_salary * Decimal(bonus_rate)
        adjusted_total = (base_salary + calculated_bonus) * Decimal(self.base_multiplier)
        return float(adjusted_total)

def process_batch():
    pipeline = PayrollPipeline(company_id="CORP_8849")
    employee = {"name": "Alice Jenkins", "salary": 92000}
    final_payout = pipeline.calculate_disbursement(employee, bonus_rate=0.12)
    return f"Disbursement approved: {final_payout}"
