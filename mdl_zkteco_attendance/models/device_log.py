from odoo import fields, models


class AttendanceDeviceLog(models.Model):
    _name = "mdl.attendance.device.log"
    _description = "Attendance Device Raw Log"
    _order = "received_at desc, id desc"
    _check_company_auto = True

    received_at = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    device_id = fields.Many2one("mdl.attendance.device", readonly=True, ondelete="set null", index=True, check_company=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)
    device_identifier = fields.Char(readonly=True, index=True)
    request_type = fields.Char(readonly=True, index=True)
    http_method = fields.Char(readonly=True)
    endpoint = fields.Char(readonly=True)
    headers = fields.Text(readonly=True)
    body = fields.Text(readonly=True)
    body_binary = fields.Binary(readonly=True, attachment=True)
    query_string = fields.Text(readonly=True)
    remote_ip = fields.Char(readonly=True)
    processing_state = fields.Selection([
        ("new", "חדש"), ("processed", "עובד"), ("waiting_employee_link", "ממתין לקישור עובד"),
        ("not_applied", "לא יושם"), ("ignored", "התעלם"), ("error", "שגיאה"),
    ], default="new", readonly=True, index=True)
    processing_message = fields.Text(readonly=True)
    command_id = fields.Many2one("mdl.attendance.device.command", readonly=True, ondelete="set null")
    event_ids = fields.One2many("mdl.attendance.device.event", "log_id")
    legacy_log_id = fields.Many2one("mdl.zk.raw.log", readonly=True, ondelete="set null", copy=False)
