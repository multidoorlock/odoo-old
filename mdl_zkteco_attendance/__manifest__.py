{
    "name": "Multi Doorlock - ZKTeco Attendance",
    "version": "19.0.3.0.0",
    "summary": "Generic attendance device management with ZKTeco ADMS support",
    "category": "Human Resources/Attendances",
    "license": "LGPL-3",

    "depends": [
        "hr",
        "hr_attendance",
        "hr_payroll",
    ],

    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/attendance_device_views.xml",
        "views/device_employee_views.xml",
        "views/device_command_views.xml",
        "views/device_log_views.xml",
        "views/device_event_views.xml",
        "views/device_sync_wizard_views.xml",
        "views/pending_attendance_wizard_views.xml",
        "views/menu_views.xml",
    ],

    "installable": True,
    "application": True,
    "authoer": "Multi Doorlock",
    "maintainer": "Itay Yosef",
}
