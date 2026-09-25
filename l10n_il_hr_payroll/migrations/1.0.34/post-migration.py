from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['survey.survey']._ensure_form_101_survey()
    intake_templates = env['sign.template'].search([
        ('name', '=', 'טופס 101 למילוי עובד'),
    ])
    for template in intake_templates:
        if env['sign.request'].search_count([('template_id', '=', template.id)]):
            template.active = False
        else:
            template.unlink()
