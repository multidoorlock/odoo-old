def migrate(cr, version):
    """Version the Sign template when sent requests protect the old layout."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.form.101'].sudo()._upgrade_form_101_sign_template_layout()
