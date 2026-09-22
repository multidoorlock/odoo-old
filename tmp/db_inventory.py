from collections import Counter


companies = env['res.company'].search([])
print('COMPANIES', ascii([(company.id, company.name, company.vat) for company in companies]))
employees = env['hr.employee'].search([], order='company_id, name')
print('EMPLOYEE_COUNTS', Counter(employee.company_id.name for employee in employees))
print('EMPLOYEES')
for employee in employees:
    print(employee.id, '|', ascii(employee.company_id.name), '|', ascii(employee.name), '|', employee.identification_id or '')
forms = env['hr.employee.form.101'].search([])
print('FORM101_COUNT', len(forms), Counter(form.state for form in forms))
for form in forms:
    print('FORM101', form.id, '|', ascii(form.employee_id.name), '|', form.tax_year, '|', form.state)
slips = env['hr.payslip'].search([])
print('PAYSLIP_COUNT', len(slips), Counter(slip.state for slip in slips))
print('PAYSLIP_MONTHS', Counter((slip.company_id.name, slip.date_from.year, slip.date_from.month) for slip in slips if slip.date_from))
