{
    "name": "Multi Doorlock - ZKTeco Attendance",
    "version": "19.0.1.0.0",
    "summary": "Direct ADMS connection between ZKTeco devices and Odoo",
    "category": "Human Resources/Attendances",
    "license": "LGPL-3",
    "depends": [
        "hr_attendance",
    ],
    "data": [
    "security/ir.model.access.csv",
    "views/zk_raw_log_views.xml",
    ],
    "installable": True,
    "application": False,
}