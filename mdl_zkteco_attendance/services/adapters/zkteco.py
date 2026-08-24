import base64
import hashlib
import io
import logging
import re
from datetime import datetime, timedelta

import pytz
from PIL import Image
from odoo import fields

from .base import AttendanceDeviceAdapter
from ..attendance_processor import AttendanceProcessor

_logger = logging.getLogger(__name__)


class ZKTecoAdapter(AttendanceDeviceAdapter):
    def _clean(self, value):
        return (value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()

    def _photo(self, value):
        if not value:
            return False
        try:
            raw = base64.b64decode(value)
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            image.thumbnail((320, 320))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85, optimize=True)
            raw = output.getvalue()
            return raw, base64.b64encode(raw).decode("ascii")
        except Exception:
            _logger.exception("Could not prepare ZKTeco photo")
            return False

    def build_command(self, command_type, card):
        pin = card.device_user_id
        if command_type in ("create_user", "update_name", "update_privilege", "update_verification_mode"):
            return (f"DATA UPDATE USERINFO PIN={pin}\tName={self._clean(card.device_name)}"
                    f"\tPri={card.device_privilege}\tVerify={card.verification_mode}")
        if command_type == "update_profile_photo":
            prepared = self._photo(card.profile_photo)
            if not prepared:
                return f"DATA DELETE USERPIC PIN={pin}"
            raw, encoded = prepared
            return f"DATA UPDATE USERPIC PIN={pin}\tSize={len(raw)}\tContent={encoded}"
        if command_type == "update_biometric_photo":
            if not card.biometric_photo:
                raise ValueError("אין בכרטיס תבנית זיהוי פנים. יש לסרוק פנים בשעון ולמשוך את התבנית תחילה.")
            raw, encoded = self._photo(card.biometric_photo)
            # ZAM70/MB560-VL advertises face-photo support in slot 9.
            # The terminal converts this comparison photo into ZKFace data.
            return f"DATA UPDATE BIOPHOTO PIN={pin}\tType=9\tSize={len(raw)}\tContent={encoded}"
        if command_type in ("request_user", "request_privilege", "request_verification_mode"):
            return f"DATA QUERY USERINFO PIN={pin}"
        if command_type == "request_profile_photo":
            # ZAM70 rejects QUERY USERPIC but includes the JPEG in USERINFO.
            return f"DATA QUERY USERINFO PIN={pin}"
        if command_type == "request_biometric_photo":
            return f"DATA QUERY BIOPHOTO PIN={pin}\tType=9"
        if command_type == "delete_user":
            return f"DATA DELETE USERINFO PIN={pin}"
        raise ValueError(f"Unsupported ZKTeco command type: {command_type}")

    def process_payload(self, log, request_type, raw_body, body_text):
        request_type = (request_type or "").upper()
        first_token = body_text.lstrip().split(None, 1)[0].upper() if body_text.strip() else ""
        if request_type == "OPERLOG" and first_token == "OPLOG":
            return self._process_operlog(log, body_text)
        # Several ZKTeco firmwares wrap user and photo changes in table=OPERLOG.
        # The actual record type is the first token in the payload.
        if request_type == "OPERLOG" and first_token in ("USER", "USERINFO"):
            request_type = "USERINFO"
        elif request_type == "OPERLOG" and first_token in ("USERPIC", "BIOPHOTO", "BIODATA"):
            request_type = first_token
        if request_type == "ATTLOG":
            return self._process_attlog(log, body_text)
        # Photos must be dispatched before the USERINFO fallback.  A JPEG's
        # base64 payload may coincidentally contain text such as ``NAME=``.
        if request_type in ("USERPIC", "BIOPHOTO"):
            return self._process_photo(log, request_type, body_text)
        if request_type == "BIODATA":
            return self._process_biodata(log, body_text)
        if request_type == "USERINFO" or ("PIN=" in body_text.upper() and "NAME=" in body_text.upper()):
            return self._process_userinfo(log, body_text)
        log.sudo().write({"processing_state": "processed", "processing_message": f"Received {request_type or 'UNKNOWN'}"})
        return 0

    def _process_operlog(self, log, body_text):
        created = deleted = 0
        for line in body_text.replace("\r", "\n").split("\n"):
            columns = line.strip().split("\t")
            if not columns or not columns[0].startswith("OPLOG "):
                continue
            try:
                operation_type = int(columns[0].split()[1])
            except (IndexError, ValueError):
                continue
            pin = columns[3].strip() if len(columns) > 3 else ""
            if not pin or pin == "0":
                continue
            if operation_type == 30:
                card = self._get_or_create_card(pin)
                if card:
                    card._queue_command("request_user")
                    card._queue_command("request_profile_photo")
                    created += 1
            elif operation_type == 9:
                card = self.env["mdl.attendance.device.employee"].sudo().with_context(
                    active_test=False
                ).search([
                    ("device_id", "=", self.device.id),
                    ("device_user_id", "=", pin),
                ], limit=1)
                if card:
                    card.with_context(skip_device_delete_sync=True).unlink()
                    deleted += 1
        log.sudo().write({
            "processing_state": "processed",
            "processing_message": f"OPERLOG: discovered {created} user(s), deleted {deleted} user(s)",
        })
        return created + deleted

    def _values(self, line):
        # Values such as a user's Name may contain spaces. Locate field markers
        # instead of splitting on whitespace so ``Name=Jane Doe`` stays intact.
        matches = list(re.finditer(r"(?:^|[\t ])([A-Za-z][A-Za-z0-9_]*)=", line))
        values = {}
        for index, match in enumerate(matches):
            value_end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            values[match.group(1).upper()] = line[match.end():value_end].strip()
        return values

    def _get_or_create_card(self, pin, name=None, update_existing=False):
        Card = self.env["mdl.attendance.device.employee"].sudo()
        card = Card.with_context(active_test=False).search([
            ("device_id", "=", self.device.id),
            ("device_user_id", "=", pin),
        ], limit=1)
        if card:
            values = {}
            if not card.active:
                values["active"] = True
            if update_existing and name and card.device_name != name:
                values["device_name"] = name
            if values:
                card.with_context(skip_card_sync=True).write(values)
            return card
        if not self.device.auto_discover_users:
            return Card.browse()
        card = Card.with_context(attendance_device_discovery=True).create({
            "device_id": self.device.id, "device_user_id": pin,
            "device_name": name or pin, "link_state": "needs_employee_link",
        })
        card._queue_command("request_user")
        if self.device.auto_sync_profile_photo:
            card._queue_command("request_profile_photo")
        return card

    def _pull_is_pending(self, card, command_types):
        # The clock acknowledges DATA QUERY first and posts the requested table
        # in a following request.  Keep a short correlation window after that ACK;
        # otherwise the command is already ``done`` when BIODATA/USERPIC arrives.
        recent_ack = fields.Datetime.now() - timedelta(minutes=5)
        return bool(card and self.env["mdl.attendance.device.command"].sudo().search_count([
            ("device_id", "=", self.device.id),
            ("command_type", "in", list(command_types)),
            "|",
            ("state", "in", ["queued", "sent"]),
            "&", ("state", "in", ["done", "failed"]), ("completed_at", ">=", recent_ack),
            "|", ("device_employee_id", "=", card.id), ("device_employee_id", "=", False),
        ], limit=1))

    def _process_userinfo(self, log, body_text):
        count = 0
        for line in body_text.replace("\r", "\n").split("\n"):
            values = self._values(line)
            pin = values.get("PIN")
            if not pin:
                continue
            existing = self.env["mdl.attendance.device.employee"].sudo().with_context(active_test=False).search([
                ("device_id", "=", self.device.id), ("device_user_id", "=", pin)
            ], limit=1)
            allow_update = not existing or self._pull_is_pending(existing, {"request_user", "request_users"})
            card = self._get_or_create_card(pin, values.get("NAME"), update_existing=allow_update)
            extra_values = {}
            privilege_values = dict(card._fields["device_privilege"].selection) if card else {}
            verification_values = dict(card._fields["verification_mode"].selection) if card else {}
            if values.get("PRI") in privilege_values and self._pull_is_pending(card, {"request_privilege"}):
                extra_values["device_privilege"] = values["PRI"]
                self._complete_pull_command(card, "request_privilege", log, line)
            if values.get("VERIFY") in verification_values and self._pull_is_pending(card, {"request_verification_mode"}):
                extra_values["verification_mode"] = values["VERIFY"]
                self._complete_pull_command(card, "request_verification_mode", log, line)
            if extra_values:
                extra_values.update({"sync_state": "synced", "last_sync_at": log.received_at, "last_sync_error": False})
                card.with_context(skip_card_sync=True).write(extra_values)
            self._complete_pull_command(card, "request_user", log, line)
            count += 1
        bulk_command = self.env["mdl.attendance.device.command"].sudo().search([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "request_users"),
            ("state", "in", ["sent", "queued", "failed"]),
            "|", ("completed_at", "=", False), ("completed_at", ">=", fields.Datetime.now() - timedelta(minutes=5)),
        ], order="id", limit=1)
        if bulk_command:
            bulk_command.mark_result(0, body_text, log)
        log.sudo().write({"processing_state": "processed", "processing_message": f"Processed {count} USERINFO record(s)"})
        return count

    def _process_photo(self, log, request_type, body_text):
        values = self._values(body_text)
        pin = values.get("PIN")
        card = self._get_or_create_card(pin) if pin else False
        content = values.get("CONTENT")
        prepared = self._photo(content) if content else False
        fields_to_update = []
        if card and prepared:
            if request_type == "USERPIC" and self._pull_is_pending(card, {"request_profile_photo"}):
                fields_to_update.append(("profile_photo", "request_profile_photo"))
            if request_type == "BIOPHOTO" and self._pull_is_pending(card, {"request_biometric_photo"}):
                fields_to_update.append(("biometric_photo", "request_biometric_photo"))
        if fields_to_update:
            _raw, display_image = prepared
            update_values = {
                "sync_state": "synced",
                "last_sync_at": log.received_at,
                "last_sync_error": False,
            }
            for field, command_type in fields_to_update:
                update_values[field] = display_image
                self._complete_pull_command(card, command_type, log, body_text)
            card.with_context(skip_card_sync=True).write(update_values)
            updated_fields = ", ".join(field for field, _command in fields_to_update)
            state, message = "processed", f"Updated {updated_fields} on device card"
        else:
            state, message = "not_applied", "Photo payload did not contain a supported PIN/Content pair"
        log.sudo().write({"processing_state": state, "processing_message": message})
        return int(state == "processed")

    def _process_biodata(self, log, body_text):
        updated = 0
        for line in body_text.replace("\r", "\n").split("\n"):
            values = self._values(line)
            pin, template = values.get("PIN"), values.get("TMP")
            card = self.env["mdl.attendance.device.employee"].sudo().with_context(active_test=False).search([
                ("device_id", "=", self.device.id), ("device_user_id", "=", pin),
            ], limit=1) if pin else False
            if not (card and template and values.get("TYPE") == "1" and self._pull_is_pending(card, {"request_biometric_photo"})):
                continue
            card.with_context(skip_card_sync=True).write({
                "face_template": template,
                "face_template_no": int(values.get("NO", 4)),
                "face_template_index": int(values.get("INDEX", 0)),
                "face_template_major_ver": int(values.get("MAJORVER", 13)),
                "face_template_minor_ver": int(values.get("MINORVER", 0)),
                "sync_state": "synced", "last_sync_at": log.received_at, "last_sync_error": False,
            })
            self._complete_pull_command(card, "request_biometric_photo", log, line)
            updated += 1
        state = "processed" if updated else "not_applied"
        message = f"Updated {updated} face recognition template(s)" if updated else "BIODATA did not contain a requested face template"
        log.sudo().write({"processing_state": state, "processing_message": message})
        return updated

    def apply_latest_face_template(self, card):
        """Apply the latest face template already posted by this clock.

        Some firmware acknowledges ``DATA QUERY BIODATA`` but returns a table
        cursor rather than the requested PIN.  Enrollment still posts the exact
        BIODATA record, so an explicit Pull may safely use that latest clock
        payload for the selected card.
        """
        log = self.env["mdl.attendance.device.log"].sudo().search([
            ("device_id", "=", self.device.id),
            ("request_type", "=", "BIODATA"),
            ("body", "ilike", f"BIODATA Pin={card.device_user_id}"),
        ], order="received_at desc, id desc", limit=1)
        if log:
            return self._process_biodata(log, log.body)
        return 0

    def _complete_pull_command(self, card, command_type, log, response):
        if not card:
            return
        command = self.env["mdl.attendance.device.command"].sudo().search([
            ("device_employee_id", "=", card.id), ("command_type", "=", command_type),
            ("state", "in", ["sent", "queued"]),
        ], order="id", limit=1)
        if command:
            command.mark_result(0, response, log)

    def map_punch_state(self, raw_value):
        parse = lambda value: {item.strip() for item in (value or "").split(",") if item.strip()}
        in_values = parse(self.device.punch_in_values) or {"0"}
        out_values = parse(self.device.punch_out_values) or {"1"}
        if raw_value in in_values:
            return "in"
        if raw_value in out_values:
            return "out"
        return "unknown"

    def _utc_datetime(self, value):
        local_naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        timezone = pytz.timezone(self.device.timezone or "UTC")
        return timezone.localize(local_naive, is_dst=None).astimezone(pytz.utc).replace(tzinfo=None)

    def _process_attlog(self, log, body_text):
        Event = self.env["mdl.attendance.device.event"].sudo()
        events = Event.browse()
        errors = 0
        lines = [line.strip() for line in body_text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
        for line_number, line in enumerate(lines, start=1):
            try:
                columns = line.split("\t")
                if len(columns) < 4:
                    columns = line.split()
                    if len(columns) >= 5:
                        columns = [columns[0], f"{columns[1]} {columns[2]}", *columns[3:]]
                punch_column = self.device.punch_state_column
                if punch_column < 0 or punch_column >= len(columns):
                    raise ValueError(f"Punch State column {punch_column} is missing")
                pin, event_text, raw_punch = columns[0].strip(), columns[1].strip(), columns[punch_column].strip()
                event_datetime = self._utc_datetime(event_text)
                punch_state = self.map_punch_state(raw_punch)
                card = self._get_or_create_card(pin)
                fingerprint_source = f"{self.device.id}|{pin}|{event_datetime.isoformat()}|{raw_punch}"
                fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()
                event = Event.create({
                    "log_id": log.id, "device_id": self.device.id,
                    "device_employee_id": card.id if card else False,
                    "employee_id": card.employee_id.id if card and card.employee_id else False,
                    "device_user_id": pin, "event_datetime": event_datetime,
                    "raw_punch_state": raw_punch, "punch_state": punch_state,
                    "event_fingerprint": fingerprint, "raw_line": line,
                })
                events |= event
            except Exception as exc:
                errors += 1
                # Malformed device input is an expected validation outcome: it
                # is preserved below as an error event. Do not emit an ERROR
                # traceback that makes an otherwise successful test/build fail.
                _logger.warning("Rejected malformed ZKTeco ATTLOG line %r: %s", line, exc)
                fingerprint = hashlib.sha256(f"parse-error|{log.id}|{line_number}|{line}".encode()).hexdigest()
                event = Event.create({
                    "log_id": log.id, "device_id": self.device.id,
                    "device_user_id": line.split("\t", 1)[0].strip() or False,
                    "punch_state": "unknown", "event_fingerprint": fingerprint,
                    "raw_line": line, "processing_state": "error",
                    "processing_message": str(exc),
                })
                events |= event
        AttendanceProcessor(self.env).process(events.filtered(lambda event: event.processing_state == "new"))
        states = set(events.mapped("processing_state"))
        if errors:
            state = "error"
        elif states == {"processed"}:
            state = "processed"
        elif "waiting_employee_link" in states:
            state = "waiting_employee_link"
        elif states & {"not_applied", "error"}:
            state = "not_applied"
        else:
            state = "ignored" if states else "processed"
        log.sudo().write({"processing_state": state, "processing_message": f"Created {len(events)} event(s); {errors} parse error(s)"})
        if not errors:
            self.device.sudo().write({"last_attendance_sync_at": log.received_at or fields.Datetime.now()})
        return len(events)
