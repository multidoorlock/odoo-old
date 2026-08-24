{
    "name": "Israel - Payroll",
    "countries": ["il"],
    "version": "19.0.9.0.1",
    "category": "Human Resources/Payroll",
    "summary":"",
    "description": """
לוקליזציית שכר לישראל
=====================

    * מבני שכר לעובד חודשי ולעובד שעתי/יומי
    * סוגי כניסות עבודה ללא תשלום: חל״ת והיעדרות בלתי מאושרת
    * שדות עובד ישראליים: קטגוריית עובד, נקודות זיכוי, תושבות, תיאום מס, טופס 101
    * פרמטרים מתוארכים לשנת המס: מדרגות מס, ביטוח לאומי, שכר מינימום, פנסיה
    """,
    "depends": [
        "hr_payroll",
        "hr_work_entry",
        "hr_work_entry_holidays",
        "hr_payroll_holidays",
    ],
    "auto_install": ["hr_payroll"],
    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",
        "data/resource_calendar_data.xml",
        "data/hr_work_entry_type_data.xml",
        "data/hr_salary_rule_category_data.xml",
        "data/hr_payroll_structure_type_data.xml",
        "data/hr_payroll_structure_data.xml",
        "data/hr_payslip_input_type_data.xml",
        "data/hr_leave_type_data.xml",
        "data/hr_salary_rule_data.xml",
        "data/hr_rule_parameters_data.xml",
        "data/ir_cron_data.xml",
        "report/l10n_il_form101_report.xml",
        "views/l10n_il_form101_views.xml",
        "views/l10n_il_payslip_report_views.xml",
        "views/hr_payslip_views.xml",
        "views/hr_employee_views.xml",
        "views/hr_work_entry_type_views.xml",
        "views/res_company_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "author": "Multi Doorlock LTD.",
    "maintainer": "itay.y@mdl.co.il",
}
