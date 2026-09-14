from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Display the existing additional-day type in settings for old companies."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    entry_type = env.ref(
        'l10n_il_hr_payroll.work_entry_type_additional_day',
        raise_if_not_found=False)
    if entry_type:
        env['res.company'].search([
            ('mdl_additional_day_work_entry_type_id', '=', False),
        ]).write({'mdl_additional_day_work_entry_type_id': entry_type.id})
