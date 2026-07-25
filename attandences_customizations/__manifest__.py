{
    "name": "התאמות נוכחות",
    "version": "19.0.3.0.0",
    "category": "Human Resources/Attendances",
    "summary": "סיווג משמרות ושכר שעות נוספות לפי נוכחות",
    "description": """
התאמות נוכחות
=============

    * סיווג אוטומטי של רישום נוכחות למשמרת בוקר/ערב לפי שעת הכניסה (חוקי משמרות), רק לעובד
      שסוג רשומת הנוכחות שלו הוא "משמרות"
    * הרחבת Overtime Rulesets הקיים כך שכלל שעות נוספות יחול רק על סוג משמרת מסוים
    * שני סוגי כניסת עבודה חדשים לשכר: נוכחות - משמרת בוקר / ערב (במקום הסוג הכללי "נוכחות")
    * שדה "שכר לשעה נוספת" בעמוד השכר של העובד, וכלל שכר המחשב את התשלום על שעות נוספות
      מנוכחות לפי שעה זו (ולא לפי אחוז מהשכר הרגיל)
    """,
    "depends": [
        "hr_attendance",
        "hr_work_entry_attendance",
        "l10n_il_hr_payroll",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",
        "data/hr_work_entry_type_data.xml",
        "data/hr_attendance_classification_data.xml",
        "data/hr_attendance_overtime_data.xml",
        "data/hr_salary_rule_data.xml",
        "views/hr_attendance_classification_views.xml",
        "views/hr_attendance_overtime_rule_views.xml",
        "views/hr_version_views.xml",
        "views/hr_attendance_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "author": "Multi Doorlock LTD.",
    "maintainer": "itay.y@mdl.co.il",
}
