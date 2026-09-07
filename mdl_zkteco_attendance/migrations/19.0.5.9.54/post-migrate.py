from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Give existing Odoo attendances the same endpoint events as new ones."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Attendance = env["hr.attendance"].with_context(
        active_test=False,
        tracking_disable=True,
    )
    last_id = 0
    while True:
        attendances = Attendance.search(
            [("id", ">", last_id), ("check_in", "!=", False)],
            order="id",
            limit=500,
        )
        if not attendances:
            break
        attendances._ensure_attendance_device_events()
        last_id = attendances[-1].id
