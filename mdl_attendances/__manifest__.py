{
    "name": "Multi Doorlock - Attendances",
    "version": "19.0.1.1.9",
    "category": "Human Resources/Attendances",
    "summary": "Split attendances into effective work and non-work intervals",
    "author": "MDL",
    "license": "LGPL-3",
    "depends": ["hr_attendance"],
    "data": [
        "security/hr_attendance_segment_security.xml",
        "security/ir.model.access.csv",
        "views/hr_attendance_segment_rule_views.xml",
        "views/hr_attendance_views.xml",
        "views/hr_version_views.xml",
        "views/hr_attendance_overtime_rule_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mdl_attendances/static/src/scss/attendance_segment_timeline.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
