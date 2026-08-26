import base64
import binascii
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AttendanceDeviceFingerprint(models.Model):
    _name = "mdl.attendance.device.fingerprint"
    _description = "Attendance Device Fingerprint Template"
    _order = "device_employee_id, finger_index, id"
    _check_company_auto = True

    device_employee_id = fields.Many2one(
        "mdl.attendance.device.employee",
        string="כרטיס עובד",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    device_id = fields.Many2one(
        related="device_employee_id.device_id",
        store=True,
        index=True,
    )
    company_id = fields.Many2one(
        related="device_employee_id.company_id",
        store=True,
        index=True,
    )
    finger_index = fields.Selection(
        [(str(index), str(index)) for index in range(10)],
        string="מספר אצבע בשעון",
        required=True,
        default="0",
        help=(
            "זהו חריץ התבנית 0–9 שבו הטביעה נשמרת בשעון. "
            "במשיכה מהשעון השורה והמספר נוצרים אוטומטית; כשבוחרים קובץ ושומרים, "
            "הוא נשלח אוטומטית לשעון לפי המספר שבשורה."
        ),
    )
    template_file = fields.Binary(
        string="קובץ טביעת אצבע",
        required=True,
        attachment=False,
    )
    filename = fields.Char(string="שם קובץ")
    source = fields.Selection(
        [("odoo", "Odoo"), ("device", "שעון")],
        string="מקור",
        default="odoo",
        required=True,
        readonly=True,
    )
    template_size = fields.Integer(
        string="גודל תבנית",
        compute="_compute_template_size",
    )
    last_sync_at = fields.Datetime(string="סנכרון אחרון", readonly=True)
    biodata_index = fields.Integer(default=0, readonly=True)
    major_version = fields.Integer(default=13, readonly=True)
    minor_version = fields.Integer(default=0, readonly=True)
    template_format = fields.Integer(default=0, readonly=True)
    is_duress = fields.Boolean(default=False, readonly=True)
    finger_index_locked = fields.Boolean(
        compute="_compute_finger_index_locked",
        readonly=True,
    )

    _card_finger_unique = models.Constraint(
        "UNIQUE(device_employee_id, finger_index)",
        "אפשר לשמור רק תבנית אחת לכל מספר אצבע באותו כרטיס.",
    )

    @api.depends("template_file")
    def _compute_template_size(self):
        for fingerprint in self:
            try:
                fingerprint.template_size = len(
                    base64.b64decode(fingerprint.template_file or b"", validate=True)
                )
            except (binascii.Error, ValueError, TypeError):
                fingerprint.template_size = 0

    def _compute_finger_index_locked(self):
        for fingerprint in self:
            fingerprint.finger_index_locked = bool(fingerprint.id)

    def _extract_ini_payload(self, text):
        """Extract this card/finger's FPT_n value from a ZKTeco INI backup."""
        self.ensure_one()
        device_user_id = self.device_employee_id.device_user_id or ""
        target_section = f"user_{device_user_id}".lower()
        target_key = f"FPT_{self.finger_index}".upper()
        current_section = False
        contains_user_sections = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            section_match = re.fullmatch(r"\[([^]]+)\]", line)
            if section_match:
                current_section = section_match.group(1).strip().lower()
                contains_user_sections |= current_section.startswith("user_")
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().upper() != target_key:
                continue
            current_user_id = (
                current_section[5:]
                if current_section and current_section.startswith("user_")
                else ""
            )
            same_numeric_user = (
                current_user_id.isdigit()
                and device_user_id.isdigit()
                and int(current_user_id) == int(device_user_id)
            )
            if (
                not contains_user_sections
                or current_section == target_section
                or same_numeric_user
            ):
                return value.strip()
        if contains_user_sections:
            raise ValidationError(_(
                "בקובץ הגיבוי לא נמצאה %s תחת [User_%s]."
            ) % (target_key, self.device_employee_id.device_user_id))
        return False

    def _template_payload(self):
        """Return the base64 payload expected by BIODATA.

        Odoo Binary fields contain base64 of the uploaded file.  The uploaded
        file may itself be raw ZK template bytes, a text file containing the
        template's base64, or a full ZKTeco INI backup with FPT_n entries.
        """
        self.ensure_one()
        encoded_file = self.template_file or b""
        if isinstance(encoded_file, str):
            encoded_file = encoded_file.encode("ascii")
        try:
            raw_file = base64.b64decode(encoded_file, validate=True)
        except (binascii.Error, ValueError, TypeError) as exc:
            raise ValidationError(_("קובץ טביעת האצבע אינו קובץ Binary תקין.")) from exc
        if not raw_file:
            raise ValidationError(_("קובץ טביעת האצבע ריק."))

        text = False
        for encoding in ("utf-8-sig", "cp1255", "latin-1"):
            try:
                text = raw_file.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        candidate = self._extract_ini_payload(text) if text else False
        if not candidate and text:
            stripped = "".join(text.split())
            if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", stripped or ""):
                candidate = stripped
        if candidate:
            try:
                base64.b64decode(candidate.encode("ascii"), validate=True)
            except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
                raise ValidationError(_("תבנית טביעת האצבע בקובץ אינה Base64 תקין.")) from exc
            return candidate
        return base64.b64encode(raw_file).decode("ascii")

    @api.constrains("template_file", "finger_index", "device_employee_id")
    def _check_template_file(self):
        for fingerprint in self:
            fingerprint._template_payload()

    @api.model_create_multi
    def create(self, vals_list):
        seen = set()
        for values in vals_list:
            card_id = values.get("device_employee_id")
            finger_index = str(values.get("finger_index", "0"))
            key = (card_id, finger_index)
            if key in seen or self.search_count([
                ("device_employee_id", "=", card_id),
                ("finger_index", "=", finger_index),
            ], limit=1):
                raise ValidationError(_(
                    "מספר האצבע %s כבר קיים בכרטיס הזה."
                ) % finger_index)
            seen.add(key)
        records = super().create(vals_list)
        records._refresh_card_fingerprint_flag()
        if not self.env.context.get("skip_fingerprint_sync"):
            records._queue_push()
        return records

    def write(self, vals):
        old_cards = self.device_employee_id
        if "finger_index" in vals:
            new_index = str(vals["finger_index"])
            if any(
                fingerprint.finger_index != new_index
                for fingerprint in self
            ):
                raise ValidationError(_(
                    "לא ניתן לשנות מספר אצבע לאחר יצירת השורה. "
                    "יש למחוק את השורה וליצור שורה חדשה."
                ))
        if "finger_index" in vals or "device_employee_id" in vals:
            for fingerprint in self:
                card_id = vals.get(
                    "device_employee_id", fingerprint.device_employee_id.id
                )
                finger_index = str(vals.get(
                    "finger_index", fingerprint.finger_index
                ))
                if self.search_count([
                    ("device_employee_id", "=", card_id),
                    ("finger_index", "=", finger_index),
                    ("id", "!=", fingerprint.id),
                ], limit=1):
                    raise ValidationError(_(
                        "מספר האצבע %s כבר קיים בכרטיס הזה."
                    ) % finger_index)
        if "template_file" in vals and not self.env.context.get("skip_fingerprint_sync"):
            vals = dict(vals, source="odoo")
        result = super().write(vals)
        (old_cards | self.device_employee_id)._refresh_has_fingerprint()
        if (
            not self.env.context.get("skip_fingerprint_sync")
            and {"template_file", "finger_index", "device_employee_id"}.intersection(vals)
        ):
            self._queue_push()
        return result

    def unlink(self):
        cards = self.device_employee_id
        if not self.env.context.get("skip_fingerprint_sync"):
            self._queue_delete()
        result = super().unlink()
        cards._refresh_has_fingerprint()
        return result

    def _refresh_card_fingerprint_flag(self):
        self.device_employee_id._refresh_has_fingerprint()

    def _queue_push(self):
        Command = self.env["mdl.attendance.device.command"].sudo()
        for fingerprint in self:
            card = fingerprint.device_employee_id
            payload = fingerprint._template_payload()
            raw_command = (
                f"DATA UPDATE BIODATA Pin={card.device_user_id}"
                f"\tNo={fingerprint.finger_index}"
                f"\tIndex={fingerprint.biodata_index}\tValid=1"
                f"\tDuress={int(fingerprint.is_duress)}\tType=1"
                f"\tMajorVer={fingerprint.major_version}"
                f"\tMinorVer={fingerprint.minor_version}"
                f"\tFormat={fingerprint.template_format}\tTmp={payload}"
            )
            Command.queue_fingerprint_command(
                card,
                fingerprint.finger_index,
                "update_fingerprint",
                raw_command,
            )

    def _queue_delete(self):
        Command = self.env["mdl.attendance.device.command"].sudo()
        for fingerprint in self:
            card = fingerprint.device_employee_id
            raw_command = (
                f"DATA DELETE BIODATA Pin={card.device_user_id}"
                f"\tType=1\tNo={fingerprint.finger_index}"
            )
            Command.queue_fingerprint_command(
                card,
                fingerprint.finger_index,
                "delete_fingerprint",
                raw_command,
            )
