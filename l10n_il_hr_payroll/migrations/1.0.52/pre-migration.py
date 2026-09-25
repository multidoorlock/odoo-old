def migrate(cr, version):
    """Transfer the temporary Section 14 addon's records to payroll.

    The feature was initially installed as ``l10n_il_hr_section_14``.  Moving
    its external IDs before loading the payroll XML lets Odoo update the same
    views, roles, template and model metadata instead of duplicating them.
    """
    cr.execute("""
        SELECT old.name, old.model, old.res_id, current.res_id
          FROM ir_model_data old
          JOIN ir_model_data current
            ON current.module = 'l10n_il_hr_payroll'
           AND current.name = old.name
         WHERE old.module = 'l10n_il_hr_section_14'
           AND (old.model != current.model OR old.res_id != current.res_id)
    """)
    conflicts = cr.fetchall()
    if conflicts:
        raise RuntimeError(
            'Cannot transfer Section 14 metadata because conflicting payroll '
            f'external IDs already exist: {conflicts}'
        )

    cr.execute("""
        DELETE FROM ir_model_data old
              USING ir_model_data current
         WHERE old.module = 'l10n_il_hr_section_14'
           AND current.module = 'l10n_il_hr_payroll'
           AND current.name = old.name
           AND current.model = old.model
           AND current.res_id = old.res_id
    """)
    cr.execute("""
        UPDATE ir_model_data
           SET module = 'l10n_il_hr_payroll'
         WHERE module = 'l10n_il_hr_section_14'
    """)
