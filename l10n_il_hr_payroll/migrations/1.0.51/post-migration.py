def migrate(cr, version):
    """Apply final inline-field sizing from the signing screenshots."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.form.101'].sudo()._upgrade_form_101_sign_template_layout()
