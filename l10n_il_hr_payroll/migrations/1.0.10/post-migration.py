from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Force Odoo's dependency graph to repair every stored monthly rate."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    versions = env['hr.version'].with_context(active_test=False).search([
        ('mdl_wage_type', '=', 'mdl_monthly'),
    ])
    versions.modified(['wage', 'mdl_wage_type', 'resource_calendar_id'])
    env.flush_all()
