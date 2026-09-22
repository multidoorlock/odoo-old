import json
import os
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

from odoo import Command


SOURCE = Path('tmp/pdfs/audit_source.json')
OUTPUT = Path(os.environ.get(
    'PAYROLL_AUDIT_OUTPUT',
    'tmp/pdfs/full_engine_audit_result.json',
))
rows = json.loads(SOURCE.read_text(encoding='utf-8'))
if os.environ.get('PAYROLL_AUDIT_NONZERO_ONLY') == '1':
    rows = [row for row in rows if row.get('gross', 0.0) > 0.0]
target_identification_id = os.environ.get('PAYROLL_AUDIT_IDENTIFICATION_ID')
if target_identification_id:
    rows = [
        row for row in rows
        if row.get('identification_id') == target_identification_id
    ]

# Employees for whom the supplied archive contains an identifiable Form 101.
# For these rows the audit creates an active Form 101 and verifies that payroll
# takes the credit points from the form, not from the legacy employee field.
FORM_101_IDENTIFICATION_IDS = {
    '025343559', '027173723', '027464163', '060462561',
    '060716081', '315115451', '318448826', '318956539',
    '325019487', '326356482', '326371572', '326453933',
}
tax_adjustment = float(os.environ.get('PAYROLL_AUDIT_TAX_ADJUSTMENT', '0'))
forced_rate_type = os.environ.get('PAYROLL_AUDIT_FORCE_RATE_TYPE')
if forced_rate_type not in (None, 'gross', 'net'):
    raise ValueError('PAYROLL_AUDIT_FORCE_RATE_TYPE must be gross or net')

# Historical, employee-specific opening supplied by the source payroll.
# Ohad started on 15/03/2026, so his June cumulative calculation covers
# March-June rather than January-June.  Keep this audit/import exception here
# instead of changing the statutory salary rule for every employee.
ONE_OFF_VERSION_OVERRIDES = {
    ('325019487', 'multi_2026_06'): {
        'il_monthly_tax_credit_adjustment': -219.83,
    },
}
start = int(os.environ.get('PAYROLL_AUDIT_START', '0'))
end = int(os.environ.get('PAYROLL_AUDIT_END', str(len(rows))))
indexed_rows = list(enumerate(rows, 1))[start:end]

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
        return capped * (5.17 if health else 7.0) / 100.0
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
            votes.append(
                abs(money(statutory_ni(base, health, True)) - expected)
                + 0.01
                < abs(money(statutory_ni(base, health, False)) - expected)
            )
    return {
        'il_ni_full_rate_from_first_shekel': bool(votes and sum(votes) > len(votes) / 2),
        'il_national_insurance_exempt': 'national_insurance' not in components,
        'il_health_insurance_exempt': 'health_insurance' not in components,
    }


def create_prior_line(prior, rule, total):
    if abs(total) <= 0.000001:
        return
    env['hr.payslip.line'].create({
        'name': rule.name,
        'slip_id': prior.id,
        'salary_rule_id': rule.id,
        'category_id': rule.category_id.id,
        'amount': total,
        'quantity': 1.0,
        'rate': 100.0,
        'total': total,
    })


def create_active_form_101(employee, row, year):
    """Create the smallest deterministic Form 101 profile for audit purposes.

    The source payslip records the already-approved credit-point total.  The
    matching Form 101 proves that a declaration exists for this employee; this
    profile makes Odoo derive that same total through Form 101 fields so the
    integration path itself is exercised by every matched payslip.
    """
    points = float(row.get('credit_points') or 0.0)
    if points < 2.25:
        return env['hr.employee.form.101']
    female = abs((points - 2.75) - round(points - 2.75)) <= 0.001
    base = 2.75 if female else 2.25
    remaining = int(round(points - base))
    relief_fields = (
        'relief_studies',
        'relief_support_non_custody',
        'relief_age_16_18',
        'relief_alimony_former_spouse',
    )
    if remaining < 0 or remaining > len(relief_fields):
        return env['hr.employee.form.101']
    values = {
        'employee_id': employee.id,
        'company_id': employee.company_id.id,
        'tax_year': str(year),
        'state': 'active',
        'employer_withholding_file': 'AUDIT',
        'first_name': employee.name,
        'last_name': 'AUDIT',
        'birthday': date(1990, 1, 1),
        'private_street': 'AUDIT',
        'private_house_number': '1',
        'private_city': 'AUDIT',
        'mobile_phone': '0500000000',
        'relief_resident': True,
        'is_israeli_resident': 'yes',
        'sex': 'female' if female else 'male',
        'has_other_income': 'no',
        'credit_points_here': 'here',
        'employment_start_date': date(year, 1, 1),
        'employer_income_main_type': 'monthly',
        'declaration_confirmed': True,
        'declaration_date': date(year, 1, 1),
    }
    values.update({field: index < remaining for index, field in enumerate(relief_fields)})
    form = env['hr.employee.form.101'].create(values)
    calculated = form._il_payroll_credit_points(date(year, 6, 1))
    if abs(calculated - points) > 0.001:
        raise ValueError(
            f'Form 101 points mismatch for {row.get("identification_id")}: '
            f'{calculated} != {points}')
    return form


results = []
for chunk_position, (index, row) in enumerate(indexed_rows, 1):
    year, month = month_from_key(row['file'])
    date_from = date(year, month, 1)
    date_to = date(year, month, monthrange(year, month)[1])
    structure = structures[row['layout']]
    components = row['components']
    pension = components.get('pension', 0.0)
    one_off_values = ONE_OFF_VERSION_OVERRIDES.get(
        (row.get('identification_id'), row['file']), {})

    rate_type = forced_rate_type or (
        'net' if row['layout'] == 'autonomy' else 'gross'
    )
    employee = env['hr.employee'].create({
        'name': f'FULL ENGINE AUDIT {index:03d}',
        'company_id': company.id,
        'identification_id': f'98{index:07d}',
        'contract_date_start': date(year, 1, 1),
        'date_version': date(year, 1, 1),
        'resource_calendar_id': calendar.id,
        'structure_type_id': structure.type_id.id,
        'il_salary_structure_id': structure.id,
        'mdl_wage_type': 'mdl_monthly',
        # The Shavit/Autonomia source payslips are explicitly net-wage
        # contracts: the source gross changes so the contractual NET stays at
        # a round target.  Let Odoo run its native gross-up engine for those
        # workers instead of treating the source gross as a fixed wage.
        'mdl_wage_rate_type': rate_type,
        'wage': row['net'] if rate_type == 'net' else row['gross'],
        'il_tax_credit_points': row.get('credit_points') or 0.0,
        # Optional audit-only employee adjustment.  This lets us verify a
        # historical, employee-specific tax opening without changing rules.
        'il_monthly_tax_credit_adjustment': (
            tax_adjustment
            if os.environ.get('PAYROLL_AUDIT_TAX_ADJUSTMENT') is not None
            else one_off_values.get('il_monthly_tax_credit_adjustment', 0.0)
        ),
        'il_pension_enabled': bool(pension),
        'il_employee_pension_rate': 6.0 if pension else 0.0,
        'il_pension_start_date': date(year, 1, 1) if pension else False,
        'il_pension_insured_wage': pension / 0.06 if pension else 0.0,
        **insurance_flags(row),
    })
    form_101 = env['hr.employee.form.101']
    if row.get('identification_id') in FORM_101_IDENTIFICATION_IDS:
        form_101 = create_active_form_101(employee, row, year)
    current = env['hr.payslip'].create({
        'name': f'FULL ENGINE AUDIT current {index:03d}',
        'employee_id': employee.id,
        'company_id': company.id,
        'date_from': date_from,
        'date_to': date_to,
        'version_id': employee.version_id.id,
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
            'name': f'FULL ENGINE AUDIT opening {index:03d}',
            'employee_id': employee.id,
            'company_id': company.id,
            'date_from': date(year, 1, 1),
            'date_to': prior_to,
            'version_id': employee.version_id.id,
            'struct_id': structure.id,
            'state': 'validated',
            'done_date': datetime.combine(prior_to, datetime.max.time()),
            'edited': True,
        })
        create_prior_line(prior, rules['tax_base'], row['ytd_tax_base'] - row['current_tax_base'])
        create_prior_line(
            prior,
            rules[f"{row['layout']}_tax"],
            -(row.get('ytd_components', {}).get('income_tax', 0.0) - components.get('income_tax', 0.0)),
        )
        create_prior_line(
            prior,
            rules[f"{row['layout']}_pension"],
            -(row.get('ytd_components', {}).get('pension', 0.0) - pension),
        )
        env.flush_all()

    current.compute_sheet()
    lines = {
        line.code: money(line.total)
        for line in current.line_ids
        if line.code and abs(line.total) > 0.000001
    }
    net_actual = lines.get('NET', money(current.net_wage))
    gross_actual = money(current.gross_wage)
    results.append({
        **row,
        'profile': insurance_flags(row),
        'form_101_used': bool(form_101),
        'form_101_points': (
            form_101._il_payroll_credit_points(date(year, month, 1))
            if form_101 else None
        ),
        'gross_actual': gross_actual,
        'gross_error': money(gross_actual - row['gross']),
        'net_actual': net_actual,
        'net_error': money(net_actual - row['net']),
        'net_exact': abs(net_actual - row['net']) <= 0.01,
        'lines': lines,
    })
    if chunk_position % 25 == 0:
        print(f'PROGRESS {chunk_position}/{len(indexed_rows)} (source {index})', flush=True)


def summarize(items):
    return {
        'total': len(items),
        'gross_exact': sum(abs(item['gross_error']) <= 0.01 for item in items),
        'net_exact': sum(item['net_exact'] for item in items),
        'net_within_0_10': sum(abs(item['net_error']) <= 0.10 for item in items),
        'net_within_1': sum(abs(item['net_error']) <= 1.0 for item in items),
        'net_within_10': sum(abs(item['net_error']) <= 10.0 for item in items),
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
    'largest_net_errors': sorted(results, key=lambda item: abs(item['net_error']), reverse=True)[:30],
    'results': results,
}
output = OUTPUT if start == 0 and end >= len(rows) else OUTPUT.with_name(
    f'{OUTPUT.stem}_{start:03d}_{end:03d}{OUTPUT.suffix}')
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in report.items() if key != 'results'}, ensure_ascii=False, indent=2))

# The audit is intentionally read-only for the user's database.
env.cr.rollback()
