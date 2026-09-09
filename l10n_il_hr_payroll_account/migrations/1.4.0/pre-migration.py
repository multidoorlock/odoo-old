def migrate(cr, version):
    """Retire the former split-created journal-entry links.

    The split records and payment fields are deliberately preserved: in the
    current design they schedule native reconciliations instead of creating
    separate journal entries.
    """
    cr.execute("ALTER TABLE account_move DROP COLUMN IF EXISTS il_employee_payment_id")
    cr.execute("ALTER TABLE account_move DROP COLUMN IF EXISTS il_employee_payment_split_line_id")
