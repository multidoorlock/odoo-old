def migrate(cr, version):
    cr.execute("""
        UPDATE hr_employee_form_101
           SET state = 'approved'
         WHERE state IN ('sent', 'signed')
    """)
