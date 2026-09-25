def migrate(cr, version):
    """Install one corrected active Form 101 template and archive history."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.form.101'].sudo()._upgrade_form_101_sign_template_layout()
