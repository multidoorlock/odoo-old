# -*- coding: utf-8 -*-
{
    'name': 'Israel - Payroll With Accounting',
    'version': '1.4.46',
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
        'wizard/payroll_reconciliation_wizard_views.xml',
        'views/hr_payslip_views.xml',
        'wizard/payslip_run_payment_wizard_views.xml',
        'wizard/payment_cycle_wizard_views.xml',
        'wizard/masav_export_wizard_views.xml',
        'views/payment_cycle_views.xml',
        # Replace legacy batch arches before validating the new batch sibling.
        'views/hr_payslip_run_views.xml',
        'views/payroll_batch_payment_selection_views.xml',
        'views/hr_attendance_overtime_rule_views.xml',
        'views/menus.xml',
        'views/employee_accounting_navigation.xml',
        'report/batch_employee_payments.xml',
        'data/hr_hebrew_translations.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'l10n_il_hr_payroll_account/static/src/components/payslip_link_amount/payslip_link_amount.js',
            'l10n_il_hr_payroll_account/static/src/components/payslip_allocation_list/payslip_allocation_list.js',
            'l10n_il_hr_payroll_account/static/src/components/payslip_allocation_list/payslip_allocation_list.xml',
            'l10n_il_hr_payroll_account/static/src/components/quick_split_lines/quick_split_lines.js',
            'l10n_il_hr_payroll_account/static/src/components/quick_split_lines/quick_split_lines.xml',
            'l10n_il_hr_payroll_account/static/src/components/payrun_card/payrun_card.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
