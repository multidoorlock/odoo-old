def migrate(cr, version):
    """Correct the active Form 101 fields without creating a new template."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.form.101'].sudo()._upgrade_form_101_sign_template_layout()
