from calendar import monthrange
from datetime import date, datetime

import openpyxl

WORKBOOK = "C:\\Users\\ItayYosef\\Downloads\\\u05de\u05e2\u05e8\u05db\u05ea \u05e9\u05db\u05e8.xlsx"
PREFIX = "XLSX-PAYROLL-"


def rows(sheet, header_row=2):
    values = list(sheet.values)
    headers = values[header_row - 1]
    return [dict(zip(headers, row)) for row in values[header_row:] if any(value is not None for value in row)]


book = openpyxl.load_workbook(WORKBOOK, data_only=True, read_only=True)
transfer_rows = rows(book["\u05e0\u05ea\u05d5\u05e0\u05d9 \u05d4\u05e2\u05d1\u05e8\u05d5\u05ea"])
rows_to_import = [
    row for row in transfer_rows
    if row.get("\u05ea.\u05d6") and isinstance(row.get("\u05d7\u05d5\u05d3\u05e9"), datetime)
    and date(2026, 6, 1) <= row["\u05d7\u05d5\u05d3\u05e9"].date() <= date(2026, 8, 31)
]
identifiers = list({str(int(row["\u05ea.\u05d6"])) for row in rows_to_import})
employees = env["hr.employee"].with_context(active_test=False).search([("identification_id", "in", identifiers)])
by_id = {employee.identification_id: employee for employee in employees}

existing = env["account.payment"].search([("memo", "like", PREFIX + "%")])
if existing:
    raise RuntimeError("Imported payments already exist; refusing to duplicate: %s" % existing.ids)

journal = env["account.journal"].search([
    ("company_id", "=", env.company.id), ("type", "in", ("bank", "cash")),
], order="type asc,id asc", limit=1)
if not journal or not journal.outbound_payment_method_line_ids:
    raise RuntimeError("No outbound bank/cash payment method is configured")
method = journal.outbound_payment_method_line_ids[:1]
payments = env["account.payment"]

for row in rows_to_import:
    identifier = str(int(row["\u05ea.\u05d6"]))
    employee = by_id[identifier]
    month = row["\u05d7\u05d5\u05d3\u05e9"].date().replace(day=1)
    month_stop = date(month.year, month.month, monthrange(month.year, month.month)[1])
    slip = env["hr.payslip"].with_context(active_test=False).search([
        ("employee_id", "=", employee.id), ("date_from", "=", month), ("date_to", "=", month_stop),
    ], limit=1)
    if not slip:
        raise RuntimeError("Missing payslip for %s %s" % (identifier, month))
    if not employee.work_contact_id:
        raise RuntimeError("Employee %s has no work contact" % identifier)
    items = [
        ("ADV", float(row.get("\u05e1\u05da \u05de\u05e4\u05e8\u05e2\u05d5\u05ea \u05d7\u05d5\u05d3\u05e9\u05d9") or 0), month_stop),
        ("BANK", float(row.get("\u05e1\u05db\u05d5\u05dd \u05d4\u05e2\u05d1\u05e8\u05d4 \u05d1\u05e4\u05d5\u05e2\u05dc") or 0), row.get("\u05ea\u05d0\u05e8\u05d9\u05da \u05d4\u05e2\u05d1\u05e8\u05d4") or month_stop),
    ]
    for kind, amount, payment_date in items:
        if amount <= 0:
            continue
        if isinstance(payment_date, datetime):
            payment_date = payment_date.date()
        memo = "%s%s-%s-%s" % (PREFIX, kind, month.strftime("%Y%m"), identifier)
        payment = env["account.payment"].with_context(il_origin_payslip_id=slip.id).create({
            "payment_type": "outbound",
            "partner_type": "supplier",
            "partner_id": employee.work_contact_id.id,
            "amount": amount,
            "date": payment_date,
            "journal_id": journal.id,
            "payment_method_line_id": method.id,
            "memo": memo,
            "payment_reference": memo,
            "il_spread_type": "none",
        })
        payment.action_post()
        payments |= payment

for slip in payments.mapped("il_split_line_ids.payslip_id"):
    slip.compute_sheet()

env.cr.commit()
print("PAYMENTS_IMPORTED", len(payments))
print("PAYMENTS_TOTAL", sum(payments.mapped("amount")))
print("PAYMENTS_LINKED", len(payments.mapped("il_split_line_ids")), len(payments.mapped("il_split_line_ids.payslip_id")))
print("PAYMENTS_STATES", sorted(set(payments.mapped("state"))))
