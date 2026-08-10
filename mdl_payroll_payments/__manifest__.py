# -*- coding: utf-8 -*-
{
    'name': 'MDL Payroll — תלושים ותשלומים (חלק ב\')',
    'version': '1.0',
    'category': 'Human Resources/Payroll',
    'author': 'MDL',
    'summary': 'חוקי שכר ישראליים, התאמות שכר, תשלומי עובדים, מחזורי תשלום והוראות',
    'description': """
חלק ב' של מערכת השכר הישראלית.

חוקי שכר לפי סוג עובד (ישראלי / פלסטיני / עובד זר), בסיסי מס והפרשות,
מנוע Gross-Up להתאמות נטו, התאמות שכר עם מיפוי בסיסים,
תשלומי עובדים על גבי account.payment, קישור תשלומים לתלושים,
סגירת תשלומי יתר, מחזורי תשלום, הוראות ומחזורי הוראות.
""",
    'depends': [
        'mdl_payroll',
        'hr_payroll_account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/hr_payslip_input_type_data.xml',
        'data/hr_rule_parameter_data.xml',
        'data/hr_payroll_structure_data.xml',
        'data/hr_salary_rule_data.xml',
        'views/hr_employee_views.xml',
        'views/hr_salary_attachment_views.xml',
        'views/hr_payslip_input_type_views.xml',
        'views/account_payment_views.xml',
        'views/hr_payslip_views.xml',
        'wizard/hr_payroll_cycle_type_wizard_views.xml',
        'wizard/hr_payroll_instruction_wizard_views.xml',
        'wizard/hr_payslip_overpayment_close_wizard_views.xml',
        'views/hr_payroll_cycle_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
