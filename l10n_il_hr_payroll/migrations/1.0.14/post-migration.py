from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Keep additional-day hours outside the fixed monthly-wage denominator."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    additional_day = env.ref(
        'l10n_il_hr_payroll.work_entry_type_additional_day',
        raise_if_not_found=False,
    )
    if additional_day:
        additional_day.is_extra_hours = True
