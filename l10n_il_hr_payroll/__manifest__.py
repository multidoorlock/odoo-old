# Part of l10n_il_hr_payroll. Israeli payroll configuration layer on top of standard Odoo.
{
    'name': 'Israel - Payroll',
    'version': '1.0.61',
    'category': 'Human Resources/Payroll',
    'author': 'MDL',
    'summary': 'שכבת הגדרה נוחה מעל מנגנוני השכר, הנוכחות ורשומות העבודה הסטנדרטיים של Odoo',
    'description': """
שכבת התאמה ישראלית למערכת השכר (חלק א').

הגדרת סוג שכר (חודשי / יומי), תעריף יום נוסף ושעות נוספות על גרסת תנאי ההעסקה.
חמישה סוגי לוחות עבודה: נוכחות (שעות קבועות / מכסה יומית / מכסה שבועית) ומשמרות (מכסה יומית / שבועית).
עיבוד נוכחות ליצירת רשומות עבודה מנורמלות: עיגול חצי/יום מלא, הפרדת שעות נוספות בסף 40 דקות,
סיווג יום נוסף, פיצול משמרת ערב לעבודה ושינה, והיעדרות ללא תשלום.
""",
    'depends': [
        'hr_payroll',
        'hr_work_entry_attendance',
        'sign',
    ],
    'data': [
        'security/sign_security.xml',
        'security/hr_employee_form_101_security.xml',
        'security/section_14_security.xml',
        'security/ir.model.access.csv',
        'data/hr_work_entry_type_data.xml',
        'views/hr_employee_section_14_activation_wizard_views.xml',
        'views/hr_employee_section_14_views.xml',
        'views/hr_employee_onboarding_views.xml',
        'data/section_14_data.xml',
        'views/hr_employee_form_101_activation_wizard_views.xml',
        'views/hr_employee_form_101_views.xml',
        'views/sign_item_templates.xml',
        'report/hr_employee_form_101_report.xml',
        'views/hr_employee_views.xml',
        'views/resource_calendar_views.xml',
        'views/res_config_settings_views.xml',
        'views/hr_work_entry_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'l10n_il_hr_payroll/static/src/fields/daily_wage_sync_field.js',
            'l10n_il_hr_payroll/static/src/js/sign_template_guard.js',
            'l10n_il_hr_payroll/static/src/js/form_101_radio.js',
        ],
        'web.assets_frontend': [
            'l10n_il_hr_payroll/static/src/js/form_101_radio.js',
        ],
        'sign.assets_public_sign': [
            'l10n_il_hr_payroll/static/src/js/form_101_radio.js',
        ],
    },
    'license': 'OEEL-1',
    'installable': True,
    'application': False,
}
