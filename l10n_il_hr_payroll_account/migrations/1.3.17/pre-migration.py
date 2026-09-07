def migrate(cr, version):
    """Preserve historic lines before removing the legacy direct-net rule."""
    cr.execute("""
        WITH salary_rules AS (
            SELECT legacy.id AS legacy_id,
                   replacement.id AS replacement_id
              FROM hr_salary_rule AS legacy
              JOIN hr_salary_rule AS replacement
                ON replacement.struct_id = legacy.struct_id
               AND replacement.code = 'IL_ADJUSTMENT_NET_GROSSUP'
             WHERE legacy.code = 'IL_ADJUSTMENT_NET_DIRECT'
        )
        UPDATE hr_payslip_line AS line
           SET salary_rule_id = salary_rules.replacement_id
          FROM salary_rules
         WHERE line.salary_rule_id = salary_rules.legacy_id
    """)
    # Structure-specific copies have no XML ID, so Odoo's removed-data cleanup
    # would only remove the base rule.  Remove every obsolete copy after all
    # historic lines have been relinked to the matching gross-up rule.
    cr.execute("""
        DELETE FROM hr_salary_rule
         WHERE code = 'IL_ADJUSTMENT_NET_DIRECT'
    """)
