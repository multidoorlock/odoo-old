from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Recompute weekly bases and the monthly rates which depend on them."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    calendars = env['resource.calendar'].with_context(active_test=False).search([])
    calendars.modified([
        'mdl_schedule_type', 'mdl_schedule_frequency',
        'mdl_shifts_per_week', 'mdl_hours_per_day', 'attendance_ids',
    ])
    env.flush_all()

    versions = env['hr.version'].with_context(active_test=False).search([
        ('mdl_wage_type', '=', 'mdl_monthly'),
    ])
    versions.modified(['wage', 'mdl_wage_type', 'resource_calendar_id'])
    env.flush_all()
