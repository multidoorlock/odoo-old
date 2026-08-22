from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

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

    def action_zk_push_user(self):
        """Legacy entry point: never synchronize employee fields directly."""
        return {
            "type": "ir.actions.act_window",
            "name": "כרטיסי שעוני נוכחות",
            "res_model": "mdl.attendance.device.employee",
            "view_mode": "list,form",
            "domain": [("employee_id", "in", self.ids)],
        }
