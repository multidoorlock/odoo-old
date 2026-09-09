from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Enforce the final two-account design once for upgraded databases.
    for company in env['res.company'].search([]):
        env['hr.payroll.structure'].with_company(company).with_context(
            allowed_company_ids=[company.id],
        )._il_ensure_payroll_accounting_configuration(overwrite=True)

    # Retain historical rule records referenced by payslip lines, but retire
    # both former split-based salary rules from every structure.
    env['hr.salary.rule'].with_context(active_test=False).search([
        ('code', 'in', ('IL_PAYMENTS', 'IL_NET_TO_PAY')),
    ]).write({'active': False, 'appears_on_payslip': False})

    # Backfill a payslip owner where a legacy NET payable item can be matched
    # unambiguously by move, company account and employee partner.
    cr.execute("""
        UPDATE account_move_line AS line
           SET il_payslip_id = slip.id
          FROM hr_payslip AS slip
          JOIN hr_employee AS employee ON employee.id = slip.employee_id
          JOIN res_company AS company ON company.id = slip.company_id
         WHERE line.move_id = slip.move_id
           AND line.account_id = company.il_employee_payment_debit_account_id
           AND line.partner_id = employee.work_contact_id
           AND line.il_payslip_id IS NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM hr_payslip AS other
                 JOIN hr_employee AS other_employee
                   ON other_employee.id = other.employee_id
                WHERE other.move_id = slip.move_id
                  AND other.id != slip.id
                  AND other_employee.work_contact_id = employee.work_contact_id
           )
    """)
