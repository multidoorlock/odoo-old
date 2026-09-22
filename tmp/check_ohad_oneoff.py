Employee = env['hr.employee'].with_context(active_test=False)
employees = Employee.search([
    '|',
    ('identification_id', '=', '325019487'),
    ('name', 'ilike', 'אוהד'),
])
print('EMPLOYEES', employees.ids)
for employee in employees:
    print('EMPLOYEE', employee.id, employee.name.encode('unicode_escape').decode(), employee.identification_id, employee.company_id.name, employee.active)
    versions = env['hr.version'].search([('employee_id', '=', employee.id)], order='date_version asc, id asc')
    for version in versions:
        print('VERSION', version.id, version.date_version, version.contract_date_start,
              version.il_tax_credit_points, version.il_monthly_tax_credit_adjustment,
              version.il_salary_structure_id.display_name)
    forms = env['hr.employee.form.101'].search([('employee_id', '=', employee.id)], order='tax_year, id')
    for form in forms:
        print('FORM101', form.id, form.tax_year, form.state, form.employment_start_date)
    slips = env['hr.payslip'].search([('employee_id', '=', employee.id)], order='date_from, id')
    for slip in slips:
        vals = {line.code: line.total for line in slip.line_ids if line.code in ('GROSS', 'NET', 'IL_TAX_BASE', 'IL_INCOME_TAX', 'IL_ISR_INCOME_TAX')}
        print('SLIP', slip.id, slip.number, slip.state, slip.date_from, slip.date_to, vals)
