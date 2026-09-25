def migrate(cr, version):
    """Mark the existing Form 101 radio items without replacing them."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.form.101'].sudo()._upgrade_form_101_sign_template_layout()
