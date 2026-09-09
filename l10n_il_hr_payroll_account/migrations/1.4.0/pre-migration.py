def migrate(cr, version):
    """Remove the retired split mechanism before the 1.4 registry is loaded."""
    cr.execute("DROP TABLE IF EXISTS account_payment_split_line CASCADE")
    cr.execute("ALTER TABLE account_payment DROP COLUMN IF EXISTS il_spread_type")
    cr.execute("ALTER TABLE account_payment DROP COLUMN IF EXISTS il_applied_amount")
    cr.execute("ALTER TABLE account_payment DROP COLUMN IF EXISTS il_remaining_amount")
    cr.execute("ALTER TABLE account_payment DROP COLUMN IF EXISTS il_planned_amount")
    cr.execute("ALTER TABLE account_payment DROP COLUMN IF EXISTS il_currency_rounding")
    cr.execute("ALTER TABLE account_move DROP COLUMN IF EXISTS il_employee_payment_id")
    cr.execute("ALTER TABLE account_move DROP COLUMN IF EXISTS il_employee_payment_split_line_id")
