def migrate(cr, version):
    """Repair stored payment totals after deleted payslip links.

    Older databases may contain split lines whose foreign key was nulled by
    ``ON DELETE SET NULL`` while stored computed values still said that the
    line was applied. Rebuild all dependent values from the canonical split
    table so upgrading is deterministic and idempotent.
    """
    cr.execute("""
        UPDATE account_payment_split_line
           SET is_applied = (payslip_id IS NOT NULL)
         WHERE is_applied IS DISTINCT FROM (payslip_id IS NOT NULL)
    """)
    cr.execute("""
        UPDATE account_payment payment
           SET il_planned_amount = COALESCE(totals.planned, 0),
               il_applied_amount = COALESCE(totals.applied, 0),
               il_remaining_amount = payment.amount - COALESCE(totals.applied, 0)
          FROM (
              SELECT candidate.id AS payment_id,
                     SUM(split.amount) AS planned,
                     SUM(split.amount) FILTER (WHERE split.payslip_id IS NOT NULL) AS applied
                FROM account_payment candidate
                LEFT JOIN account_payment_split_line split
                  ON split.payment_id = candidate.id
               GROUP BY candidate.id
          ) totals
         WHERE payment.id = totals.payment_id
    """)
