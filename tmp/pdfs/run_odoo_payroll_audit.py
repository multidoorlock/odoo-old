import json
from collections import Counter, defaultdict
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

from odoo import Command


SOURCE = Path('tmp/pdfs/audit_source.json')
OUTPUT = Path('tmp/pdfs/audit_result.json')
rows = json.loads(SOURCE.read_text(encoding='utf-8'))

company = env.company
calendar = env['resource.calendar'].search([
    ('company_id', 'in', (False, company.id)),
], limit=1)
attendance = env.ref('hr_work_entry.work_entry_type_attendance')
structures = {
    'multi': env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il'),
    'autonomy': env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_monthly'),
}
rules = {
    'tax_base': env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_tax_base'),
    'multi_tax': env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_isr_income_tax'),
    'autonomy_tax': env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_pal_income_tax'),
    'multi_pension': env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_isr_pension_ee'),
    'autonomy_pension': env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_pal_pension_ee'),
}


def money(value):
    return round(float(value or 0.0) + 1e-9, 2)


def month_from_key(key):
    year, month = map(int, key.rsplit('_', 2)[-2:])
    return year, month


def statutory_ni(base, health=False, full=False):
    capped = min(base, 51910.0)
    if full:
        rate = 5.17 if health else 7.0
        return capped * rate / 100.0
    reduced = min(capped, 7703.0)
    high = max(capped - 7703.0, 0.0)
    return reduced * (3.23 if health else 1.04) / 100.0 + high * (5.17 if health else 7.0) / 100.0


def insurance_flags(row):
    if row['layout'] != 'multi':
        return {}
    components = row['components']
    base = row['current_tax_base']
    votes = []
    for key, health in (('national_insurance', False), ('health_insurance', True)):
        if key in components:
            expected = components[key]
            standard_error = abs(money(statutory_ni(base, health, False)) - expected)
            full_error = abs(money(statutory_ni(base, health, True)) - expected)
            votes.append(full_error + 0.01 < standard_error)
    return {
        'il_ni_full_rate_from_first_shekel': bool(votes and sum(votes) > len(votes) / 2),
        'il_national_insurance_exempt': 'national_insurance' not in components,
        'il_health_insurance_exempt': 'health_insurance' not in components,
    }


def prior_line(prior, rule, total):
    if abs(total) <= 0.000001:
        return
    env['hr.payslip.line'].create({
        'name': rule.name,
        'slip_id': prior.id,
        'salary_rule_id': rule.id,
        'amount': total,
        'quantity': 1.0,
        'rate': 100.0,
        'total': total,
    })


results = []
for index, row in enumerate(rows, 1):
    year, month = month_from_key(row['file'])
    date_from = date(year, month, 1)
    date_to = date(year, month, monthrange(year, month)[1])
    structure = structures[row['layout']]
    components = row['components']
    pension = components.get('pension', 0.0)
    employee_values = {
        'name': f'AUDIT PDF {index:03d}',
        'company_id': company.id,
        'contract_date_start': date(year, 1, 1),
        'date_version': date(year, 1, 1),
        'resource_calendar_id': calendar.id,
        'structure_type_id': structure.type_id.id,
        'il_salary_structure_id': structure.id,
        'mdl_wage_type': 'mdl_monthly',
        'mdl_wage_rate_type': 'gross',
        'wage': row['gross'],
        'il_tax_credit_points': row.get('credit_points') or 0.0,
        'il_pension_enabled': bool(pension),
        'il_employee_pension_rate': 6.0 if pension else 0.0,
        'il_pension_start_date': date(year, 1, 1) if pension else False,
        'il_pension_insured_wage': pension / 0.06 if pension else 0.0,
        **insurance_flags(row),
    }
    employee = env['hr.employee'].create(employee_values)
    version = employee.version_id

    current = env['hr.payslip'].create({
        'name': f'AUDIT PDF current {index:03d}',
        'employee_id': employee.id,
        'company_id': company.id,
        'date_from': date_from,
        'date_to': date_to,
        'version_id': version.id,
        'struct_id': structure.id,
        'edited': True,
        'worked_days_line_ids': [Command.create({
            'work_entry_type_id': attendance.id,
            'number_of_hours': 182.0,
            'number_of_days': 22.0,
        })],
    })
    current.worked_days_line_ids._compute_is_paid()

    if month > 1:
        prior_to = date(year, month - 1, monthrange(year, month - 1)[1])
        prior = env['hr.payslip'].create({
            'name': f'AUDIT PDF prior {index:03d}',
            'employee_id': employee.id,
            'company_id': company.id,
            'date_from': date(year, 1, 1),
            'date_to': prior_to,
            'version_id': version.id,
            'struct_id': structure.id,
            'state': 'validated',
            'done_date': datetime.combine(prior_to, datetime.max.time()),
            'edited': True,
        })
        prior_line(prior, rules['tax_base'], row['ytd_tax_base'] - row['current_tax_base'])
        tax_rule = rules[f"{row['layout']}_tax"]
        prior_line(prior, tax_rule, -(
            row.get('ytd_components', {}).get('income_tax', 0.0)
            - components.get('income_tax', 0.0)))
        pension_rule = rules[f"{row['layout']}_pension"]
        prior_line(prior, pension_rule, -(
            row.get('ytd_components', {}).get('pension', 0.0) - pension))
        env.flush_all()

    tax_rule_code = 'IL_ISR_INCOME_TAX' if row['layout'] == 'multi' else 'IL_PAL_INCOME_TAX'
    tax = current._il_income_tax(row['current_tax_base'], tax_rule_code)
    if row['layout'] == 'multi':
        ni = current._il_ni_amount(
            row['current_tax_base'], 'ISR',
            'IL_ISR_NI_EE_REDUCED_RATE', 'IL_ISR_NI_EE_FULL_RATE')
        health = current._il_ni_amount(
            row['current_tax_base'], 'ISR',
            'IL_ISR_HEALTH_REDUCED_RATE', 'IL_ISR_HEALTH_FULL_RATE')
    else:
        ni = current._il_ni_amount(
            row['current_tax_base'], 'PAL',
            'IL_PAL_NI_EE_REDUCED_RATE', 'IL_PAL_NI_EE_FULL_RATE')
        health = 0.0
    pension_actual = current._il_employee_pension_contribution()
    actual = {
        'income_tax': money(tax),
        'national_insurance': money(ni),
        'health_insurance': money(health),
        'pension': money(pension_actual),
    }
    expected = {key: money(components.get(key, 0.0)) for key in actual}
    net_actual = money(row['gross'] - sum(actual.values()))
    net_error = money(net_actual - row['net'])
    results.append({
        **row,
        'profile': insurance_flags(row),
        'actual': actual,
        'errors': {key: money(actual[key] - expected[key]) for key in actual},
        'net_actual': net_actual,
        'net_error': net_error,
        'net_exact': abs(net_error) <= 0.01,
    })


def summarize(items):
    total = len(items)
    return {
        'total': total,
        'net_exact': sum(item['net_exact'] for item in items),
        'net_within_1': sum(abs(item['net_error']) <= 1.0 for item in items),
        'net_within_2': sum(abs(item['net_error']) <= 2.0 for item in items),
        'components_exact': {
            key: sum(abs(item['errors'][key]) <= 0.01 for item in items)
            for key in ('income_tax', 'national_insurance', 'health_insurance', 'pension')
        },
    }


report = {
    'summary': summarize(results),
    'by_layout': {
        layout: summarize([item for item in results if item['layout'] == layout])
        for layout in ('multi', 'autonomy')
    },
    'by_file': {
        key: summarize([item for item in results if item['file'] == key])
        for key in sorted({item['file'] for item in results})
    },
    'largest_net_errors': sorted(results, key=lambda item: abs(item['net_error']), reverse=True)[:20],
    'results': results,
}
OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in report.items() if key != 'results'}, ensure_ascii=False, indent=2))

# The audit fixtures are deliberately ephemeral.  No employee, version,
# payslip, or line created above may survive in the user's database.
env.cr.rollback()
