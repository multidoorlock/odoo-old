import uuid

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AttendanceConflictEventWizard(models.TransientModel):
    _name = "mdl.attendance.conflict.event.wizard"
    _description = "Create a Manual Attendance Event"

    employee_id = fields.Many2one("hr.employee", string="עובד", required=True)
    device_id = fields.Many2one("mdl.attendance.device", string="שעון", required=True)
    punch_state = fields.Selection(
        [("in", "כניסה"), ("out", "יציאה")], string="סוג אירוע", required=True,
    )
    event_datetime = fields.Datetime(string="תאריך ושעה", required=True)
    attendance_id = fields.Many2one("hr.attendance", readonly=True)

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        employee = self.env["hr.employee"].browse(values.get("employee_id"))
        if employee and not values.get("device_id"):
            card = self.env["mdl.attendance.device.employee"].search([
                ("employee_id", "=", employee.id), ("active", "=", True),
            ], order="last_sync_at desc, id", limit=1)
            if card:
                values["device_id"] = card.device_id.id
        return values

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        if self.employee_id:
            card = self.env["mdl.attendance.device.employee"].search([
                ("employee_id", "=", self.employee_id.id), ("active", "=", True),
            ], order="last_sync_at desc, id", limit=1)
            self.device_id = card.device_id if card else False

    def action_create_event(self):
        self.ensure_one()
        card = self.env["mdl.attendance.device.employee"].search([
            ("employee_id", "=", self.employee_id.id),
            ("device_id", "=", self.device_id.id),
            ("active", "=", True),
        ], order="last_sync_at desc, id", limit=1)
        if not card:
            raise UserError(_("לא נמצא לעובד כרטיס פעיל בשעון שנבחר."))
        log = self.env["mdl.attendance.device.log"].sudo().create({
            "device_id": self.device_id.id,
            "device_identifier": self.device_id.device_identifier,
            "request_type": "MANUAL",
            "http_method": "MANUAL",
            "endpoint": "attendance-conflict-timeline",
            "processing_state": "processed",
            "processing_message": "Manual attendance event created by a manager",
        })
        event = self.env["mdl.attendance.device.event"].sudo().create({
            "log_id": log.id,
            "device_id": self.device_id.id,
            "device_employee_id": card.id,
            "employee_id": self.employee_id.id,
            "device_user_id": card.device_user_id,
            "event_datetime": self.event_datetime,
            "raw_line": "Manual attendance event",
            "raw_punch_state": self.punch_state,
            "punch_state": self.punch_state,
            "event_fingerprint": "manual:%s" % uuid.uuid4().hex,
            "processing_state": "not_applied",
            "processing_message": "Manual attendance event",
        })
        event._timeline_reconcile_employee_ids([self.employee_id.id])
        return {"type": "ir.actions.act_window_close"}
