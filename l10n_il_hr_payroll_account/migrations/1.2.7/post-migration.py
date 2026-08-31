from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    versions = env['hr.version'].search([
        ('contract_date_start', '=', False),
        ('date_version', '!=', False),
        ('structure_type_id.country_id.code', '=', 'IL'),
    ])
    for payroll_version in versions:
        payroll_version.with_context(
            il_ensuring_contract_start=True,
            sync_contract_dates=True,
        ).write({'contract_date_start': payroll_version.date_version})
