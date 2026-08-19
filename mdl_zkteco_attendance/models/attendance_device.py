from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AttendanceDevice(models.Model):
    _name = "mdl.attendance.device"
    _description = "Attendance Device"
    _order = "name, id"
    _check_company_auto = True

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
    auto_discover_users = fields.Boolean(default=True)
    auto_push_new_cards = fields.Boolean(default=True)
    auto_sync_name = fields.Boolean(default=True)
    auto_sync_profile_photo = fields.Boolean(default=True)
    auto_sync_biometric_photo = fields.Boolean(default=False)

    # Explicit firmware mapping. Never infer a direction from open attendance.
    punch_in_values = fields.Char(
        string="ערכי Punch לכניסה",
        help="ערכים מופרדים בפסיקים כפי שנשלחים בעמודת Punch State.",
    )
    punch_out_values = fields.Char(
        string="ערכי Punch ליציאה",
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

    @api.model
    def _tz_get(self):
        return [(tz, tz) for tz in __import__("pytz").all_timezones]

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

    def action_open_push_wizard(self):
        self.ensure_one()
        return self.env["mdl.attendance.device.sync.wizard"]._open(self, "push")

    def action_open_pull_wizard(self):
        self.ensure_one()
        return self.env["mdl.attendance.device.sync.wizard"]._open(self, "pull")

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

    @api.ondelete(at_uninstall=False)
    def _prevent_history_deletion(self):
        for device in self:
            if self.env["mdl.attendance.device.log"].sudo().search_count([("device_id", "=", device.id)], limit=1):
                raise UserError(_("לא ניתן למחוק שעון עם היסטוריה. יש להעביר אותו לארכיון."))
