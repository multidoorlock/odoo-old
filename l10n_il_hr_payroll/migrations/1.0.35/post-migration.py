from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'survey.survey' not in env:
        return
    ensure_survey = getattr(env['survey.survey'], '_ensure_form_101_survey', None)
    if ensure_survey:
        ensure_survey()
