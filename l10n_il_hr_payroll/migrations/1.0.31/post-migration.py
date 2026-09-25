from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    form_model = env['hr.employee.form.101']
    template = env['sign.template'].search([
        ('active', '=', True),
        ('name', 'ilike', '101'),
    ], order='id desc', limit=1)
    if not template:
        return
    form_model.search([('sign_template_id', '=', False)]).write({
        'sign_template_id': template.id,
    })
    form_model._ensure_sign_template_configuration(template)
