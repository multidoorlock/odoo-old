import json
from calendar import monthrange
from datetime import date, datetime

from odoo import Command


row = next(
    item for item in json.load(open('tmp/pdfs/audit_source.json', encoding='utf8'))
    if item['file'] == 'multi_2026_06' and item['page'] == 2
)
company = env.company
structure = env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il')
calendar = env['resource.calendar'].search([('company_id', 'in', (False, company.id))], limit=1)
attendance = env.ref('hr_work_entry.work_entry_type_attendance')
pension = row['components'].get('pension', 0.0)
employee = env['hr.employee'].create({
    'name': 'FULL ENGINE PDF TEST',
    'company_id': company.id,
    'identification_id': '999999998',
    'contract_date_start': date(2026, 1, 1),
    'date_version': date(2026, 1, 1),
    'resource_calendar_id': calendar.id,
    'structure_type_id': structure.type_id.id,
    'il_salary_structure_id': structure.id,
    'mdl_wage_type': 'mdl_monthly',
    'mdl_wage_rate_type': 'gross',
    'wage': row['gross'],
    'il_tax_credit_points': row['credit_points'],
    'il_pension_enabled': bool(pension),
    'il_employee_pension_rate': 6.0 if pension else 0.0,
    'il_pension_start_date': date(2026, 1, 1) if pension else False,
    'il_pension_insured_wage': pension / 0.06 if pension else 0.0,
})
slip = env['hr.payslip'].create({
    'name': 'FULL ENGINE PDF TEST',
    'employee_id': employee.id,
    'company_id': company.id,
    'date_from': date(2026, 6, 1),
    'date_to': date(2026, 6, monthrange(2026, 6)[1]),
    'version_id': employee.version_id.id,
    'struct_id': structure.id,
    'edited': True,
    'worked_days_line_ids': [Command.create({
        'work_entry_type_id': attendance.id,
        'number_of_hours': 182.0,
        'number_of_days': 22.0,
    })],
})
slip.worked_days_line_ids._compute_is_paid()

# Import the cumulative opening balance through May. It is payroll history,
# not a current-slip override, and lets Odoo calculate June cumulatively.
prior = env['hr.payslip'].create({
    'name': 'FULL ENGINE PDF TEST OPENING',
    'employee_id': employee.id,
    'company_id': company.id,
    'date_from': date(2026, 1, 1),
    'date_to': date(2026, 5, 31),
    'version_id': employee.version_id.id,
    'struct_id': structure.id,
    'state': 'validated',
    'done_date': datetime(2026, 5, 31, 23, 59, 59),
    'edited': True,
})
rules = {
    'tax_base': env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_tax_base'),
    'tax': env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_isr_income_tax'),
    'pension': env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_isr_pension_ee'),
}
for rule, total in (
    (rules['tax_base'], row['ytd_tax_base'] - row['current_tax_base']),
    (rules['tax'], -(row['ytd_components']['income_tax'] - row['components']['income_tax'])),
    (rules['pension'], -(row['ytd_components']['pension'] - pension)),
):
    env['hr.payslip.line'].create({
        'name': rule.name, 'slip_id': prior.id, 'salary_rule_id': rule.id,
        'category_id': rule.category_id.id, 'amount': total, 'quantity': 1,
        'rate': 100, 'total': total,
    })
env.flush_all()
slip.compute_sheet()
print('EXPECTED', row['gross'], row['net'], row['components'])
print('ODOO', slip.gross_wage, slip.net_wage)
print('LINES', [(line.code, line.total) for line in slip.line_ids if abs(line.total) > .001])
env.cr.rollback()
