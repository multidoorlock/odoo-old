def migrate(cr, version):
    cr.execute("""
        UPDATE il_payment_cycle_type
           SET payment_state = CASE
               WHEN cancel_payments THEN 'canceled'
               ELSE 'in_process'
           END
         WHERE cancel_payments IS NOT NULL
    """)
    cr.execute("""
        ALTER TABLE il_payment_cycle_type
        DROP COLUMN IF EXISTS cancel_payments
    """)
