from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Make actual reconciliation links the source of the deducted flag."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    split_lines = env['account.payment.split.line'].search([])
    if split_lines:
        split_lines._compute_is_applied()
        split_lines.flush_recordset(['is_applied'])

    payments = split_lines.payment_id
    if payments:
        payments._compute_il_spread_amounts()
        payments.flush_recordset([
            'il_planned_amount', 'il_applied_amount', 'il_remaining_amount',
        ])
