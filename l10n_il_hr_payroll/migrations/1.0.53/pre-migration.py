def migrate(cr, version):
    """Rename the former approved Form 101 state to the signed state."""
    cr.execute(
        """
        UPDATE hr_employee_form_101
           SET state = 'signed'
         WHERE state = 'approved'
        """
    )
