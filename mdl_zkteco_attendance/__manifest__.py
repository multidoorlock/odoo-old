{
    "name": "Multi Doorlock - Clock Attendance",
    "version": "19.0.5.9.45",
    "summary": "Generic attendance device management",
    "category": "Human Resources/Attendances",
    "license": "LGPL-3",

    "depends": [
        "web",
        "hr",
        "hr_attendance",
        "hr_attendance_gantt",
        "hr_payroll",
    ],

    "data": [
        "data/asset_data.xml",
        "data/attendance_reconcile_cron.xml",
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/attendance_device_views.xml",
        "views/device_employee_views.xml",
        "views/device_command_views.xml",
        "views/device_log_views.xml",
        "views/device_event_views.xml",
        "views/conflict_event_wizard_views.xml",
        "views/attendance_conflict_views.xml",
        "views/device_sync_wizard_views.xml",
        "views/pending_attendance_wizard_views.xml",
        "views/menu_views.xml",
    ],

    "assets": {
        "web.assets_backend": [
            "mdl_zkteco_attendance/static/src/device_employee_view_preference.js",
        ],
        "web.assets_backend_lazy": [
            "mdl_zkteco_attendance/static/src/conflict_timeline/conflict_timeline.js",
            "mdl_zkteco_attendance/static/src/conflict_timeline/conflict_timeline.xml",
            "mdl_zkteco_attendance/static/src/conflict_timeline/conflict_timeline.scss",
        ],
    },

    "installable": True,
    "application": True,
    "author": "Multi Doorlock",
    "maintainer": "Itay Yosef",
}
