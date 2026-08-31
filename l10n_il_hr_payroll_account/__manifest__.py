# -*- coding: utf-8 -*-
{
    'name': 'MDL Payroll — תלושים ותשלומים (חלק ב\')',
    'version': '1.2.1',
    'category': 'Human Resources/Payroll',
    'author': 'MDL',
    'summary': 'חוקי שכר ישראליים, התאמות שכר ותשלומי עובדים ישירים',
    'description': """
חלק ב' של מערכת השכר הישראלית.

חוקי שכר לפי סוג עובד (ישראלי / פלסטיני / עובד זר), בסיסי מס והפרשות,
מנוע Gross-Up להתאמות נטו, התאמות שכר עם מיפוי בסיסים,
תשלומי עובדים על גבי account.payment, פריסה אחידה דרך שורות משיכה וקישורן לתלושים.
""",
    'depends': [
        'l10n_il_hr_payroll',
        'hr_payroll_account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_payslip_input_type_data.xml',
        'data/hr_payroll_structure_data.xml',
        'data/hr_salary_rule_data.xml',
        'data/hr_payroll_sync_data.xml',
        'views/hr_employee_views.xml',
        'views/hr_salary_attachment_views.xml',
        'views/hr_payslip_input_type_views.xml',
        'views/account_payment_views.xml',
        'views/hr_payslip_views.xml',
        'wizard/hr_payslip_payment_draw_wizard_views.xml',
        'views/hr_attendance_overtime_rule_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'l10n_il_hr_payroll_account/static/src/components/quick_split_lines/quick_split_lines.js',
            'l10n_il_hr_payroll_account/static/src/components/quick_split_lines/quick_split_lines.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
