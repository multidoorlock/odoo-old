# Part of mdl_payroll. Israeli payroll configuration layer on top of standard Odoo.
{
    'name': 'שכר ישראלי — הגדרות שכר, לוחות עבודה ונוכחות',
    'version': '1.0.1',
    'category': 'Human Resources/Payroll',
    'author': 'MDL',
    'summary': 'שכבת הגדרה נוחה מעל מנגנוני השכר, הנוכחות ורשומות העבודה הסטנדרטיים של Odoo',
    'description': """
שכבת התאמה ישראלית למערכת השכר (חלק א').

הגדרת סוג שכר (חודשי / יומי) ותעריפים (סוף שבוע, יום נוסף, שעות נוספות) על גרסת תנאי ההעסקה.
חמישה סוגי לוחות עבודה: נוכחות (שעות קבועות / מכסה יומית / מכסה שבועית) ומשמרות (מכסה יומית / שבועית).
עיבוד נוכחות ליצירת רשומות עבודה מנורמלות: עיגול חצי/יום מלא, הפרדת שעות נוספות בסף 40 דקות,
סיווג סוף שבוע לפני יום נוסף לפני יום רגיל, פיצול משמרת ערב לעבודה ושינה, והיעדרות ללא תשלום.
""",
    'depends': [
        'hr_payroll',
        'hr_work_entry_attendance',
    ],
    'data': [
        'data/hr_work_entry_type_data.xml',
        'views/hr_employee_views.xml',
        'views/resource_calendar_views.xml',
        'views/res_config_settings_views.xml',
        'views/hr_work_entry_views.xml',
    ],
    'license': 'OEEL-1',
    'installable': True,
    'application': False,
}
