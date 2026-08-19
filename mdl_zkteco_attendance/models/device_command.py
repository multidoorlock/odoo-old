from odoo import api, fields, models


class AttendanceDeviceCommand(models.Model):
    _name = "mdl.attendance.device.command"
    _description = "Attendance Device Command"
    _order = "id desc"
    _check_company_auto = True

    device_id = fields.Many2one("mdl.attendance.device", required=True, ondelete="restrict", index=True, check_company=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)
    device_employee_id = fields.Many2one("mdl.attendance.device.employee", ondelete="set null", index=True, check_company=True)
    command_type = fields.Selection([
        ("create_user", "יצירת משתמש"), ("update_name", "עדכון שם"),
        ("update_privilege", "עדכון הרשאה"), ("update_verification_mode", "עדכון מצב אימות"),
        ("update_profile_photo", "עדכון תמונת פרופיל"),
        ("update_biometric_photo", "עדכון תמונה ביומטרית"),
        ("request_user", "בקשת פרטי משתמש"),
        ("request_privilege", "בקשת הרשאה"), ("request_verification_mode", "בקשת מצב אימות"),
        ("request_profile_photo", "בקשת תמונת פרופיל"),
        ("request_biometric_photo", "בקשת תמונה ביומטרית"),
        ("request_users", "בקשת כל המשתמשים מהשעון"),
        ("delete_user", "מחיקת משתמש"), ("custom", "פקודה אחרת"),
    ], required=True, default="custom", index=True)
    state = fields.Selection([
        ("queued", "ממתין"), ("sent", "נשלח"), ("done", "בוצע"),
        ("failed", "נכשל"), ("cancelled", "בוטל"),
    ], required=True, default="queued", index=True)
    sent_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    raw_command = fields.Text(required=True)
    raw_response = fields.Text(readonly=True)
    response_log_id = fields.Many2one("mdl.attendance.device.log", readonly=True, ondelete="set null")
    return_code = fields.Integer(readonly=True)
    retry_count = fields.Integer(default=0, readonly=True)
    error_message = fields.Text(readonly=True)
    legacy_command_id = fields.Many2one("mdl.zk.command", readonly=True, ondelete="set null", copy=False)

    @api.model
    def queue_command(self, card, command_type, raw_command):
        existing = self.search([
            ("device_id", "=", card.device_id.id),
            ("device_employee_id", "=", card.id),
            ("command_type", "=", command_type), ("state", "=", "queued"),
        ], limit=1)
        vals = {"raw_command": raw_command, "error_message": False}
        if existing:
            existing.write(vals)
            command = existing
        else:
            vals.update({"device_id": card.device_id.id, "device_employee_id": card.id, "command_type": command_type})
            command = self.create(vals)
        pull_types = {"request_users", "request_user", "request_privilege", "request_verification_mode", "request_profile_photo", "request_biometric_photo"}
        card.with_context(skip_card_sync=True).write({
            "sync_state": "pending_pull" if command_type in pull_types else "pending_push",
            "last_sync_error": False,
        })
        return command

    def get_wire_command(self):
        self.ensure_one()
        return f"C:{self.id}:{self.raw_command}"

    def mark_sent(self):
        self.ensure_one()
        self.write({"state": "sent", "sent_at": fields.Datetime.now()})

    def mark_result(self, return_code, raw_response, response_log=None):
        self.ensure_one()
        state = "done" if return_code >= 0 else "failed"
        error = False if state == "done" else (raw_response or f"Return Code: {return_code}")
        self.write({
            "state": state, "return_code": return_code, "raw_response": raw_response,
            "response_log_id": response_log.id if response_log else False,
            "completed_at": fields.Datetime.now(), "error_message": error,
        })
        self._refresh_card_state()

    def _refresh_card_state(self):
        for command in self:
            card = command.device_employee_id
            if not card:
                continue
            pending_commands = self.search([("device_employee_id", "=", card.id), ("state", "in", ["queued", "sent"])])
            latest_command = self.search([("device_employee_id", "=", card.id)], order="id desc", limit=1)
            if pending_commands:
                pull_types = {"request_users", "request_user", "request_privilege", "request_verification_mode", "request_profile_photo", "request_biometric_photo"}
                state = "pending_pull" if all(command.command_type in pull_types for command in pending_commands) else "pending_push"
                vals = {"sync_state": state, "last_sync_error": False}
            elif latest_command.state == "failed":
                vals = {"sync_state": "error", "last_sync_error": latest_command.error_message}
            else:
                vals = {"sync_state": "synced", "last_sync_at": fields.Datetime.now(), "last_sync_error": False}
            card.with_context(skip_card_sync=True).write(vals)

    def action_retry(self):
        for command in self.filtered(lambda c: c.state in ("failed", "cancelled", "sent")):
            command.write({"state": "queued", "retry_count": command.retry_count + 1, "error_message": False})
            command._refresh_card_state()
        return True

    def action_cancel(self):
        self.filtered(lambda c: c.state in ("queued", "sent")).write({"state": "cancelled", "completed_at": fields.Datetime.now()})
        self._refresh_card_state()
        return True
