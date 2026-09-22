def migrate(cr, version):
    # 1.0.25 replaces three booleans with explicit Yes/No selections so that
    # "No" is a real, required answer instead of being indistinguishable from
    # an untouched checkbox.
    for column in ('has_israeli_id', 'is_israeli_resident', 'spouse_has_israeli_id'):
        cr.execute(
            f'''
                UPDATE hr_employee_form_101
                   SET {column} = CASE
                       WHEN {column}::text IN ('true', 't', '1', 'yes') THEN 'yes'
                       ELSE 'no'
                   END
            '''
        )

    # The former "inactive" state was removed. Replaced forms return to the
    # standard draft state and retain all of their historical contents.
    cr.execute("UPDATE hr_employee_form_101 SET state = 'draft' WHERE state = 'inactive'")

    # Existing drafts predate these mandatory fields. Keep them editable and
    # visibly mark the missing value instead of inventing personal data.
    cr.execute(
        """
            UPDATE hr_employee_form_101
               SET last_name = '-'
             WHERE last_name IS NULL OR btrim(last_name) = ''
        """
    )
    cr.execute(
        """
            UPDATE hr_employee_form_101
               SET private_house_number = '-'
             WHERE private_house_number IS NULL OR btrim(private_house_number) = ''
        """
    )
