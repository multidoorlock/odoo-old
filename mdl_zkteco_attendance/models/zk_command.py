from odoo import api, fields, models


class ZKTecoCommand(models.Model):
    _name = "mdl.zk.command"
    _description = "ZKTeco Device Command"
    _order = "id desc"

    device_id = fields.Many2one(
        comodel_name="mdl.zk.device",
        string="שעון",
        required=True,
        ondelete="cascade",
        index=True,
    )

    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="עובד",
        ondelete="set null",
        index=True,
    )

    command_type = fields.Selection(
        selection=[
            # Legacy values are kept so old command records remain readable.
            ("pull_user", "משיכת שם (ישן)"),
            ("pull_photo", "משיכת תמונה (ישן)"),
            ("push_user", "שליחת שם"),
            ("push_photo", "שליחת תמונת משתמש"),
            ("custom", "פקודה אחרת"),
        ],
        string="סוג פקודה",
        required=True,
        default="custom",
    )

    command_text = fields.Text(
        string="פקודה",
        required=True,
    )

    state = fields.Selection(
        selection=[
            ("queued", "ממתין"),
            ("sent", "נשלח"),
            ("done", "בוצע"),
            ("failed", "נכשל"),
        ],
        string="מצב",
        required=True,
        default="queued",
        index=True,
    )

    sent_at = fields.Datetime(
        string="נשלח בתאריך",
        readonly=True,
    )

    completed_at = fields.Datetime(
        string="הושלם בתאריך",
        readonly=True,
    )

    return_code = fields.Integer(
        string="Return Code",
        readonly=True,
    )

    response_body = fields.Text(
        string="תשובת השעון",
        readonly=True,
    )

    error_message = fields.Text(
        string="שגיאה",
        readonly=True,
    )

    @api.model
    def queue_command(
        self,
        device,
        command_type,
        command_text,
        employee=None,
    ):
        """
        Keep at most one queued command of the same type for the same
        employee/device. If a newer image/name is saved before the clock polls,
        replace the queued payload with the newest one.
        """
        existing = self.sudo().search(
            [
                ("device_id", "=", device.id),
                (
                    "employee_id",
                    "=",
                    employee.id if employee else False,
                ),
                ("command_type", "=", command_type),
                ("state", "=", "queued"),
            ],
            limit=1,
        )

        if existing:
            existing.sudo().write({
                "command_text": command_text,
                "error_message": False,
            })
            return existing

        return self.sudo().create({
            "device_id": device.id,
            "employee_id": (
                employee.id if employee else False
            ),
            "command_type": command_type,
            "command_text": command_text,
        })

    def get_wire_command(self):
        self.ensure_one()

        return f"C:{self.id}:{self.command_text}"

    def mark_sent(self):
        self.ensure_one()

        self.sudo().write({
            "state": "sent",
            "sent_at": fields.Datetime.now(),
        })

    def mark_result(self, return_code, response_body):
        """
        Mark this command result and update the employee sync status accurately.

        A successful NAME command alone no longer means that the whole employee
        is synchronized if the PHOTO command is still queued/sent.
        """
        self.ensure_one()

        state = "done" if return_code >= 0 else "failed"

        self.sudo().write({
            "state": state,
            "return_code": return_code,
            "response_body": response_body,
            "completed_at": fields.Datetime.now(),
            "error_message": (
                False
                if state == "done"
                else (
                    response_body
                    or f"ZKTeco Return Code: {return_code}"
                )
            ),
        })

        employee = self.employee_id
        if not employee:
            return

        if state == "failed":
            employee.with_context(
                zk_skip_sync=True
            ).sudo().write({
                "zk_sync_state": "error",
                "zk_sync_error": (
                    response_body
                    or f"ZKTeco Return Code: {return_code}"
                ),
            })
            return

        # Do not show "synced" while another outgoing command for the
        # same employee/device is still waiting or was sent without a result.
        remaining = self.sudo().search_count(
            [
                ("id", "!=", self.id),
                ("device_id", "=", self.device_id.id),
                ("employee_id", "=", employee.id),
                ("command_type", "in", ["push_user", "push_photo"]),
                ("state", "in", ["queued", "sent"]),
            ]
        )

        if remaining:
            employee.with_context(
                zk_skip_sync=True
            ).sudo().write({
                "zk_sync_state": "pending_push",
                "zk_sync_error": False,
            })
        else:
            employee.with_context(
                zk_skip_sync=True
            ).sudo().write({
                "zk_sync_state": "synced",
                "zk_last_sync_at": fields.Datetime.now(),
                "zk_sync_error": False,
            })