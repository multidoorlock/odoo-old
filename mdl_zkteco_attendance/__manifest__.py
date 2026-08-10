{
    "name": "Multi Doorlock - ZKTeco Attendance",
    "version": "19.0.2.0.0",
    "summary": "Direct ZKTeco ADMS integration with Odoo",
    "category": "Human Resources/Attendances",
    "license": "LGPL-3",

    "depends": [
        "hr",
        "hr_attendance",
        "hr_payroll",
    ],

    "data": [
        "security/ir.model.access.csv",

        "views/hr_employee_views.xml",
        "views/zk_device_views.xml",
        "views/zk_command_views.xml",
        "views/zk_raw_log_views.xml",
        "views/zk_menu_views.xml",
    ],

    "installable": True,
    "application": False,
}