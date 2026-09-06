def migrate(cr, version):
    """Remove persisted lines from the retired technical NET helper rule.

    The rule itself is removed by Odoo's XML data cleanup later in the module
    upgrade. Existing payslip lines must be released first because their
    salary-rule foreign key is restrictive. These are redundant intermediate
    values, not the final NET line.
    """
    cr.execute("""
        DELETE FROM hr_payslip_line
         WHERE code = 'IL_NET_BEFORE_DIRECT_ADJUSTMENTS'
    """)
