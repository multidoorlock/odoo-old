def migrate(cr, version):
    """Collapse the temporary separate net fields back into the shared wage."""
    cr.execute("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'hr_version'
           AND column_name = 'mdl_net_daily_wage'
    """)
    if cr.fetchone():
        cr.execute("""
            UPDATE hr_version
               SET mdl_daily_wage = mdl_net_daily_wage
             WHERE mdl_wage_rate_type = 'net'
               AND mdl_net_daily_wage > 0
        """)
    cr.execute("""
        ALTER TABLE hr_version
            DROP COLUMN IF EXISTS mdl_net_daily_wage,
            DROP COLUMN IF EXISTS mdl_net_hourly_wage,
            DROP COLUMN IF EXISTS mdl_net_hourly_wage_exact
    """)
