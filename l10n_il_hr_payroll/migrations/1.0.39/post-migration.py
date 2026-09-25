def migrate(cr, version):
    """Remove only the obsolete Form 101 survey, never the Survey app."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'survey.survey' not in env:
        return
    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'survey_survey'
           AND column_name = 'is_form_101_survey'
    """)
    if not cr.fetchone():
        return
    cr.execute("SELECT id FROM survey_survey WHERE is_form_101_survey IS TRUE")
    survey_ids = [row[0] for row in cr.fetchall()]
    if survey_ids:
        env['survey.survey'].browse(survey_ids).unlink()
