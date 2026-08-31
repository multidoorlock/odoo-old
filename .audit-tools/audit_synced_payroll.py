from datetime import date, datetime
from statistics import mean

import openpyxl

workbook = openpyxl.load_workbook(
    "C:\\Users\\ItayYosef\\Downloads\\\u05de\u05e2\u05e8\u05db\u05ea \u05e9\u05db\u05e8.xlsx",
    data_only=True,
    read_only=True,
)
sheet = workbook["\u05e0\u05ea\u05d5\u05e0\u05d9 \u05d4\u05e2\u05d1\u05e8\u05d5\u05ea"]
iterator = sheet.iter_rows(min_row=2, values_only=True)
headers = next(iterator)
excel = {}
for values in iterator:
    row = dict(zip(headers, values))
    month = row.get("\u05d7\u05d5\u05d3\u05e9")
    identifier = row.get("\u05ea.\u05d6")
    if identifier and isinstance(month, datetime) and date(2026, 6, 1) <= month.date() <= date(2026, 8, 31):
        excel[(str(int(identifier)), month.date().replace(day=1))] = row

employees = env["hr.employee"].with_context(active_test=False).search([
    ("identification_id", "in", list({key[0] for key in excel})),
])
employee_by_id = {employee.identification_id: employee for employee in employees}
slips = env["hr.payslip"].search([
    ("employee_id", "in", employees.ids),
    ("date_from", ">=", date(2026, 6, 1)),
    ("date_to", "<=", date(2026, 8, 31)),
])

def line_amount(slip, code):
    return sum(slip.line_ids.filtered(lambda line: line.code == code).mapped("total"))


comparisons = []
for key, row in excel.items():
    employee = employee_by_id[key[0]]
    slip = slips.filtered(lambda item: item.employee_id == employee and item.date_from == key[1])[:1]
    if not slip:
        continue
    expected_base = float(row.get("\u05e9\u05db\u05e8 \u05de\u05d7\u05d5\u05e9\u05d1 \u05dc\u05d7\u05d5\u05d3\u05e9") or 0)
    expected_salary = float(row.get("\u05e9\u05db\u05e8 \u05db\u05d5\u05dc\u05dc \u05ea\u05d5\u05e1\u05e4\u05d5\u05ea") or expected_base)
    weekend = line_amount(slip, "IL_WEEKEND_GROSS")
    comparisons.append((
        key, employee.name, float(row.get("\u05d9\u05de\u05d9 \u05e2\u05d1\u05d5\u05d3\u05d4") or 0),
        expected_salary, line_amount(slip, "BASIC"), line_amount(slip, "GROSS"),
        line_amount(slip, "IL_OVERTIME"), line_amount(slip, "NET"), slip.il_net_amount_to_pay,
        expected_base, line_amount(slip, "BASIC") + weekend,
    ))

attendances = env["hr.attendance"].search([
    ("employee_id", "in", employees.ids),
    ("check_in", ">=", datetime(2026, 5, 31, 21)),
    ("check_in", "<", datetime(2026, 9, 1, 21)),
])
segments = attendances.mapped("segment_ids")
overtime_lines = env["hr.attendance.overtime.line"].search([
    ("employee_id", "in", employees.ids),
    ("date", ">=", date(2026, 6, 1)),
    ("date", "<=", date(2026, 8, 31)),
])
print("AUDIT_COUNTS", len(employees), len(attendances), len(segments), len(overtime_lines), len(slips), len(comparisons))
print("AUDIT_ATTENDANCE_HOURS", round(sum(attendances.mapped("worked_hours")), 2), round(sum(attendances.mapped("presence_hours")), 2))
print("AUDIT_NONWORK_HOURS", round(sum(segments.filtered(lambda segment: not segment.is_work).mapped("duration")), 2))
print("AUDIT_OVERTIME", round(sum(overtime_lines.mapped("duration")), 2), round(sum(overtime_lines.mapped("mdl_fixed_hourly_amount")), 2))
deltas = [item[5] - item[3] for item in comparisons]
print("AUDIT_GROSS_VS_EXCEL", "mean_delta", round(mean(deltas), 2), "exact", sum(abs(delta) < 0.01 for delta in deltas), "of", len(deltas))
for item in sorted(comparisons, key=lambda value: abs(value[5] - value[3]), reverse=True)[:10]:
    print("AUDIT_ROW", item)

# A real one-hour overtime result must be paid at the fixed rate, not percentage.
fixed_slips = [item for item in comparisons if item[6] > 0]
print("AUDIT_FIXED_OT_SLIPS", len(fixed_slips), fixed_slips[:10])
base_deltas = [item[10] - item[9] for item in comparisons]
print("AUDIT_BASE_VS_EXCEL", "mean_delta", round(mean(base_deltas), 2), "exact", sum(abs(delta) < 0.01 for delta in base_deltas), "of", len(base_deltas))
for item in comparisons:
    if abs(item[10] - item[9]) >= 0.01:
        print("AUDIT_BASE_MISMATCH", item[0], item[1], "excel_days", item[2], "excel_base", item[9], "odoo_base", item[10])
