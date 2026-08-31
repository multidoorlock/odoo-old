from datetime import date

identifiers = [
    "401010319", "402801633", "800832412", "850049529", "850911447", "850919549",
    "852733716", "853869600", "854944089", "854947165", "858508443", "858519051",
    "904607900", "904968807", "907535017", "907559777", "911690386", "914094800",
    "914099742", "936467018", "940853849", "941039174", "977380278",
]
# The actual set is read from the synchronized ruleset rather than hard-coded.
ruleset = env["hr.attendance.overtime.ruleset"].search([("name", "=", "MDL Fixed Overtime 50")], limit=1)
versions = env["hr.version"].with_context(active_test=False).search([("ruleset_id", "=", ruleset.id)])
employees = versions.mapped("employee_id")
print("INSPECT", len(versions), len(employees), [(e.identification_id, e.active) for e in employees if not e.active])
for employee in employees:
    entries = env["hr.work.entry"].with_context(active_test=False).search([
        ("employee_id", "=", employee.id), ("date", ">=", date(2026, 6, 1)), ("date", "<=", date(2026, 8, 31)),
    ])
    attendances = env["hr.attendance"].with_context(active_test=False).search([
        ("employee_id", "=", employee.id), ("check_in", ">=", "2026-05-31 21:00:00"), ("check_in", "<", "2026-09-01 21:00:00"),
    ])
    slips = env["hr.payslip"].with_context(active_test=False).search([
        ("employee_id", "=", employee.id), ("date_from", ">=", date(2026, 6, 1)), ("date_to", "<=", date(2026, 8, 31)),
    ])
    if attendances and not entries:
        print("NO_ENTRIES", employee.identification_id, employee.name, employee.active, len(attendances), [(s.date_from, sum(s.line_ids.filtered(lambda l: l.code == "GROSS").mapped("total"))) for s in slips])
    if employee.identification_id == "907559777":
        print("TARGET", employee.active, len(attendances), len(entries), [(entry.date, entry.duration, entry.work_entry_type_id.code, entry.state) for entry in entries], [(slip.date_from, [(line.code, line.total) for line in slip.line_ids]) for slip in slips])

lines = env["hr.attendance.overtime.line"].with_context(active_test=False).search([
    ("employee_id", "in", employees.ids), ("date", ">=", date(2026, 6, 1)), ("date", "<=", date(2026, 8, 31)),
], order="employee_id,date")
for line in lines:
    print("OT", line.employee_id.identification_id, line.date, line.duration, line.mdl_fixed_hourly_amount, line.amount_rate, line.rule_ids.mapped("name"))
