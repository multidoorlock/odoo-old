from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # These values are now live summary fields backed by accounting
    # reconciliation. Keep historical rule records for old payslip lines,
    # but remove every copy from active salary calculation.
    obsolete_rules = env['hr.salary.rule'].with_context(active_test=False).search([
        ('code', 'in', ('IL_PAYMENTS', 'IL_NET_TO_PAY')),
    ])
    obsolete_rules.write({
        'active': False,
        'appears_on_payslip': False,
    })
