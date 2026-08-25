from odoo import api, fields, models, _


class AttendanceDeviceSyncWizard(models.TransientModel):
    _name = "mdl.attendance.device.sync.wizard"
    _description = "Attendance Device Synchronization"

    device_id = fields.Many2one("mdl.attendance.device", required=True, readonly=True)
    direction = fields.Selection(
        [("pull", "משיכה"), ("push", "שליחה")],
        string="כיוון",
        required=True,
        default="pull",
    )

    @api.model
    def _open(self, device):
        wizard = self.create({"device_id": device.id})
        return {
            "type": "ir.actions.act_window", "name": _("סנכרון שעון נוכחות"),
            "res_model": self._name, "res_id": wizard.id, "view_mode": "form", "target": "new",
        }

    def action_confirm(self):
        self.ensure_one()
        device = self.device_id
        cards = device.device_employee_ids.filtered("active")
        if self.direction == "push":
            device._queue_current_device_settings()
            for card in cards:
                # USERINFO contains name, privilege and verification mode.
                # Empty photos deliberately queue DELETE so the clock becomes
                # an exact mirror of Odoo.
                card._queue_command("create_user")
                card._queue_command("update_profile_photo")
                card._queue_command("update_biometric_photo")
                card.fingerprint_ids._queue_push()
        else:
            # The bulk requests also discover users created directly on the
            # terminal and refresh fingerprint/face enrollment flags.  A
            # BIOPHOTO request is intentionally never queued: this terminal
            # cannot return that comparison image.
            device._queue_automatic_sync(force=True)
            device._queue_attendance_reconciliation()
            for card in cards:
                card._queue_command("request_profile_photo")
        return {"type": "ir.actions.act_window_close"}
