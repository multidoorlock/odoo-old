def migrate(cr, version):
    """Convert the former direct payslip link to the unified split table."""
    cr.execute("""
        INSERT INTO account_payment_split_line
            (payment_id, sequence, amount, currency_id, payslip_id,
             is_applied, company_id, employee_id)
        SELECT payment.id, 1, payment.amount, payment.currency_id,
               payment.payslip_id, payment.payslip_id IS NOT NULL,
               payment.company_id, employee.id
          FROM account_payment payment
          JOIN hr_employee employee
            ON employee.work_contact_id = payment.partner_id
           AND employee.company_id = payment.company_id
         WHERE payment.payment_type = 'outbound'
           AND payment.amount > 0
           AND NOT EXISTS (
               SELECT 1 FROM account_payment_split_line split
                WHERE split.payment_id = payment.id)
    """)
    cr.execute("""
        UPDATE account_payment payment
           SET il_spread_type = COALESCE(payment.il_spread_type, 'none'),
               il_planned_amount = totals.planned,
               il_applied_amount = totals.applied,
               il_remaining_amount = payment.amount - totals.applied
          FROM (
              SELECT payment_id,
                     SUM(amount) AS planned,
                     SUM(CASE WHEN payslip_id IS NOT NULL THEN amount ELSE 0 END) AS applied
                FROM account_payment_split_line
               GROUP BY payment_id
          ) totals
         WHERE totals.payment_id = payment.id
    """)
    cr.execute("ALTER TABLE account_payment DROP COLUMN IF EXISTS payslip_id CASCADE")
