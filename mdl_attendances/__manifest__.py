{
    "name": "Multi Doorlock - Attendances",
    "version": "19.0.1.0.1",
    "category": "Human Resources/Attendances",
    "summary": "סיווג משמרות ושכר שעות נוספות לפי נוכחות",
    "description": """
התאמות נוכחות
=============

    * "סוג לוח זמנים לעבודה" (נוכחות/משמרות) ברמת ה-Working Schedule עצמו - בלוח מסוג
      משמרות, נוכחות בפועל מסווגת אוטומטית למשמרת בוקר/ערב לפי שעת הכניסה מול הבלוקים
      (morning/afternoon) שהוגדרו באותו לוח
    * הרחבת Overtime Rulesets הקיים כך שכלל שעות נוספות יחול רק על סוג משמרת מסוים
    * שני סוגי כניסת עבודה חדשים לשכר: נוכחות - משמרת בוקר / ערב (במקום הסוג הכללי "נוכחות") -
      סוג כניסת העבודה בלוח מסונן/מוגבל לפי סוג הלוח (נוכחות/משמרות)
    * שיטת תשלום שעות נוספות מנוכחות (אחוז משווי שעה / סכום קבוע) - ראו l10n_il_hr_payroll,
      שדות l10n_il_overtime_* בעמוד השכר של העובד
    """,
    "depends": [
        "hr_attendance",
        "hr_work_entry_attendance",
        "hr_payroll",
        "l10n_il_hr_payroll",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",
        "data/hr_work_entry_type_data.xml",
        "data/hr_attendance_overtime_data.xml",
        "data/hr_salary_rule_data.xml",
        "views/hr_attendance_overtime_rule_views.xml",
        "views/resource_calendar_views.xml",
        "views/hr_employee_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "author": "Multi Doorlock LTD.",
    "maintainer": "itay.y@mdl.co.il",
}
