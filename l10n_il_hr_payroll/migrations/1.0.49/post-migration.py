def migrate(cr, version):
    """Apply the screenshot-verified Form 101 field coordinates."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.form.101'].sudo()._ensure_form_101_assets()
