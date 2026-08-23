from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AttendanceDeviceEmployee(models.Model):
    _name = "mdl.attendance.device.employee"
    _description = "Attendance Device Employee Card"
    _order = "device_id, device_user_id, id"
    _check_company_auto = True

    def _default_device_name_lang_id(self):
        language = self.env["res.lang"]._lang_get(self.env.lang)
        return language or self.env["res.lang"].search([], limit=1)

    employee_id = fields.Many2one(
        "hr.employee", string="עובד", ondelete="set null", index=True, check_company=True,
    )
    device_id = fields.Many2one(
        "mdl.attendance.device", string="שעון", required=True,
        ondelete="restrict", index=True, check_company=True,
    )
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)
    device_user_id = fields.Char(string="מזהה בשעון", required=True, readonly=True, copy=False, index=True)
    device_name = fields.Char(string="שם בכרטיס", translate=True)
    device_name_lang_id = fields.Many2one(
        "res.lang",
        string="שפת השם בשעון",
        required=True,
        default=_default_device_name_lang_id,
        domain=[("active", "=", True)],
    )
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
        for vals in vals_list:
            device = self.env["mdl.attendance.device"].browse(vals.get("device_id"))
            if not vals.get("device_user_id"):
                vals["device_user_id"] = self._allocate_user_id(device)
            if vals.get("employee_id"):
                employee = self.env["hr.employee"].browse(vals["employee_id"]).exists()
                if employee:
                    vals.setdefault("device_name", employee.name)
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

    @api.onchange("employee_id")
    def _onchange_employee_id_set_card_identity(self):
        if not self._origin.id:
            self.device_name = self.employee_id.name if self.employee_id else False
            self.profile_photo = self.employee_id.image_1920 if self.employee_id else False

    def get_device_name_language_code(self):
        self.ensure_one()
        language = self.device_name_lang_id or self.env["res.lang"]._lang_get(self.env.lang)
        return language.code

    def set_device_name_language_code(self, lang_code):
        self.ensure_one()
        language = self.env["res.lang"]._lang_get(lang_code)
        if not language:
            raise ValidationError(_("השפה שנבחרה אינה פעילה במערכת."))
        self.write({"device_name_lang_id": language.id})
        return True

    def _device_name_for_clock(self):
        self.ensure_one()
        language_code = self.get_device_name_language_code()
        return self.with_context(lang=language_code).device_name

    def write(self, vals):
        employee_changed = "employee_id" in vals
        result = super().write(vals)
        if employee_changed:
            for card in self:
                card.with_context(skip_card_sync=True).write({
                    "link_state": "linked" if card.employee_id else "needs_employee_link"
                })
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
            if not card.device_id.auto_push_new_cards:
                continue
            card._queue_command("create_user")
            if card.device_id.auto_sync_profile_photo and card.profile_photo:
                card._queue_command("update_profile_photo")
            if card.device_id.auto_sync_biometric_photo and card.biometric_photo:
                card._queue_command("update_biometric_photo")

    def action_open_push_wizard(self):
        self.ensure_one()
        return self.env["mdl.attendance.device.sync.wizard"]._open(self.device_id, "push", self)

    def action_open_pull_wizard(self):
        self.ensure_one()
        return self.env["mdl.attendance.device.sync.wizard"]._open(self.device_id, "pull", self)

    def action_process_pending_attendance(self):
        self.ensure_one()
        return self.env["mdl.attendance.pending.wizard"]._open(self)
