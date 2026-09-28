from odoo.tools.sql import column_exists, table_exists


def migrate(cr, version):
    """Rename the former approved Form 101 state to the signed state."""
    if not table_exists(cr, 'hr_employee_form_101') or not column_exists(
        cr, 'hr_employee_form_101', 'state'
    ):
        return
    cr.execute(
        """
        UPDATE hr_employee_form_101
           SET state = 'signed'
         WHERE state = 'approved'
        """
    )
