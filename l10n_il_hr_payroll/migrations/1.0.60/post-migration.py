def migrate(cr, version):
    """Repair the spouse-income controls in the current Form 101 template."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.form.101'].sudo()._ensure_form_101_assets()
