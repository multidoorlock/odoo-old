def migrate(cr, version):
    """Collapse legacy weekend/shift settings into the new minimal model."""
    cr.execute("""
        UPDATE res_company
           SET mdl_shift_morning_hours = COALESCE(mdl_shift_paid_hours, 9.5),
               mdl_shift_evening_hours = COALESCE(mdl_shift_paid_hours, 9.5)
    """)
    cr.execute("""
        ALTER TABLE res_company
            DROP COLUMN IF EXISTS mdl_weekend_sunday,
            DROP COLUMN IF EXISTS mdl_weekend_monday,
            DROP COLUMN IF EXISTS mdl_weekend_tuesday,
            DROP COLUMN IF EXISTS mdl_weekend_wednesday,
            DROP COLUMN IF EXISTS mdl_weekend_thursday,
            DROP COLUMN IF EXISTS mdl_weekend_friday,
            DROP COLUMN IF EXISTS mdl_weekend_saturday,
            DROP COLUMN IF EXISTS mdl_shift_morning_start,
            DROP COLUMN IF EXISTS mdl_shift_morning_end,
            DROP COLUMN IF EXISTS mdl_shift_evening_start,
            DROP COLUMN IF EXISTS mdl_shift_evening_end,
            DROP COLUMN IF EXISTS mdl_shift_sleep_start,
            DROP COLUMN IF EXISTS mdl_shift_sleep_end,
            DROP COLUMN IF EXISTS mdl_shift_paid_hours,
            DROP COLUMN IF EXISTS mdl_shift_sleep_hours
    """)
    cr.execute("""
        ALTER TABLE hr_version
            DROP COLUMN IF EXISTS mdl_weekend_wage,
            DROP COLUMN IF EXISTS mdl_weekend_rate_type,
            DROP COLUMN IF EXISTS mdl_additional_day_rate_type
    """)
