from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AttendanceDeviceSyncWizard(models.TransientModel):
    _name = "mdl.attendance.device.sync.wizard"
    _description = "Attendance Device Synchronization"

    device_id = fields.Many2one("mdl.attendance.device", required=True, readonly=True)
    direction = fields.Selection([("push", "שליחה לשעון"), ("pull", "משיכה מהשעון")], required=True, readonly=True)
    selection_mode = fields.Selection([("all", "כל הכרטיסים המקושרים"), ("selected", "כרטיסים נבחרים")], default="all", required=True)
    device_employee_ids = fields.Many2many(
        "mdl.attendance.device.employee", "mdl_att_device_sync_card_rel",
        "wizard_id", "card_id", string="כרטיסים",
        domain="[('device_id', '=', device_id)]",
    )
    sync_name = fields.Boolean(string="שם", default=True)
    sync_privilege = fields.Boolean(string="הרשאה", default=False)
    sync_verification_mode = fields.Boolean(string="מצב אימות", default=False)
    sync_profile_photo = fields.Boolean(string="תמונת פרופיל", default=True)
    sync_biometric_photo = fields.Boolean(string="תבנית זיהוי פנים", default=False)

    @api.model
    def _open(self, device, direction, card=None):
        wizard = self.create({
            "device_id": device.id, "direction": direction,
            "selection_mode": "selected" if card else "all",
            "device_employee_ids": [(6, 0, card.ids)] if card else False,
        })
        return {
            "type": "ir.actions.act_window", "name": _("סנכרון שעון נוכחות"),
            "res_model": self._name, "res_id": wizard.id, "view_mode": "form", "target": "new",
        }

    def action_confirm(self):
        self.ensure_one()
        cards = self.device_employee_ids if self.selection_mode == "selected" else self.device_id.device_employee_ids.filtered("active")
        if not cards:
            raise UserError(_("לא נמצאו כרטיסים לסנכרון."))
        types = []
        prefix = "update" if self.direction == "push" else "request"
        if self.sync_name:
            types.append(f"{prefix}_name" if self.direction == "push" else "request_user")
        if self.sync_privilege:
            types.append("update_privilege" if self.direction == "push" else "request_privilege")
        if self.sync_verification_mode:
            types.append("update_verification_mode" if self.direction == "push" else "request_verification_mode")
        if self.sync_profile_photo:
            types.append(f"{prefix}_profile_photo" if self.direction == "push" else "request_profile_photo")
        if self.sync_biometric_photo and self.direction == "push":
            types.append(f"{prefix}_biometric_photo" if self.direction == "push" else "request_biometric_photo")
        for card in cards:
            for command_type in dict.fromkeys(types):
                card._queue_command(command_type)
            if self.direction == "pull":
                card.with_context(skip_card_sync=True).write({"sync_state": "pending_pull"})
                if self.sync_biometric_photo and self.direction == "push":
                    adapter = card.device_id._adapter()
                    if hasattr(adapter, "apply_latest_face_template"):
                        adapter.apply_latest_face_template(card)
        return {"type": "ir.actions.act_window_close"}
