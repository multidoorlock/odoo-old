import base64
import io

from PIL import Image

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # -------------------------------------------------------------------------
    # ZKTeco link
    # -------------------------------------------------------------------------

    zk_attendance_enabled = fields.Boolean(
        string="שעון נוכחות",
        default=False,
        help="מסמן שהעובד מקושר לשעון נוכחות ZKTeco.",
    )

    zk_device_id = fields.Many2one(
        comodel_name="mdl.zk.device",
        string="שעון",
        ondelete="restrict",
        help="שעון ה-ZKTeco שאליו העובד מקושר.",
    )

    zk_user_id = fields.Char(
        string="מזהה עובד בשעון",
        copy=False,
        index=True,
        help="מזהה העובד כפי שהוא מוגדר בתוך שעון ZKTeco.",
    )

    # -------------------------------------------------------------------------
    # Sync status
    # -------------------------------------------------------------------------

    zk_sync_state = fields.Selection(
        selection=[
            ("not_linked", "לא מקושר"),
            ("pending_pull", "ממתין למשיכה (ישן)"),
            ("pending_push", "ממתין לשליחה"),
            ("synced", "מסונכרן"),
            ("error", "שגיאה"),
        ],
        string="מצב סנכרון",
        default="not_linked",
        readonly=True,
        copy=False,
    )

    zk_last_sync_at = fields.Datetime(
        string="סנכרון אחרון",
        readonly=True,
        copy=False,
    )

    zk_sync_error = fields.Text(
        string="שגיאת סנכרון",
        readonly=True,
        copy=False,
    )

    # Kept for compatibility with the previous BIOPHOTO experiment.
    # It is NOT used by USERPIC.
    zk_photo_type = fields.Char(
        string="ZKTeco Photo Type",
        readonly=True,
        copy=False,
    )

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    @api.constrains(
        "zk_attendance_enabled",
        "zk_device_id",
        "zk_user_id",
    )
    def _check_zkteco_configuration(self):
        for employee in self:
            if not employee.zk_attendance_enabled:
                continue

            if not employee.zk_device_id:
                raise ValidationError(
                    _("יש לבחור שעון נוכחות.")
                )

            if not employee.zk_user_id:
                raise ValidationError(
                    _("יש להזין מזהה עובד בשעון.")
                )

            duplicate = self.sudo().search(
                [
                    ("id", "!=", employee.id),
                    ("zk_attendance_enabled", "=", True),
                    ("zk_device_id", "=", employee.zk_device_id.id),
                    ("zk_user_id", "=", employee.zk_user_id),
                ],
                limit=1,
            )

            if duplicate:
                raise ValidationError(
                    _(
                        "מזהה העובד %(user_id)s כבר משויך "
                        "לעובד %(employee)s באותו שעון."
                    )
                    % {
                        "user_id": employee.zk_user_id,
                        "employee": duplicate.display_name,
                    }
                )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _zk_can_push(self):
        self.ensure_one()

        return bool(
            self.zk_attendance_enabled
            and self.zk_device_id
            and self.zk_user_id
        )

    def _zk_clean_name(self):
        self.ensure_one()

        return (
            (self.name or "")
            .replace("\r", " ")
            .replace("\n", " ")
            .replace("\t", " ")
            .strip()
        )

    # -------------------------------------------------------------------------
    # Name PUSH: Odoo -> ZKTeco
    # -------------------------------------------------------------------------

    def _zk_queue_push_name(self):
        Command = self.env["mdl.zk.command"].sudo()

        for employee in self:
            if not employee._zk_can_push():
                continue

            command_text = (
                "DATA UPDATE USERINFO "
                f"PIN={employee.zk_user_id}"
                f"\tName={employee._zk_clean_name()}"
            )

            Command.queue_command(
                device=employee.zk_device_id,
                employee=employee,
                command_type="push_user",
                command_text=command_text,
            )

    # -------------------------------------------------------------------------
    # User Photo PUSH: Odoo -> ZKTeco
    # -------------------------------------------------------------------------

    def _zk_prepare_user_photo(self):
        """
        Prepare Odoo image_1920 as a small JPEG.

        IMPORTANT:
        This is the displayed USER PHOTO path.
        It does NOT send BIOPHOTO, BIODATA or a face template.
        """
        self.ensure_one()

        if not self.image_1920:
            return False

        try:
            raw_image = base64.b64decode(self.image_1920)

            image = Image.open(io.BytesIO(raw_image))
            image = image.convert("RGB")
            image.thumbnail((320, 320))

            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=85,
                optimize=True,
            )

            photo_bytes = output.getvalue()

            return {
                "raw": photo_bytes,
                "base64": base64.b64encode(
                    photo_bytes
                ).decode("ascii"),
            }

        except Exception:
            return False

    def _zk_queue_push_user_photo(self):
        """
        Queue the displayed user/profile photo.

        We intentionally use USERPIC here and never BIOPHOTO.
        This is a controlled protocol test for the physical clock firmware.
        """
        Command = self.env["mdl.zk.command"].sudo()

        for employee in self:
            if not employee._zk_can_push():
                continue

            prepared = employee._zk_prepare_user_photo()
            if not prepared:
                continue

            command_text = (
                "DATA UPDATE USERPIC "
                f"PIN={employee.zk_user_id}"
                f"\tSize={len(prepared['raw'])}"
                f"\tContent={prepared['base64']}"
            )

            Command.queue_command(
                device=employee.zk_device_id,
                employee=employee,
                command_type="push_photo",
                command_text=command_text,
            )

    # -------------------------------------------------------------------------
    # Manual button
    # -------------------------------------------------------------------------

    def action_zk_push_user(self):
        """
        Send the current Odoo name + displayed user photo to the clock.

        Nothing is sent directly over the network here.
        Commands are queued; the clock receives them on its next
        /iclock/getrequest poll.
        """
        for employee in self:
            if not employee._zk_can_push():
                raise ValidationError(
                    _(
                        "כדי לשלוח לשעון יש לסמן שעון נוכחות, "
                        "לבחור שעון ולהזין מזהה עובד בשעון."
                    )
                )

            employee._zk_queue_push_name()
            employee._zk_queue_push_user_photo()

            employee.with_context(
                zk_skip_sync=True
            ).sudo().write({
                "zk_sync_state": "pending_push",
                "zk_sync_error": False,
            })

        return True

    # -------------------------------------------------------------------------
    # Automatic PUSH on create
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)

        if self.env.context.get("zk_skip_sync"):
            return employees

        for employee in employees:
            if employee._zk_can_push():
                employee._zk_queue_push_name()
                employee._zk_queue_push_user_photo()

                employee.with_context(
                    zk_skip_sync=True
                ).sudo().write({
                    "zk_sync_state": "pending_push",
                    "zk_sync_error": False,
                })

        return employees

    # -------------------------------------------------------------------------
    # Automatic PUSH on save
    # -------------------------------------------------------------------------

    def write(self, vals):
        """
        Odoo is the source of truth.

        - Link changed -> send current name and current user photo.
        - Name changed -> send name.
        - image_1920 changed -> send USERPIC.
        """
        if self.env.context.get("zk_skip_sync"):
            return super().write(vals)

        link_fields = {
            "zk_attendance_enabled",
            "zk_device_id",
            "zk_user_id",
        }

        link_changed = bool(
            link_fields.intersection(vals.keys())
        )

        name_changed = "name" in vals
        image_changed = "image_1920" in vals

        result = super().write(vals)

        for employee in self:
            if not employee.zk_attendance_enabled:
                employee.with_context(
                    zk_skip_sync=True
                ).sudo().write({
                    "zk_sync_state": "not_linked",
                    "zk_sync_error": False,
                })
                continue

            if link_changed:
                if employee._zk_can_push():
                    employee._zk_queue_push_name()
                    employee._zk_queue_push_user_photo()

                    employee.with_context(
                        zk_skip_sync=True
                    ).sudo().write({
                        "zk_sync_state": "pending_push",
                        "zk_sync_error": False,
                    })

                continue

            queued_push = False

            if name_changed and employee._zk_can_push():
                employee._zk_queue_push_name()
                queued_push = True

            if image_changed and employee._zk_can_push():
                employee._zk_queue_push_user_photo()
                queued_push = True

            if queued_push:
                employee.with_context(
                    zk_skip_sync=True
                ).sudo().write({
                    "zk_sync_state": "pending_push",
                    "zk_sync_error": False,
                })

        return result