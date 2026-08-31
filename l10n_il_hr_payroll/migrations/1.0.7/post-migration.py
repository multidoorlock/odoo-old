from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Recompute exact/display hourly rates after the 1.0.6 SQL data merge."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    daily_versions = env['hr.version'].with_context(active_test=False).search([
        ('mdl_wage_type', '=', 'mdl_daily'),
    ])
    if daily_versions:
        daily_versions._compute_mdl_hourly_wage()
        daily_versions.flush_recordset([
            'mdl_hourly_wage_exact',
            'hourly_wage',
        ])
