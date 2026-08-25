import base64
import binascii
import hashlib

from odoo import api, fields, models


class AttendanceDeviceCommand(models.Model):
    _name = "mdl.attendance.device.command"
    _description = "Attendance Device Command"
    _order = "id desc"
    _check_company_auto = True

    device_id = fields.Many2one("mdl.attendance.device", required=True, ondelete="restrict", index=True, check_company=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)
    device_employee_id = fields.Many2one("mdl.attendance.device.employee", ondelete="set null", index=True, check_company=True)
    fingerprint_index = fields.Selection(
        [(str(index), str(index)) for index in range(10)],
        string="מספר אצבע",
        readonly=True,
        index=True,
    )
    fingerprint_verification_hash = fields.Char(readonly=True, index=True)
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
        ("request_fingerprints", "בקשת מצב טביעות אצבע"),
        ("update_fingerprint", "עדכון טביעת אצבע"),
        ("delete_fingerprint", "מחיקת טביעת אצבע"),
        ("request_face_templates", "בקשת מצב תבניות פנים"),
        ("request_attendance_logs", "בקשת השלמת רשומות נוכחות"),
        ("update_device_language", "עדכון שפת השעון"),
        ("request_device_language", "בקשת שפת השעון"),
        ("update_device_cooldown", "עדכון Cooldown בשעון"),
        ("request_device_cooldown", "בקשת Cooldown מהשעון"),
        ("request_device_options", "בקשת הגדרות השעון"),
        ("reload_device_options", "טעינה מחדש של הגדרות השעון"),
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
        pull_types = {"request_users", "request_user", "request_privilege", "request_verification_mode", "request_profile_photo", "request_biometric_photo", "request_fingerprints"}
        card.with_context(skip_card_sync=True).write({
            "sync_state": "pending_pull" if command_type in pull_types else "pending_push",
            "last_sync_error": False,
        })
        return command

    @staticmethod
    def _fingerprint_payload_hash(payload):
        if not payload:
            return False
        if isinstance(payload, str):
            payload = payload.encode("ascii")
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, UnicodeEncodeError, ValueError, TypeError):
            raw = payload
        return hashlib.sha256(raw).hexdigest()

    @api.model
    def queue_fingerprint_verification(self, card, fingerprint_index, payload=False):
        """Read a pushed slot back before declaring the card synchronized."""
        fingerprint_index = str(fingerprint_index)
        domain = [
            ("device_id", "=", card.device_id.id),
            ("device_employee_id", "=", card.id),
            ("command_type", "=", "request_fingerprints"),
            ("fingerprint_index", "=", fingerprint_index),
            ("state", "in", ["queued", "sent"]),
        ]
        existing = self.search(domain, order="id desc", limit=1)
        values = {
            "raw_command": f"DATA QUERY BIODATA Pin={card.device_user_id}",
            "fingerprint_verification_hash": self._fingerprint_payload_hash(payload),
            "error_message": False,
        }
        if existing:
            if existing.state == "sent":
                existing.write({
                    "state": "cancelled",
                    "completed_at": fields.Datetime.now(),
                })
                existing = False
            else:
                existing.write(values)
        if not existing:
            values.update({
                "device_id": card.device_id.id,
                "device_employee_id": card.id,
                "fingerprint_index": fingerprint_index,
                "command_type": "request_fingerprints",
                "state": "queued",
            })
            existing = self.create(values)
        card.with_context(skip_card_sync=True).write({
            "sync_state": "pending_pull",
            "last_sync_error": False,
        })
        return existing

    @api.model
    def queue_device_command(self, device, command_type, raw_command):
        """Queue a device-level setting/query without creating duplicates."""
        existing = self.search([
            ("device_id", "=", device.id),
            ("device_employee_id", "=", False),
            ("command_type", "=", command_type),
            ("state", "=", "queued"),
        ], order="id desc", limit=1)
        values = {"raw_command": raw_command, "error_message": False}
        if existing:
            existing.write(values)
            return existing
        values.update({
            "device_id": device.id,
            "command_type": command_type,
            "state": "queued",
        })
        return self.create(values)

    @api.model
    def queue_fingerprint_command(
        self, card, fingerprint_index, command_type, raw_command
    ):
        """Queue one command per finger without overwriting another finger."""
        opposite_type = {
            "update_fingerprint": "delete_fingerprint",
            "delete_fingerprint": "update_fingerprint",
        }[command_type]
        domain = [
            ("device_id", "=", card.device_id.id),
            ("device_employee_id", "=", card.id),
            ("fingerprint_index", "=", str(fingerprint_index)),
            ("state", "=", "queued"),
        ]
        opposite = self.search(domain + [("command_type", "=", opposite_type)])
        if opposite:
            opposite.write({
                "state": "cancelled",
                "completed_at": fields.Datetime.now(),
            })
        command = self.search(
            domain + [("command_type", "=", command_type)], limit=1
        )
        values = {
            "raw_command": raw_command,
            "error_message": False,
            "fingerprint_index": str(fingerprint_index),
        }
        if command:
            command.write(values)
        else:
            values.update({
                "device_id": card.device_id.id,
                "device_employee_id": card.id,
                "command_type": command_type,
                "state": "queued",
            })
            command = self.create(values)
        card.with_context(skip_card_sync=True).write({
            "sync_state": "pending_push",
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
        fingerprint_verification = (
            self.command_type == "request_fingerprints"
            and bool(self.device_employee_id)
            and self.fingerprint_index is not False
        )
        if (
            fingerprint_verification
            and return_code >= 0
            and not self.env.context.get("fingerprint_payload_verified")
        ):
            # DATA QUERY is asynchronous: Return=0 only acknowledges the query.
            # Keep waiting until /iclock/cdata posts the actual BIODATA row.
            if self.state != "done":
                self.write({
                    "state": "sent",
                    "return_code": return_code,
                    "raw_response": raw_response,
                    "response_log_id": response_log.id if response_log else False,
                    "error_message": False,
                })
                self._refresh_card_state()
            return
        state = "done" if return_code >= 0 else "failed"
        error = False if state == "done" else (raw_response or f"Return Code: {return_code}")
        self.write({
            "state": state, "return_code": return_code, "raw_response": raw_response,
            "response_log_id": response_log.id if response_log else False,
            "completed_at": fields.Datetime.now(), "error_message": error,
        })
        if (
            state == "done"
            and self.command_type == "update_biometric_photo"
            and self.device_employee_id
        ):
            # A successful BIOPHOTO update/delete is authoritative for this
            # card.  Previously the command completed but the readonly flag
            # stayed unchanged until a later BIODATA upload happened.
            self.device_employee_id.with_context(
                skip_card_sync=True,
                skip_biometric_verification_constraint=True,
            ).write({"has_face": bool(self.device_employee_id.biometric_photo)})
        if (
            state == "done"
            and self.command_type in ("update_fingerprint", "delete_fingerprint")
            and self.device_employee_id
            and self.fingerprint_index is not False
        ):
            fingerprint = self.env[
                "mdl.attendance.device.fingerprint"
            ].sudo().search([
                ("device_employee_id", "=", self.device_employee_id.id),
                ("finger_index", "=", self.fingerprint_index),
            ], limit=1)
            payload = (
                fingerprint._template_payload()
                if self.command_type == "update_fingerprint" and fingerprint
                else False
            )
            self.sudo().queue_fingerprint_verification(
                self.device_employee_id,
                self.fingerprint_index,
                payload,
            )
        self._refresh_card_state()

    def _refresh_card_state(self):
        for command in self:
            card = command.device_employee_id
            if not card:
                continue
            pending_commands = self.search([("device_employee_id", "=", card.id), ("state", "in", ["queued", "sent"])])
            latest_command = self.search([("device_employee_id", "=", card.id)], order="id desc", limit=1)
            if pending_commands:
                pull_types = {"request_users", "request_user", "request_privilege", "request_verification_mode", "request_profile_photo", "request_biometric_photo", "request_fingerprints"}
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
