from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError


class AttendancePendingWizard(models.TransientModel):
    _name = "mdl.attendance.pending.wizard"
    _description = "Process Valid Pending Attendance Intervals"

    device_employee_id = fields.Many2one(
        "mdl.attendance.device.employee", required=True, readonly=True
    )
    employee_id = fields.Many2one(
        related="device_employee_id.employee_id", string="עובד", readonly=True
    )
    interval_line_ids = fields.One2many(
        "mdl.attendance.pending.wizard.line", "wizard_id", string="רשומות נוכחות תקינות"
    )

    @api.model
    def _open(self, card):
        candidates = card._get_valid_attendance_candidates()
        if not candidates:
            raise UserError(_("לא נמצאו זוגות כניסה/יציאה תקינים שניתן להכניס ל-Odoo."))
        wizard = self.create({
            "device_employee_id": card.id,
            "interval_line_ids": [Command.create({
                "check_in_event_id": check_in_event.id,
                "check_out_event_id": check_out_event.id or False,
            }) for check_in_event, check_out_event in candidates],
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("רשומות נוכחות מוכנות לעיבוד"),
            "res_model": self._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }


class AttendancePendingWizardLine(models.TransientModel):
    _name = "mdl.attendance.pending.wizard.line"
    _description = "Valid Pending Attendance Interval"
    _order = "check_in, id"

    wizard_id = fields.Many2one(
        "mdl.attendance.pending.wizard", required=True, ondelete="cascade"
    )
    check_in_event_id = fields.Many2one(
        "mdl.attendance.device.event", required=True, readonly=True, ondelete="cascade"
    )
    check_out_event_id = fields.Many2one(
        "mdl.attendance.device.event", readonly=True, ondelete="cascade"
    )
    check_in = fields.Datetime(related="check_in_event_id.event_datetime", string="כניסה")
    check_out = fields.Datetime(related="check_out_event_id.event_datetime", string="יציאה")
    interval_type = fields.Selection(
        [("closed", "כניסה ויציאה"), ("open", "כניסה פתוחה")],
        compute="_compute_interval_type", string="סוג"
    )

    @api.depends("check_out_event_id")
    def _compute_interval_type(self):
        for line in self:
            line.interval_type = "closed" if line.check_out_event_id else "open"

    def _reload_wizard(self):
        self.ensure_one()
        card = self.wizard_id.device_employee_id
        if not card._get_valid_attendance_candidates():
            return {"type": "ir.actions.act_window_close"}
        return self.env["mdl.attendance.pending.wizard"]._open(card)

    def action_apply(self):
        self.ensure_one()
        card = self.wizard_id.device_employee_id
        if not card.employee_id:
            raise UserError(_("חובה לקשר תחילה את הכרטיס לעובד."))
        if not card._attendance_interval_is_valid(self.check_in, self.check_out or False):
            raise UserError(_("הרשומה כבר אינה תקינה או שהיא מתנגשת ברשומת נוכחות אחרת."))
        events = self.check_in_event_id | self.check_out_event_id
        events.sudo().write({
            "employee_id": card.employee_id.id,
            "processing_state": "new",
            "processing_message": False,
        })
        events.sorted("event_datetime").action_process()
        failed = events.filtered(lambda event: event.processing_state != "processed")
        if failed:
            raise UserError(failed[0].processing_message or _("Odoo דחה את רשומת הנוכחות."))
        return self._reload_wizard()

    def action_dismiss(self):
        self.ensure_one()
        events = self.check_in_event_id | self.check_out_event_id
        events.sudo().write({
            "processing_state": "ignored",
            "processing_message": "Dismissed permanently by a user",
        })
        return self._reload_wizard()
