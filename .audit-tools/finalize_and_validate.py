from datetime import date

import openpyxl

PREFIX = "XLSX-PAYROLL-"
book = openpyxl.load_workbook(
    "C:\\Users\\ItayYosef\\Downloads\\\u05de\u05e2\u05e8\u05db\u05ea \u05e9\u05db\u05e8.xlsx",
    data_only=True, read_only=True,
)
sheet = book["\u05e7\u05d8\u05dc\u05d5\u05d2 \u05e2\u05d5\u05d1\u05d3\u05d9\u05dd"]
values = list(sheet.values)
headers = values[0]
identifiers = [
    str(int(dict(zip(headers, row))["\u05ea.\u05d6"]))
    for row in values[1:]
    if dict(zip(headers, row)).get("\u05ea.\u05d6")
]
employees = env["hr.employee"].with_context(active_test=False).search([
    ("identification_id", "in", identifiers),
])
slips = env["hr.payslip"].with_context(active_test=False).search([
    ("employee_id", "in", employees.ids),
    ("date_from", ">=", date(2026, 6, 1)),
    ("date_to", "<=", date(2026, 8, 31)),
])
for slip in slips.filtered(lambda item: item.state == "draft"):
    slip.compute_sheet()

payments = env["account.payment"].search([("memo", "like", PREFIX + "%")])
errors = []
for payment in payments:
    lines = payment.il_split_line_ids
    if len(lines) != 1:
        errors.append("payment %s has %s split lines" % (payment.id, len(lines)))
        continue
    line = lines[0]
    if payment.currency_id.compare_amounts(payment.amount, line.amount):
        errors.append("payment %s amount differs from split" % payment.id)
    if not line.payslip_id:
        errors.append("payment %s is not linked" % payment.id)
    elif line.employee_id != line.payslip_id.employee_id:
        errors.append("payment %s is linked to another employee" % payment.id)
    if payment.state not in ("in_process", "paid"):
        errors.append("payment %s is not effective: %s" % (payment.id, payment.state))

for slip in slips:
    net = sum(slip.line_ids.filtered(lambda line: line.code == "NET").mapped("total"))
    paid = sum(slip.il_split_line_ids.mapped("amount"))
    expected = net - paid
    if slip.currency_id.compare_amounts(slip.il_net_amount_to_pay, expected):
        errors.append("payslip %s net-to-pay mismatch %s != %s" % (slip.id, slip.il_net_amount_to_pay, expected))
    should_overpay = slip.currency_id.compare_amounts(expected, 0) < 0
    if should_overpay != (slip.state_display == "overpayment"):
        errors.append("payslip %s overpayment display mismatch" % slip.id)

overtime_lines = env["hr.attendance.overtime.line"].with_context(active_test=False).search([
    ("employee_id", "in", employees.ids),
    ("date", ">=", date(2026, 6, 1)),
    ("date", "<=", date(2026, 8, 31)),
])
for line in overtime_lines:
    if abs(line.mdl_fixed_hourly_amount - 50.0) > 0.0001:
        errors.append("overtime line %s is not fixed at 50" % line.id)
copy_rules = env["hr.salary.rule"].with_context(active_test=False).search([
    ("struct_id.code", "in", ("IL_ISR_MONTHLY", "IL_PAL_MONTHLY", "IL_ISR_DAILY", "IL_PAL_DAILY")),
    ("name", "ilike", "copy"),
])
if copy_rules:
    errors.append("salary rule names still contain Copy: %s" % copy_rules.mapped("name"))

if errors:
    raise RuntimeError("FINAL VALIDATION FAILED:\n" + "\n".join(errors))
env.cr.commit()
print("FINAL_EMPLOYEES", len(employees))
print("FINAL_PAYSLIPS", len(slips))
print("FINAL_PAYMENTS", len(payments), sum(payments.mapped("amount")))
print("FINAL_OVERTIME_LINES", len(overtime_lines), sum(overtime_lines.mapped("duration")))
print("FINAL_OVERPAYMENT_SLIPS", len(slips.filtered(lambda slip: slip.state_display == "overpayment")))
print("FINAL_VALIDATION_ERRORS", len(errors))
print("FINAL_COPY_RULE_NAMES", len(copy_rules), copy_rules.mapped("name"))
