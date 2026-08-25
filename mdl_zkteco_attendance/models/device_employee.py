from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AttendanceDeviceEmployee(models.Model):
    _name = "mdl.attendance.device.employee"
    _description = "Attendance Device Employee Card"
    _order = "device_id, device_user_id, id"
    _check_company_auto = True

    employee_id = fields.Many2one(
        "hr.employee", string="עובד", ondelete="set null", index=True, check_company=True,
    )
    device_id = fields.Many2one(
        "mdl.attendance.device", string="שעון", required=True,
        ondelete="restrict", index=True, check_company=True,
    )
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)
    device_user_id = fields.Char(string="מזהה בשעון", required=True, copy=False, index=True)
    device_name = fields.Char(string="שם בכרטיס", translate=False)
    profile_photo = fields.Image(string="תמונת פרופיל", max_width=1920, max_height=1920)
    device_privilege = fields.Selection(
        [("0", "משתמש רגיל"), ("14", "מנהל מערכת")],
        string="הרשאה בשעון", default="0", required=True,
    )
    verification_mode = fields.Selection(
        [
            ("0", "סיסמה / טביעת אצבע / תג קרבה / פנים"),
            ("1", "טביעת אצבע בלבד"),
            ("2", "מספר עובד בלבד"),
            ("3", "סיסמה"),
            ("4", "תג בלבד"),
            ("5", "טביעת אצבע / סיסמה"),
            ("6", "טביעת אצבע / תג קרבה"),
            ("7", "סיסמה / תג קרבה"),
            ("8", "מספר עובד + טביעת אצבע"),
            ("9", "טביעת אצבע + סיסמה"),
            ("10", "טביעת אצבע + תג קרבה"),
            ("11", "סיסמה + תג קרבה"),
            ("12", "טביעת אצבע + סיסמה + תג קרבה"),
            ("13", "מספר עובד + טביעת אצבע + סיסמה"),
            ("14", "טביעת אצבע + (תג קרבה / מספר עובד)"),
            ("15", "פנים בלבד"),
            ("16", "פנים + טביעת אצבע"),
            ("17", "פנים + סיסמה"),
            ("18", "פנים + תג קרבה"),
            ("19", "פנים + טביעת אצבע + תג קרבה"),
            ("20", "פנים + טביעת אצבע + סיסמה"),
        ],
        string="מצב אימות בשעון", default="0", required=True,
    )
    has_face = fields.Boolean(string="קיים פנים", readonly=True)
    has_fingerprint = fields.Boolean(string="קיימת טביעת אצבע", readonly=True)
    biometric_photo = fields.Image(
        string="תמונה ביומטרית", max_width=1920, max_height=1920,
        groups="mdl_zkteco_attendance.group_attendance_device_manager",
    )
    face_template = fields.Binary(string="תבנית זיהוי פנים", attachment=False, groups="mdl_zkteco_attendance.group_attendance_device_manager")
    face_template_no = fields.Integer(default=4, readonly=True)
    face_template_index = fields.Integer(default=0, readonly=True)
    face_template_major_ver = fields.Integer(default=13, readonly=True)
    face_template_minor_ver = fields.Integer(default=0, readonly=True)
    active = fields.Boolean(default=True)
    link_state = fields.Selection(
        [("needs_employee_link", "דורש קישור לעובד"), ("linked", "מקושר")],
        default="needs_employee_link", required=True, readonly=True, index=True,
    )
    sync_state = fields.Selection(
        [("not_synced", "לא מסונכרן"), ("pending_push", "ממתין לשליחה"),
         ("pending_pull", "ממתין למשיכה"), ("synced", "מסונכרן"), ("error", "שגיאה")],
        default="not_synced", required=True, readonly=True, index=True,
    )
    last_sync_at = fields.Datetime(readonly=True)
    last_sync_error = fields.Text(readonly=True)
    pending_event_count = fields.Integer(compute="_compute_pending_events")
    legacy_employee_id = fields.Many2one("hr.employee", readonly=True, ondelete="set null", copy=False)

    @api.depends("device_name", "device_user_id", "device_id")
    def _compute_display_name(self):
        for card in self:
            name = card.device_name or card.device_user_id or _("כרטיס חדש")
            card.display_name = f"{name} [{card.device_user_id}]" if card.device_user_id else name

    def _required_biometrics_for_verification_mode(self):
        self.ensure_one()
        fingerprint_modes = {"1", "8", "9", "10", "12", "13", "14", "16", "19", "20"}
        face_modes = {"15", "16", "17", "18", "19", "20"}
        return (
            self.verification_mode in face_modes,
            self.verification_mode in fingerprint_modes,
        )

    def _verification_mode_error(self):
        self.ensure_one()
        face_required, fingerprint_required = self._required_biometrics_for_verification_mode()
        missing = []
        if face_required and not self.has_face:
            missing.append(_("פנים"))
        if fingerprint_required and not self.has_fingerprint:
            missing.append(_("טביעת אצבע"))
        if not missing:
            return False
        return _("מצב האימות שנבחר מחייב: %s. יש לסמן שהנתון קיים בכרטיס.") % ", ".join(missing)

    @api.constrains("verification_mode", "has_face", "has_fingerprint")
    def _check_verification_mode_biometrics(self):
        if self.env.context.get("skip_biometric_verification_constraint"):
            return
        for card in self:
            error = card._verification_mode_error()
            if error:
                raise ValidationError(error)

    @api.onchange("verification_mode", "has_face", "has_fingerprint")
    def _onchange_verification_mode_biometrics(self):
        if self.verification_mode and self._verification_mode_error():
            warning = self._verification_mode_error()
            self.verification_mode = "0"
            return {
                "warning": {
                    "title": _("מצב אימות אינו זמין"),
                    "message": warning,
                }
            }

    _device_user_unique = models.Constraint(
        "UNIQUE(device_id, device_user_id)",
        "מזהה המשתמש חייב להיות ייחודי באותו שעון.",
    )

    @api.depends("employee_id")
    def _compute_pending_events(self):
        for card in self:
            card.pending_event_count = len(card._get_valid_attendance_candidates())

    def _get_valid_attendance_candidates(self):
        self.ensure_one()
        if not self.employee_id:
            return []
        events = self.env["mdl.attendance.device.event"].sudo().search([
            ("device_employee_id", "=", self.id),
            ("processing_state", "in", ["waiting_employee_link", "not_applied"]),
            ("punch_state", "in", ["in", "out"]),
            ("event_datetime", "!=", False),
        ], order="event_datetime, id")
        candidates = []
        pending_in = False
        for event in events:
            if event.punch_state == "in":
                pending_in = event
                continue
            if not pending_in:
                continue
            if self._attendance_interval_is_valid(pending_in.event_datetime, event.event_datetime):
                candidates.append((pending_in, event))
            pending_in = False
        if pending_in and self._attendance_interval_is_valid(pending_in.event_datetime, False):
            candidates.append((pending_in, self.env["mdl.attendance.device.event"]))
        return candidates

    def _attendance_interval_is_valid(self, check_in, check_out=False):
        self.ensure_one()
        if not check_in or (check_out and (check_out <= check_in or (check_out - check_in).total_seconds() > 86400)):
            return False
        domain = [("employee_id", "=", self.employee_id.id)]
        if check_out:
            domain += [("check_in", "<", check_out), "|", ("check_out", "=", False), ("check_out", ">", check_in)]
        else:
            domain += ["|", ("check_out", "=", False), ("check_out", ">", check_in)]
        return not self.env["hr.attendance"].sudo().search_count(domain, limit=1)

    @api.constrains("employee_id", "device_id")
    def _check_employee_company(self):
        for card in self:
            if card.employee_id and card.employee_id.company_id != card.device_id.company_id:
                raise ValidationError(_("העובד והשעון חייבים להשתייך לאותה חברה."))

    @api.model
    def _allocate_user_id(self, device):
        # Serialize allocation per device so two simultaneous card creations
        # cannot receive the same next identifier.
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (73119, device.id),
        )
        numeric_ids = [
            int(value)
            for value in self.sudo().search([
                ("device_id", "=", device.id),
                ("device_user_id", "!=", False),
            ]).mapped("device_user_id")
            if value.isdigit()
        ]
        return str(max(numeric_ids, default=0) + 1)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("import_file"):
            for vals in vals_list:
                if not vals.get("device_id"):
                    raise ValidationError(_("בייבוא כרטיסים חובה למפות את השדה שעון."))
                if not vals.get("device_user_id"):
                    raise ValidationError(_("בייבוא כרטיסים חובה למפות את השדה מזהה בשעון."))
        for vals in vals_list:
            device = self.env["mdl.attendance.device"].browse(vals.get("device_id"))
            if not vals.get("device_user_id") and not self.env.context.get("import_file"):
                vals["device_user_id"] = self._allocate_user_id(device)
            if vals.get("employee_id"):
                employee = self.env["hr.employee"].browse(vals["employee_id"]).exists()
                if employee:
                    vals["device_name"] = employee._attendance_device_name(device)
                    vals.setdefault("profile_photo", employee.image_1920)
                vals["link_state"] = "linked"
        cards = super().create(vals_list)
        if not self.env.context.get("attendance_device_discovery"):
            for card in cards:
                card._queue_initial_sync()
        return cards

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "device_id" in fields_list and not values.get("device_id"):
            devices = self.env["mdl.attendance.device"].search([], limit=2)
            if len(devices) == 1:
                values["device_id"] = devices.id
        if "device_user_id" in fields_list and not values.get("device_user_id") and values.get("device_id"):
            values["device_user_id"] = self._allocate_user_id(
                self.env["mdl.attendance.device"].browse(values["device_id"])
            )
        return values

    @api.onchange("device_id")
    def _onchange_device_id_allocate_user_id(self):
        if self.device_id and not self._origin.id:
            self.device_user_id = self._allocate_user_id(self.device_id)
        if self.employee_id and self.device_id:
            self.device_name = self.employee_id._attendance_device_name(self.device_id)

    @api.onchange("employee_id")
    def _onchange_employee_id_set_card_identity(self):
        if self.employee_id:
            self.device_name = self.employee_id._attendance_device_name(self.device_id)
            self.profile_photo = self.employee_id.image_1920
        else:
            self.device_name = False
            self.profile_photo = False

    def _sync_name_from_employee(self):
        for card in self.filtered(lambda item: item.employee_id and item.device_id):
            device_name = card.employee_id._attendance_device_name(card.device_id)
            if card.device_name != device_name:
                card.with_context(skip_employee_name_sync=True).write({
                    "device_name": device_name,
                })
        return True

    def write(self, vals):
        employee_changed = "employee_id" in vals
        identity_changed = employee_changed or "device_id" in vals
        result = super().write(vals)
        if employee_changed:
            for card in self:
                card.with_context(skip_card_sync=True).write({
                    "link_state": "linked" if card.employee_id else "needs_employee_link"
                })
        if identity_changed and not self.env.context.get("skip_employee_name_sync"):
            self._sync_name_from_employee()
        if not self.env.context.get("skip_card_sync"):
            sync_fields = {
                "device_name": "update_name",
                "device_privilege": "update_privilege",
                "verification_mode": "update_verification_mode",
                "profile_photo": "update_profile_photo",
                "biometric_photo": "update_biometric_photo",
            }
            for card in self.filtered(lambda item: item.device_id and item.device_user_id):
                for field_name, command_type in sync_fields.items():
                    if field_name in vals:
                        card._queue_command(command_type)
        return result

    def unlink(self):
        if not self.env.context.get("skip_device_delete_sync"):
            for card in self.filtered(lambda item: item.device_id and item.device_user_id):
                card._queue_command("delete_user")
        return super().unlink()

    def _queue_command(self, command_type):
        for card in self:
            raw = card.device_id._adapter().build_command(command_type, card)
            self.env["mdl.attendance.device.command"].sudo().queue_command(card, command_type, raw)

    def _queue_initial_sync(self):
        for card in self:
            card._queue_command("create_user")
            if card.profile_photo:
                card._queue_command("update_profile_photo")
            if card.biometric_photo:
                card._queue_command("update_biometric_photo")

    def action_open_push_wizard(self):
        self.ensure_one()
        return self.device_id.action_open_sync_wizard()

    def action_open_pull_wizard(self):
        self.ensure_one()
        return self.device_id.action_open_sync_wizard()

    def action_process_pending_attendance(self):
        self.ensure_one()
        return self.env["mdl.attendance.pending.wizard"]._open(self)
