def migrate(cr, version):
    """Convert the former single cycle type on a batch to a many-to-many."""
    cr.execute("""
        INSERT INTO il_batch_payment_cycle_type_rel (
            batch_payment_id, cycle_type_id
        )
        SELECT id, il_payment_cycle_type_id
          FROM account_batch_payment
         WHERE il_payment_cycle_type_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    cr.execute("""
        ALTER TABLE account_batch_payment
        DROP COLUMN IF EXISTS il_payment_cycle_type_id CASCADE
    """)
