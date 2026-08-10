{
    "name": "Israel - Payroll with Accounting",
    "countries": ["il"],
    "version": "19.0.3.0.0",
    "category": "Human Resources/Payroll",
    "summary": "",
    "description": """
תשלומי שכר להנהלת חשבונות
==========================

    * תשלומי עובד (account.payment) ומחזורי תשלומים
    * התאמות שכר (Salary Adjustments) ששולמו מחוץ לתלוש
    * טאב "עובדים" בהנהלת חשבונות
    """,
    "depends": [
        "l10n_il_hr_payroll",
        "account",
        "accountant",
        "hr_payroll_account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",
        "data/hr_payslip_input_type_data.xml",
        "data/hr_salary_rule_data.xml",
        "views/l10n_il_overpayment_closure_views.xml",
        "views/hr_payslip_views.xml",
        "views/hr_salary_attachment_views.xml",
        "views/l10n_il_salary_adjustment_payment_wizard_views.xml",
        "views/l10n_il_account_payment_views.xml",
        "views/hr_employee_views.xml",
        "views/l10n_il_employee_balance_report_views.xml",
        "views/l10n_il_payslip_run_payment_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "author": "Multi Doorlock LTD.",
    "maintainer": "itay.y@mdl.co.il",
    "post_init_hook": "post_init_hook",
}
