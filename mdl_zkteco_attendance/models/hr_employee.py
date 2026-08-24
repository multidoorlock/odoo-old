from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    name = fields.Char(
        string="Employee Name",
        related=False,
        store=True,
        readonly=False,
        required=True,
        tracking=True,
        translate=True,
    )

    # Legacy fields are intentionally retained for migration compatibility.
    # New synchronization always goes through mdl.attendance.device.employee.
    zk_attendance_enabled = fields.Boolean(string="שעון נוכחות (ישן)", default=False)
    zk_device_id = fields.Many2one("mdl.zk.device", string="שעון (ישן)", ondelete="restrict")
    zk_user_id = fields.Char(string="מזהה בשעון (ישן)", copy=False, index=True)
    zk_sync_state = fields.Selection([
        ("not_linked", "לא מקושר"), ("pending_pull", "ממתין למשיכה"),
        ("pending_push", "ממתין לשליחה"), ("synced", "מסונכרן"), ("error", "שגיאה"),
    ], default="not_linked", readonly=True, copy=False)
    zk_last_sync_at = fields.Datetime(readonly=True, copy=False)
    zk_sync_error = fields.Text(readonly=True, copy=False)
    zk_photo_type = fields.Char(readonly=True, copy=False)
    attendance_device_card_ids = fields.One2many(
        "mdl.attendance.device.employee", "employee_id", string="כרטיסי שעוני נוכחות"
    )

    def _prepare_resource_values(self, vals, tz):
        # hr.employee normally removes name because it is a related field in
        # standard Odoo. Here the employee name is a native translated field,
        # so keep it for the employee row after creating the resource.
        employee_name = vals.get("name")
        resource_values = super()._prepare_resource_values(vals, tz)
        if employee_name is not None:
            vals["name"] = employee_name
        return resource_values

    def _attendance_device_name(self, device):
        self.ensure_one()
        if not device:
            return self.name
        # A newly-created Odoo.sh database initially has only en_US enabled.
        # The clock can already be configured for Hebrew or Arabic, but Odoo
        # rejects an inactive language code in ``env.lang``.  Use the clock
        # language when it is active and otherwise keep the employee's current
        # Odoo-language name until that language is installed.
        language = self.env["res.lang"]._lang_get(device.device_language)
        language_code = language.code if language else (self.env.lang or "en_US")
        return self.with_context(lang=language_code).name or self.name

    def _sync_attendance_device_card_names(self):
        for employee in self:
            employee.attendance_device_card_ids.sudo()._sync_name_from_employee()

    def _sync_attendance_resource_names(self):
        for employee in self.filtered("resource_id"):
            resource_name = employee.with_context(lang="en_US").name or employee.name
            if employee.resource_id.name != resource_name:
                employee.resource_id.name = resource_name

    def write(self, vals):
        name_changed = "name" in vals
        result = super().write(vals)
        if name_changed:
            self._sync_attendance_resource_names()
            self._sync_attendance_device_card_names()
        return result

    def update_field_translations(self, field_name, translations, source_lang=""):
        result = super().update_field_translations(
            field_name, translations, source_lang=source_lang,
        )
        if field_name == "name":
            self._sync_attendance_resource_names()
            self._sync_attendance_device_card_names()
        return result

    def action_zk_push_user(self):
        """Legacy entry point: never synchronize employee fields directly."""
        return {
            "type": "ir.actions.act_window",
            "name": "כרטיסי שעוני נוכחות",
            "res_model": "mdl.attendance.device.employee",
            "view_mode": "list,form",
            "domain": [("employee_id", "in", self.ids)],
        }
