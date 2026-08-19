from odoo import fields, models


class AttendanceDeviceEvent(models.Model):
    _name = "mdl.attendance.device.event"
    _description = "Attendance Device Parsed Event"
    _order = "event_datetime desc, id desc"
    _check_company_auto = True

    log_id = fields.Many2one("mdl.attendance.device.log", required=True, ondelete="cascade", index=True)
    device_id = fields.Many2one("mdl.attendance.device", required=True, ondelete="restrict", index=True, check_company=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)
    device_employee_id = fields.Many2one("mdl.attendance.device.employee", ondelete="set null", index=True, check_company=True)
    employee_id = fields.Many2one("hr.employee", ondelete="set null", index=True, check_company=True)
    device_user_id = fields.Char(readonly=True, index=True)
    event_datetime = fields.Datetime(readonly=True, index=True)
    raw_line = fields.Text(readonly=True)
    raw_punch_state = fields.Char(readonly=True, index=True)
    punch_state = fields.Selection([("in", "כניסה"), ("out", "יציאה"), ("unknown", "לא ידוע")], required=True, default="unknown", readonly=True, index=True)
    event_fingerprint = fields.Char(required=True, readonly=True, index=True)
    processing_state = fields.Selection([
        ("new", "חדש"), ("processed", "עובד"), ("waiting_employee_link", "ממתין לקישור עובד"),
        ("not_applied", "לא יושם"), ("ignored", "התעלם"), ("error", "שגיאה"),
    ], default="new", required=True, readonly=True, index=True)
    processing_message = fields.Text(readonly=True)
    attendance_id = fields.Many2one("hr.attendance", readonly=True, ondelete="set null", index=True)

    def action_process(self):
        from ..services.attendance_processor import AttendanceProcessor
        AttendanceProcessor(self.env).process(self)
        return True
