def migrate(cr, version):
    """Discard obsolete transient rows from the former matrix wizard."""
    cr.execute("DELETE FROM il_payment_cycle_wizard_line")
    cr.execute("DELETE FROM il_payment_cycle_wizard")
