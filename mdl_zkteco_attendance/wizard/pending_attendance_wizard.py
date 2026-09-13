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
        events, card = self._scoped_events()
        self.env["mdl.attendance.device.event"]._timeline_lock_employee_ids(card.employee_id.ids)
        events.invalidate_recordset()
        if not card.employee_id:
            raise UserError(_("חובה לקשר תחילה את הכרטיס לעובד."))
        current_pairs = {
            (check_in.id, check_out.id or False)
            for check_in, check_out in card._get_valid_attendance_candidates()
        }
        if (self.check_in_event_id.id, self.check_out_event_id.id or False) not in current_pairs:
            raise UserError(_("האירועים השתנו או הוסתרו. יש לפתוח מחדש את רשימת הנוכחות הממתינה."))
        if not card._attendance_interval_is_valid(self.check_in, self.check_out or False):
            raise UserError(_("הרשומה כבר אינה תקינה או שהיא מתנגשת ברשומת נוכחות אחרת."))
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

    def _scoped_events(self):
        """Allow a card operator to act only on this owned wizard's card."""
        self.ensure_one()
        self.check_access("write")
        card = self.wizard_id.device_employee_id
        card.check_access("write")
        # Operators can manage their cards without general access to the
        # event model.  Check the card before reading source records with sudo,
        # and never accept an event from another card/company in this popup.
        events = (self.check_in_event_id | self.check_out_event_id).sudo().exists()
        if not events or any(
            event.device_employee_id != card
            or event.device_id != card.device_id
            or event.company_id != card.company_id
            for event in events
        ):
            raise UserError(_("אפשר להסתיר כאן רק אירועים של הכרטיס שנבחר."))
        return events, card

    def action_dismiss(self):
        events, _card = self._scoped_events()
        # Use the same payroll guards, pairing repair and atomic bulk action
        # as the timeline.  A stale popup may now refer to saved attendance.
        self.env["mdl.attendance.device.event"].sudo()._timeline_exclude_events(events)
        return self._reload_wizard()
