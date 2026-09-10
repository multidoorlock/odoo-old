from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Retire structure copies of the removed technical NET helper rule."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.salary.rule'].with_context(active_test=False).search([
        ('code', '=', 'IL_NET_BEFORE_DIRECT_ADJUSTMENTS'),
    ]).write({
        'active': False,
        'appears_on_payslip': False,
    })
