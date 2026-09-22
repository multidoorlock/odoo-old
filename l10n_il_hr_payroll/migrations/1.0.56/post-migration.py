def migrate(cr, version):
    """Keep every Form 101 choice editable in pending Sign requests."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.employee.form.101'].sudo()._unlock_form_101_sign_choices()
