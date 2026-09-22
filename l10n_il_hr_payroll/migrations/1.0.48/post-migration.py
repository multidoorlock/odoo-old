def migrate(cr, version):
    """Adopt and complete the administrator-positioned Form 101 template."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.form.101'].sudo()._ensure_form_101_assets()
