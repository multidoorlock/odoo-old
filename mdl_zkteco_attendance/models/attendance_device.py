from datetime import timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AttendanceDevice(models.Model):
    _name = "mdl.attendance.device"
    _description = "Attendance Device"
    _order = "name, id"
    _check_company_auto = True

    _LANGUAGE_TO_DEVICE = {"he_IL": "72", "ar_001": "66", "en_US": "69"}
    _DEVICE_TO_LANGUAGE = {value: key for key, value in _LANGUAGE_TO_DEVICE.items()}

    name = fields.Char(string="שם", required=True)
    manufacturer = fields.Selection(
        [
            ("zkteco", "ZKTeco"),
            ("hikvision", "Hikvision"),
            ("anviz", "Anviz"),
            ("suprema", "Suprema"),
            ("jbclock", "JBClock"),
        ],
        string="יצרן",
        required=True,
        default="zkteco",
        index=True,
    )
    device_identifier = fields.Char(
        string="מזהה ייחודי", required=True, copy=False, index=True
    )
    company_id = fields.Many2one(
        "res.company", string="חברה", required=True,
        default=lambda self: self.env.company, index=True,
    )
    active = fields.Boolean(default=True)
    last_seen_at = fields.Datetime(string="נראה לאחרונה", readonly=True)
    last_ip = fields.Char(string="IP אחרון", readonly=True)
    timezone = fields.Selection(
        selection=lambda self: self._tz_get(), string="אזור זמן",
        default=lambda self: self.env.company.resource_calendar_id.tz or self.env.user.tz or "UTC",
        required=True,
    )
    device_language = fields.Selection(
        [
            ("he_IL", "עברית"),
            ("ar_001", "ערבית"),
            ("en_US", "אנגלית"),
        ],
        string="שפה",
        required=True,
        default="he_IL",
    )
    auto_discover_users = fields.Boolean(default=True)
    auto_push_new_cards = fields.Boolean(default=True)
    auto_sync_name = fields.Boolean(default=True)
    auto_sync_profile_photo = fields.Boolean(default=True)
    auto_sync_biometric_photo = fields.Boolean(default=False)
    auto_reconcile_attendance = fields.Boolean(
        string="סנכרון השלמת נוכחות שעתי", default=True,
        help="מבקש מהשעון מדי שעה רשומות נוכחות שאולי לא הגיעו בזמן ניתוק.",
    )
    attendance_reconcile_lookback_days = fields.Integer(
        string="ימי משיכה ראשונית", default=30,
        help="מספר הימים למשיכה כאשר עדיין לא התקבלה אף רשומת נוכחות מהשעון.",
    )
    attendance_cooldown_minutes = fields.Integer(
        string="Cooldown החתמות (דקות)",
        default=0,
        help=(
            "החתמה נוספת של אותו כרטיס ומאותו סוג (כניסה/יציאה) "
            "בתוך החלון תישמר בלוג אך תסונן מעיבוד הנוכחות. 0 מבטל את הסינון."
        ),
    )
    last_attendance_sync_at = fields.Datetime(
        string="סנכרון נוכחות אחרון", readonly=True,
    )
    last_automatic_sync_at = fields.Datetime(
        string="סנכרון אוטומטי אחרון", readonly=True,
    )

    # Explicit firmware mapping. Never infer a direction from open attendance.
    punch_in_values = fields.Char(
        string="ערכי Punch לכניסה",
        default="0",
        help="ערכים מופרדים בפסיקים כפי שנשלחים בעמודת Punch State.",
    )
    punch_out_values = fields.Char(
        string="ערכי Punch ליציאה",
        default="1",
        help="ערכים מופרדים בפסיקים כפי שנשלחים בעמודת Punch State.",
    )
    punch_state_column = fields.Integer(
        string="אינדקס עמודת Punch State", default=2, required=True,
        help="אינדקס מבוסס אפס בשורת ATTLOG. יש לאשר מול payload אמיתי של IN ו-OUT.",
    )

    attendance_stamp = fields.Char(default="0", readonly=True)
    operation_stamp = fields.Char(default="0", readonly=True)
    photo_stamp = fields.Char(default="0", readonly=True)
    default_photo_type = fields.Char(default="2")
    device_employee_ids = fields.One2many(
        "mdl.attendance.device.employee", "device_id", string="כרטיסי עובדים"
    )
    command_ids = fields.One2many(
        "mdl.attendance.device.command", "device_id", string="פקודות"
    )
    legacy_device_id = fields.Many2one(
        "mdl.zk.device", string="מכשיר ישן", readonly=True, ondelete="set null", copy=False
    )

    _device_identifier_unique = models.Constraint(
        "UNIQUE(manufacturer, device_identifier)",
        "מזהה המכשיר חייב להיות ייחודי עבור היצרן.",
    )
    _attendance_cooldown_nonnegative = models.Constraint(
        "CHECK(attendance_cooldown_minutes >= 0)",
        "Cooldown ההחתמות לא יכול להיות שלילי.",
    )

    @api.model
    def _tz_get(self):
        return [(tz, tz) for tz in __import__("pytz").all_timezones]

    @api.constrains("attendance_cooldown_minutes")
    def _check_attendance_cooldown_minutes(self):
        for device in self:
            if device.attendance_cooldown_minutes < 0:
                raise ValidationError(_("Cooldown ההחתמות לא יכול להיות שלילי."))

    @api.model
    def get_or_create_from_request(self, manufacturer, device_identifier, remote_ip=None):
        identifier = (device_identifier or "").strip()
        if not identifier:
            return self.browse()
        device = self.sudo().search([
            ("manufacturer", "=", manufacturer),
            ("device_identifier", "=", identifier),
        ], limit=1)
        vals = {"last_seen_at": fields.Datetime.now(), "last_ip": remote_ip or False}
        if device:
            device.write(vals)
            return device
        vals.update({
            "name": f"{dict(self._fields['manufacturer'].selection).get(manufacturer, manufacturer)} {identifier}",
            "manufacturer": manufacturer,
            "device_identifier": identifier,
            "company_id": self.env.company.id,
        })
        return self.sudo().create(vals)

    def _adapter(self):
        self.ensure_one()
        from ..services.adapters import get_adapter
        return get_adapter(self)

    def write(self, vals):
        language_changed = "device_language" in vals
        cooldown_changed = "attendance_cooldown_minutes" in vals
        result = super().write(vals)
        if language_changed:
            self.mapped("device_employee_ids")._sync_name_from_employee()
        if not self.env.context.get("skip_device_setting_sync"):
            for device in self.filtered(lambda item: item.manufacturer == "zkteco"):
                if language_changed:
                    device._queue_device_language_push()
                if cooldown_changed:
                    device._queue_device_cooldown_push()
                if language_changed or cooldown_changed:
                    device._queue_device_options_reload()
        return result

    def _queue_device_language_push(self):
        """Send the selected terminal language using PUSH 3.x syntax."""
        self.ensure_one()
        return self._queue_device_command(
            "update_device_language",
            "SET OPTIONS Language=%s" % self._LANGUAGE_TO_DEVICE[self.device_language],
        )

    def _queue_device_cooldown_push(self):
        """Set the terminal's duplicate-punch interval in minutes.

        On this ZAM70/MB560-VL firmware ``RecheckMin`` selects minutes as
        the unit while ``AlarmReRec`` contains the actual interval.  Sending
        only ``ReCheckMin=<minutes>`` changes the unit flag and therefore does
        not update the value shown by the terminal.
        """
        self.ensure_one()
        return self._queue_device_command(
            "update_device_cooldown",
            "SET OPTIONS RecheckMin=1,AlarmReRec=%s"
            % self.attendance_cooldown_minutes,
        )

    def _queue_current_device_settings(self):
        """Queue all device-level values maintained by this module."""
        queued = self.env["mdl.attendance.device.command"].browse()
        for device in self.filtered(lambda item: item.manufacturer == "zkteco"):
            queued |= device._queue_device_language_push()
            queued |= device._queue_device_cooldown_push()
            queued |= device._queue_device_options_reload()
        return queued

    def _queue_device_command(self, command_type, raw_command):
        self.ensure_one()
        return self.env["mdl.attendance.device.command"].sudo().queue_device_command(
            self, command_type, raw_command,
        )

    def _queue_device_options_reload(self):
        """Keep RELOAD OPTIONS behind every still-queued option update."""
        self.ensure_one()
        Command = self.env["mdl.attendance.device.command"].sudo()
        stale_reload = Command.search([
            ("device_id", "=", self.id),
            ("command_type", "=", "reload_device_options"),
            ("state", "=", "queued"),
        ])
        if stale_reload:
            stale_reload.write({
                "state": "cancelled",
                "completed_at": fields.Datetime.now(),
            })
        return self._queue_device_command("reload_device_options", "RELOAD OPTIONS")

    def _device_setting_push_pending(self, command_type):
        self.ensure_one()
        return bool(self.env["mdl.attendance.device.command"].sudo().search_count([
            ("device_id", "=", self.id),
            ("command_type", "=", command_type),
            ("state", "in", ["queued", "sent"]),
        ], limit=1))

    def _apply_reported_language(self, raw_language):
        self.ensure_one()
        language = self._DEVICE_TO_LANGUAGE.get(str(raw_language or "").strip())
        if (
            language
            and language != self.device_language
            and not self._device_setting_push_pending("update_device_language")
        ):
            self.with_context(skip_device_setting_sync=True).write({
                "device_language": language,
            })
        return language

    def _apply_reported_cooldown(self, raw_cooldown):
        self.ensure_one()
        try:
            cooldown = max(0, int(str(raw_cooldown).strip()))
        except (TypeError, ValueError):
            return False
        if (
            cooldown != self.attendance_cooldown_minutes
            and not self._device_setting_push_pending("update_device_cooldown")
        ):
            self.with_context(skip_device_setting_sync=True).write({
                "attendance_cooldown_minutes": cooldown,
            })
        return cooldown

    def _queue_automatic_sync(self, force=False):
        """Queue fallback reconciliation; real-time OPERLOG remains the fast path."""
        Command = self.env["mdl.attendance.device.command"].sudo()
        now = fields.Datetime.now()
        queued = Command.browse()
        for device in self.filtered(lambda item: item.active and item.manufacturer == "zkteco"):
            if (
                not force
                and device.last_automatic_sync_at
                and device.last_automatic_sync_at > now - timedelta(hours=1)
            ):
                continue
            requests = (
                ("request_users", "DATA QUERY USERINFO"),
                ("request_fingerprints", "DATA QUERY FINGERTMP"),
                ("request_face_templates", "DATA QUERY BIODATA"),
                # PUSH 3.1.2 posts the result asynchronously to
                # /iclock/querydata?type=options.
                (
                    "request_device_options",
                    "GET OPTIONS Language,RecheckMin,AlarmReRec",
                ),
            )
            for command_type, raw_command in requests:
                if Command.search_count([
                    ("device_id", "=", device.id),
                    ("command_type", "=", command_type),
                    ("state", "in", ["queued", "sent"]),
                ], limit=1):
                    continue
                queued |= device._queue_device_command(command_type, raw_command)
            device.with_context(skip_device_setting_sync=True).write({
                "last_automatic_sync_at": now,
            })
        return queued

    def action_open_sync_wizard(self):
        self.ensure_one()
        return self.env["mdl.attendance.device.sync.wizard"]._open(self)

    # Kept as API aliases for existing bookmarks/custom actions.  The form now
    # exposes one synchronization button and the direction is chosen inside it.
    def action_open_push_wizard(self):
        return self.action_open_sync_wizard()

    def action_open_pull_wizard(self):
        return self.action_open_sync_wizard()

    def action_discover_users(self):
        self.ensure_one()
        existing = self.env["mdl.attendance.device.command"].sudo().search([
            ("device_id", "=", self.id),
            ("command_type", "=", "request_users"),
            ("state", "in", ["queued", "sent"]),
        ], limit=1)
        if not existing:
            self.env["mdl.attendance.device.command"].sudo().create({
                "device_id": self.id,
                "command_type": "request_users",
                "state": "queued",
                "raw_command": "DATA QUERY USERINFO",
            })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("משיכת משתמשים מהשעון"),
                "message": _("הבקשה נשלחה. הכרטיסים יופיעו לאחר שהשעון יחזיר את רשימת המשתמשים."),
                "type": "success",
                "sticky": False,
            },
        }

    def _attendance_reconcile_command(self):
        self.ensure_one()
        now = fields.Datetime.now()
        start = self.last_attendance_sync_at or (
            now - timedelta(days=max(self.attendance_reconcile_lookback_days, 1))
        )
        # Re-read an overlap window. Event fingerprints make this idempotent
        # and protect records posted around a disconnect/reconnect boundary.
        start -= timedelta(hours=1)
        timezone = pytz.timezone(self.timezone or "UTC")

        def local_text(value):
            aware = pytz.utc.localize(value).astimezone(timezone)
            return aware.strftime("%Y-%m-%d %H:%M:%S")

        return (
            f"DATA QUERY ATTLOG StartTime={local_text(start)}"
            f"\tEndTime={local_text(now)}"
        )

    def _queue_attendance_reconciliation(self):
        Command = self.env["mdl.attendance.device.command"].sudo()
        queued = Command.browse()
        for device in self.filtered(lambda item: item.active and item.manufacturer == "zkteco"):
            existing = Command.search([
                ("device_id", "=", device.id),
                ("command_type", "=", "request_attendance_logs"),
                ("state", "in", ["queued", "sent"]),
            ], order="id desc", limit=1)
            if existing:
                # A sent command can be stranded if the terminal disconnects
                # before acknowledging it. Retry it after two hours.
                if existing.state == "sent" and existing.sent_at and existing.sent_at < fields.Datetime.now() - timedelta(hours=2):
                    existing.write({
                        "state": "queued", "sent_at": False,
                        "retry_count": existing.retry_count + 1,
                        "raw_command": device._attendance_reconcile_command(),
                        "error_message": False,
                    })
                queued |= existing
                continue
            queued |= Command.create({
                "device_id": device.id,
                "command_type": "request_attendance_logs",
                "state": "queued",
                "raw_command": device._attendance_reconcile_command(),
            })
        return queued

    def action_reconcile_attendance(self):
        self.ensure_one()
        command = self._queue_attendance_reconciliation()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("סנכרון רשומות נוכחות"),
                "message": _("בקשת ההשלמה ממתינה לשעון ותישלח כשהוא מחובר."),
                "type": "success" if command else "warning",
                "sticky": False,
            },
        }

    @api.model
    def _cron_reconcile_attendance(self):
        devices = self.sudo().search([
            ("active", "=", True),
            ("manufacturer", "=", "zkteco"),
        ])
        devices._queue_attendance_reconciliation()
        devices._queue_automatic_sync()

    @api.ondelete(at_uninstall=False)
    def _prevent_history_deletion(self):
        for device in self:
            if self.env["mdl.attendance.device.log"].sudo().search_count([("device_id", "=", device.id)], limit=1):
                raise UserError(_("לא ניתן למחוק שעון עם היסטוריה. יש להעביר אותו לארכיון."))
