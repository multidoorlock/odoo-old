from calendar import monthrange
from datetime import date, datetime

import openpyxl
import pytz

WORKBOOK = "C:\\Users\\ItayYosef\\Downloads\\\u05de\u05e2\u05e8\u05db\u05ea \u05e9\u05db\u05e8.xlsx"
TZ = pytz.timezone("Asia/Jerusalem")


def rows(sheet, header_row=1):
    values = list(sheet.values)
    headers = values[header_row - 1]
    return [dict(zip(headers, row)) for row in values[header_row:] if any(value is not None for value in row)]


def utc_naive(value):
    if not isinstance(value, datetime):
        return False
    return TZ.localize(value).astimezone(pytz.utc).replace(tzinfo=None)


book = openpyxl.load_workbook(WORKBOOK, data_only=True, read_only=True)
catalog = rows(book["\u05e7\u05d8\u05dc\u05d5\u05d2 \u05e2\u05d5\u05d1\u05d3\u05d9\u05dd"])
attendance_rows = rows(book["\u05e4\u05d9\u05e8\u05d5\u05d8 \u05e0\u05d5\u05db\u05d7\u05d5\u05ea"], 2)
transfer_rows = rows(book["\u05e0\u05ea\u05d5\u05e0\u05d9 \u05d4\u05e2\u05d1\u05e8\u05d5\u05ea"], 2)
catalog = [row for row in catalog if row.get("\u05ea.\u05d6")]
employee_ids = [str(int(row["\u05ea.\u05d6"])) for row in catalog]
employees = env["hr.employee"].with_context(active_test=False).search([("identification_id", "in", employee_ids)])
by_id = {employee.identification_id: employee for employee in employees}
missing = sorted(set(employee_ids) - set(by_id))
if missing:
    raise RuntimeError("Missing employees: %s" % ", ".join(missing))

calendar = env["resource.calendar"].search([("name", "=", "MDL Israel Shift Calendar")], limit=1)
if not calendar:
    calendar = env.company.resource_calendar_id.copy({"name": "MDL Israel Shift Calendar"})
calendar.write({
    "tz": "Asia/Jerusalem",
    "mdl_schedule_type": "shifts",
    "mdl_schedule_frequency": "weekly_quota",
    "mdl_shifts_per_week": 5,
})
# The source workbook pays the special weekend rate for Saturday only
# (its report column is explicitly "Saturday days").
env.company.write({"mdl_weekend_friday": False, "mdl_weekend_saturday": True})
segment_ruleset = env["hr.attendance.segment.ruleset"].search([("name", "=", "ruleset")], limit=1)
if not segment_ruleset:
    raise RuntimeError("Attendance segment ruleset was not found")

overtime_ruleset = env["hr.attendance.overtime.ruleset"].search([("name", "=", "MDL Fixed Overtime 50")], limit=1)
if not overtime_ruleset:
    overtime_ruleset = env["hr.attendance.overtime.ruleset"].create({
        "name": "MDL Fixed Overtime 50", "company_id": env.company.id, "rate_combination_mode": "max",
    })
overtime_ruleset.rule_ids.unlink()
env["hr.attendance.overtime.rule"].create({
    "name": "Over 9:30 effective hours - fixed 50 NIS/hour",
    "ruleset_id": overtime_ruleset.id,
    "sequence": 10,
    "base_off": "quantity",
    "expected_hours_from_contract": False,
    "expected_hours": 9.5,
    "quantity_period": "day",
    "employer_tolerance": 2.0 / 3.0,
    "employee_tolerance": 0.0,
    "paid": True,
    "mdl_pay_method": "fixed",
    "mdl_fixed_hourly_amount": 50.0,
    "work_entry_type_id": env.ref("hr_work_entry.work_entry_type_overtime").id,
})

structures = {
    "daily": env["hr.payroll.structure"].search([("code", "=", "IL_PAL_DAILY")], limit=1),
    "monthly": env["hr.payroll.structure"].search([("code", "=", "IL_PAL_MONTHLY")], limit=1),
}
if not all(structures.values()):
    raise RuntimeError("The Palestinian daily/monthly structures are missing")

for row in catalog:
    employee = by_id[str(int(row["\u05ea.\u05d6"]))]
    monthly = str(row.get("\u05e1\u05d5\u05d2 \u05e9\u05db\u05e8") or "").startswith("\u05d2\u05dc\u05d5\u05d1\u05dc\u05d9")
    structure = structures["monthly" if monthly else "daily"]
    weekend_wage = float(row.get("\u05e9\u05db\u05e8 \u05d9\u05d5\u05dd \u05e9\u05d9\u05e9\u05d9/\u05e9\u05d1\u05ea") or 0)
    values = {
        "contract_date_start": date(2026, 6, 1),
        "structure_type_id": structure.type_id.id,
        "il_salary_structure_id": structure.id,
        "schedule_pay": "monthly",
        "resource_calendar_id": calendar.id,
        "work_entry_source": "attendance",
        "segment_ruleset_id": segment_ruleset.id,
        "ruleset_id": overtime_ruleset.id,
        "mdl_wage_type": "mdl_monthly" if monthly else "mdl_daily",
        "mdl_weekend_wage": weekend_wage,
        "mdl_weekend_rate_type": "gross" if weekend_wage else False,
    }
    if monthly:
        values["wage"] = float(row.get("\u05e9\u05db\u05e8 \u05d2\u05dc\u05d5\u05d1\u05dc\u05d9") or 0)
    else:
        values["mdl_daily_wage"] = float(row.get("\u05e9\u05db\u05e8 \u05d9\u05d5\u05de\u05d9 \u05d7\u05d5\u05dc") or 0)
    employee.version_id.write(values)
    employee.active = bool(row.get("\u05e4\u05e2\u05d9\u05dc"))

target_ids = employees.ids
env["hr.work.entry"].search([
    ("employee_id", "in", target_ids), ("date", ">=", date(2026, 6, 1)), ("date", "<=", date(2026, 8, 31)),
]).unlink()
env["hr.attendance.overtime.line"].search([
    ("employee_id", "in", target_ids), ("date", ">=", date(2026, 6, 1)), ("date", "<=", date(2026, 8, 31)),
]).unlink()
env["hr.attendance"].search([
    ("employee_id", "in", target_ids),
    ("check_in", ">=", datetime(2026, 5, 31, 21)),
    ("check_in", "<", datetime(2026, 9, 1, 21)),
]).unlink()

attendance_values = []
for row in attendance_rows:
    identifier = row.get("\u05ea.\u05d6")
    check_in = utc_naive(row.get("\u05db\u05e0\u05d9\u05e1\u05d4"))
    check_out = utc_naive(row.get("\u05d9\u05e6\u05d9\u05d0\u05d4"))
    employee = by_id.get(str(int(identifier))) if identifier else False
    if employee and check_in and check_out and check_out > check_in:
        attendance_values.append({"employee_id": employee.id, "check_in": check_in, "check_out": check_out})
# The workbook contains two pairs for the same employee where a later check-in
# sits inside an otherwise identical shift. Treat those as duplicate clock
# events and keep the union, while retaining Odoo's no-overlap invariant.
attendance_values.sort(key=lambda value: (value["employee_id"], value["check_in"], value["check_out"]))
normalized_attendances = []
merged_overlaps = 0
for value in attendance_values:
    previous = normalized_attendances[-1] if normalized_attendances else None
    if previous and previous["employee_id"] == value["employee_id"] and value["check_in"] < previous["check_out"]:
        previous["check_out"] = max(previous["check_out"], value["check_out"])
        merged_overlaps += 1
    else:
        normalized_attendances.append(value)
attendance_values = normalized_attendances
for offset in range(0, len(attendance_values), 200):
    env["hr.attendance"].create(attendance_values[offset:offset + 200])
for employee in employees:
    employee.version_id._generate_work_entries(datetime(2026, 6, 1), datetime(2026, 9, 1), force=True)

old_slips = env["hr.payslip"].search([
    ("employee_id", "in", target_ids), ("date_from", ">=", date(2026, 6, 1)), ("date_to", "<=", date(2026, 8, 31)),
])
if old_slips.filtered(lambda slip: slip.state != "draft"):
    raise RuntimeError("A non-draft target payslip exists; refusing to replace it")
old_slips.unlink()
expected_keys = {
    (identifier, date(2026, month, 1))
    for identifier in employee_ids
    for month in (6, 7, 8)
}
transfer_by_key = {
    (str(int(row["\u05ea.\u05d6"])), row["\u05d7\u05d5\u05d3\u05e9"].date().replace(day=1)): row
    for row in transfer_rows
    if row.get("\u05ea.\u05d6") and isinstance(row.get("\u05d7\u05d5\u05d3\u05e9"), datetime)
    and date(2026, 6, 1) <= row["\u05d7\u05d5\u05d3\u05e9"].date() <= date(2026, 8, 31)
}
addition_type = env.ref("mdl_payroll_payments.input_type_il_adj_salary_addition")
created_slips = env["hr.payslip"]
for identifier, month in sorted(expected_keys):
    employee = by_id[identifier]
    month_stop = date(month.year, month.month, monthrange(month.year, month.month)[1])
    slip = env["hr.payslip"].create({
        "name": "%s %s" % (employee.name, month.strftime("%m/%Y")),
        "employee_id": employee.id,
        "company_id": employee.company_id.id,
        "date_from": month,
        "date_to": month_stop,
        "struct_id": employee.version_id.il_salary_structure_id.id,
    })
    transfer_row = transfer_by_key.get((identifier, month), {})
    addition = float(transfer_row.get("\u05ea\u05d5\u05e1\u05e4\u05ea \u05d1\u05ea\u05dc\u05d5\u05e9") or 0)
    if addition:
        env["hr.payslip.input"].create({
            "payslip_id": slip.id,
            "input_type_id": addition_type.id,
            "name": transfer_row.get("\u05d4\u05e2\u05e8\u05d5\u05ea \u05ea\u05d5\u05e1\u05e4\u05ea") or addition_type.name,
            "amount": addition,
        })
    slip.compute_sheet()
    created_slips |= slip

env.cr.commit()
print("SYNC_EMPLOYEES", len(employees))
print("SYNC_ATTENDANCES", len(attendance_values))
print("SYNC_MERGED_OVERLAPS", merged_overlaps)
print("SYNC_PAYSLIPS", len(created_slips))
print("SYNC_RULESET", overtime_ruleset.id, [(r.expected_hours, r.employer_tolerance, r.mdl_fixed_hourly_amount) for r in overtime_ruleset.rule_ids])
