def migrate(cr, version):
    """Remove the obsolete direct split-to-payslip relationship."""
    cr.execute("""
        ALTER TABLE account_payment_split_line
        DROP COLUMN IF EXISTS payslip_id CASCADE
    """)
