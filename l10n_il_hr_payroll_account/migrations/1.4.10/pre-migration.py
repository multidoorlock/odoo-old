def migrate(cr, version):
    # Preserve legacy per-payslip payments as planned payments. Their already
    # reconciled lines remain untouched; post-migration adds one final open
    # instalment for any amount that was not yet represented by a split line.
    cr.execute("""
        CREATE TEMP TABLE il_legacy_per_payslip_payment (
            payment_id integer PRIMARY KEY
        ) ON COMMIT DROP
    """)
    cr.execute("""
        INSERT INTO il_legacy_per_payslip_payment (payment_id)
        SELECT id
          FROM account_payment
         WHERE il_spread_type = 'per_payslip'
    """)
    cr.execute("""
        UPDATE account_payment
           SET il_spread_type = 'planned'
         WHERE il_spread_type = 'per_payslip'
    """)
