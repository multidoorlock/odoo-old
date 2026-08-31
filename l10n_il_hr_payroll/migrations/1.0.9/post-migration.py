from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Repair monthly rates previously overwritten by readonly force-save values."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    versions = env['hr.version'].with_context(active_test=False).search([
        ('mdl_wage_type', '=', 'mdl_monthly'),
    ])
    versions._compute_mdl_daily_wage()
    versions._compute_mdl_hourly_wage()
    versions.flush_recordset([
        'mdl_daily_wage', 'hourly_wage', 'mdl_hourly_wage_exact',
    ])
