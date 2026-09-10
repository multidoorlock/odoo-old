from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT payment_id
          FROM il_legacy_per_payslip_payment
         ORDER BY payment_id
    """)
    payments = env['account.payment'].browse([
        payment_id for payment_id, in cr.fetchall()
    ])
    Split = env['account.payment.split.line']
    for payment in payments.exists():
        represented = sum(payment.il_split_line_ids.mapped('amount'))
        remainder = payment.amount - represented
        if payment.currency_id.compare_amounts(remainder, 0.0) > 0:
            Split.with_context(
                il_system_split_create=True,
                il_skip_spread_total_check=True,
            ).create({
                'payment_id': payment.id,
                'amount': remainder,
            })
