# -*- coding: utf-8 -*-
{
    'name': 'Israel - Payroll With Accounting',
    'version': '1.4.28',
    'category': 'Human Resources/Payroll',
    'author': 'MDL',
    'summary': 'חוקי שכר ישראליים, התאמות שכר ותשלומי עובדים ישירים',
    'description': """
חלק ב' של מערכת השכר הישראלית.

חוקי שכר לפי סוג עובד (ישראלי / פלסטיני / עובד זר), בסיסי מס והפרשות,
מנוע Gross-Up להתאמות נטו, התאמות שכר עם מיפוי בסיסים,
תשלומי עובדים על גבי account.payment, כאשר שורות הפיצול מתזמנות התאמות
חשבונאיות מקוריות של Odoo מול פקודות היומן של התלושים.
""",
    'depends': [
        'l10n_il_hr_payroll',
        'hr_payroll_account',
        'account_batch_payment',
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
        'views/res_config_settings_views.xml',
        'views/account_payment_views.xml',
        'views/account_partial_reconcile_views.xml',
        'views/hr_payslip_views.xml',
        'views/hr_payslip_run_views.xml',
        'wizard/payment_cycle_wizard_views.xml',
        'wizard/masav_export_wizard_views.xml',
        'views/payment_cycle_views.xml',
        'views/hr_attendance_overtime_rule_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'l10n_il_hr_payroll_account/static/src/components/quick_split_lines/quick_split_lines.js',
            'l10n_il_hr_payroll_account/static/src/components/quick_split_lines/quick_split_lines.xml',
            'l10n_il_hr_payroll_account/static/src/components/payrun_card/payrun_card.xml',
            'l10n_il_hr_payroll_account/static/src/components/grouped_batch_payments/grouped_batch_payments.js',
            'l10n_il_hr_payroll_account/static/src/components/grouped_batch_payments/grouped_batch_payments.xml',
            'l10n_il_hr_payroll_account/static/src/components/grouped_batch_payments/grouped_batch_payments.scss',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
