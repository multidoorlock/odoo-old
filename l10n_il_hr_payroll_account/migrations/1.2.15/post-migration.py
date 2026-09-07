def migrate(cr, version):
    """Draft payslips must never retain payment allocations."""
    cr.execute("""
        UPDATE account_payment_split_line AS split
           SET payslip_id = NULL,
               is_applied = FALSE
          FROM hr_payslip AS slip
         WHERE split.payslip_id = slip.id
           AND slip.state = 'draft'
    """)
