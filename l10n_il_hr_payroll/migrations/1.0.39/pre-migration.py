from odoo.tools.sql import column_exists, table_exists


def migrate(cr, version):
    if not table_exists(cr, 'hr_employee_form_101') or not column_exists(
        cr, 'hr_employee_form_101', 'state'
    ):
        return
    cr.execute("""
        UPDATE hr_employee_form_101
           SET state = 'approved'
         WHERE state IN ('sent', 'signed')
    """)
