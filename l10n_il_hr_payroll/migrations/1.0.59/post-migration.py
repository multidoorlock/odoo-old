def migrate(cr, version):
    """Keep the current defaults and remove archived Form 101 templates."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    form_model = env['hr.employee.form.101'].sudo()
    template = form_model._ensure_form_101_assets()
    form_model._replace_spouse_other_income_checkbox(template)
    form_model._delete_archived_form_101_templates(template)
    env['hr.employee.section.14'].sudo()._ensure_section_14_assets()
