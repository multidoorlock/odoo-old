import base64
import binascii
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
                return f"DATA DELETE BIOPHOTO PIN={pin}\tType=9"
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
        elif request_type == "OPERLOG" and first_token in ("USERPIC", "BIOPHOTO", "BIODATA", "FP", "FINGERTMP", "FACE"):
            request_type = first_token
        if request_type == "ATTLOG":
            return self._process_attlog(log, body_text)
        if request_type == "OPTIONS":
            return self._process_options(log, body_text)
        # Photos must be dispatched before the USERINFO fallback.  A JPEG's
        # base64 payload may coincidentally contain text such as ``NAME=``.
        if request_type in ("USERPIC", "BIOPHOTO"):
            return self._process_photo(log, request_type, body_text)
        if request_type in ("BIODATA", "FACE"):
            return self._process_biodata(log, body_text)
        if request_type in ("FP", "FINGERTMP"):
            return self._process_fingertmp(log, body_text)
        if request_type == "USERINFO" or ("PIN=" in body_text.upper() and "NAME=" in body_text.upper()):
            return self._process_userinfo(log, body_text)
        log.sudo().write({"processing_state": "processed", "processing_message": f"Received {request_type or 'UNKNOWN'}"})
        return 0

    def process_command_response(self, command, response):
        """Apply values returned inline by older GET OPTION firmwares."""
        if command.command_type in (
            "request_device_language",
            "request_device_cooldown",
            "request_device_options",
        ):
            self._apply_options(response)

    @staticmethod
    def _option_value(body_text, option_name):
        """Read one value from a comma/newline separated OPTIONS payload."""
        match = re.search(
            rf"(?:^|[,\t\r\n&$])\s*~?{re.escape(option_name)}\s*=\s*"
            r"([^,\t\r\n&$]*)",
            body_text or "",
            re.I,
        )
        return match.group(1).strip() if match else None

    def _apply_options(self, body_text):
        applied = []
        language = self._option_value(body_text, "Language")
        if language is not None and self.device.sudo()._apply_reported_language(language):
            applied.append("Language")

        # RecheckMin is a unit flag on this terminal (1 = minutes), while
        # AlarmReRec stores the actual duplicate-punch interval.  Older
        # firmwares expose only ReCheckMin, so retain it as a fallback.
        cooldown = self._option_value(body_text, "AlarmReRec")
        if cooldown is None:
            cooldown = self._option_value(body_text, "ReCheckMin")
        if cooldown is not None and self.device.sudo()._apply_reported_cooldown(cooldown) is not False:
            applied.append("AlarmReRec")
        return applied

    def _process_options(self, log, body_text):
        applied = self._apply_options(body_text)
        log.sudo().write({
            "processing_state": "processed",
            "processing_message": (
                "Applied device option(s): %s" % ", ".join(applied)
                if applied else "Received OPTIONS; no managed values were present"
            ),
        })
        return len(applied)

    def _process_operlog(self, log, body_text):
        created = deleted = biometrics = 0
        for line in body_text.replace("\r", "\n").split("\n"):
            columns = line.strip().split("\t")
            token = columns[0].split(None, 1)[0].upper() if columns and columns[0] else ""
            if token in ("FP", "FINGERTMP"):
                biometrics += self._apply_fingerprint_lines([line])
                continue
            if token == "FACE":
                biometrics += self._apply_face_lines([line])
                continue
            if token == "BIODATA":
                fingerprint_lines, face_lines = self._partition_biodata_lines([line])
                biometrics += self._apply_fingerprint_lines(fingerprint_lines)
                biometrics += self._apply_face_lines(face_lines)
                continue
            if token in ("USER", "USERINFO"):
                values = self._values(line)
                pin = values.get("PIN")
                if pin:
                    self._apply_userinfo_values(pin, values, log)
                    created += 1
                continue
            if not columns or not columns[0].startswith("OPLOG "):
                continue
            try:
                operation_type = int(columns[0].split()[1])
            except (IndexError, ValueError):
                continue
            if (
                operation_type in (5, 108)
                or re.search(r"(?:Language|RecheckMin|AlarmReRec)", line, re.I)
            ):
                # Setting changes commonly arrive with PIN=0 (the screenshot
                # from MB560-VL reports Language as OPLOG 108).  Handle them
                # before the user-PIN guard and read the current values back.
                self.device._queue_device_command(
                    "request_device_options",
                    "GET OPTIONS Language,RecheckMin,AlarmReRec",
                )
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
            elif operation_type == 37:
                card = self._get_or_create_card(pin)
                if card:
                    card._queue_command("request_user")
                    created += 1
            elif operation_type == 6:
                card = self._get_or_create_card(pin)
                if card:
                    card.with_context(skip_card_sync=True).write({"has_fingerprint": True})
                    biometrics += 1
            elif operation_type == 10:
                card = self._get_or_create_card(pin)
                if card:
                    # The deleted finger may have been the last one.  Mark it absent
                    # immediately; a following FP payload restores True when another
                    # enrolled finger still exists.
                    card.with_context(skip_card_sync=True).write({"has_fingerprint": False})
                    self.device._queue_device_command(
                        "request_fingerprints",
                        f"DATA QUERY BIODATA Pin={pin}",
                    )
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
            "processing_message": (
                f"OPERLOG: synchronized {created} user(s), deleted {deleted} user(s), "
                f"updated {biometrics} biometric state(s)"
            ),
        })
        return created + deleted + biometrics

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
        card = Card.with_context(attendance_device_discovery=True).create({
            "device_id": self.device.id, "device_user_id": pin,
            "device_name": name or pin, "link_state": "needs_employee_link",
        })
        card._queue_command("request_user")
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

    def _apply_userinfo_values(self, pin, values, log):
        card = self._get_or_create_card(pin, values.get("NAME"), update_existing=True)
        if not card:
            return card
        update_values = {}
        if values.get("NAME") is not None and card.device_name != values.get("NAME"):
            update_values["device_name"] = values.get("NAME")
        privilege_values = dict(card._fields["device_privilege"].selection)
        verification_values = dict(card._fields["verification_mode"].selection)
        if values.get("PRI") in privilege_values:
            update_values["device_privilege"] = values["PRI"]
        if values.get("VERIFY") in verification_values:
            update_values["verification_mode"] = values["VERIFY"]

        def reported_count(*names):
            for name in names:
                if name in values:
                    try:
                        return int(values[name]) > 0
                    except (TypeError, ValueError):
                        return None
            return None

        fingerprint = reported_count("FPCOUNT", "FINGERCOUNT", "FPCNT")
        face = reported_count("FACECOUNT", "FACECNT")
        if fingerprint is not None:
            update_values["has_fingerprint"] = fingerprint
            if not fingerprint and card.fingerprint_ids:
                card.fingerprint_ids.with_context(
                    skip_fingerprint_sync=True,
                ).unlink()
        if face is not None:
            update_values["has_face"] = face

        photo_content = values.get("CONTENT") or values.get("PHOTO")
        if photo_content:
            prepared = self._photo(photo_content)
            if prepared:
                update_values["profile_photo"] = prepared[1]
        update_values.update({
            "sync_state": "synced",
            "last_sync_at": log.received_at,
            "last_sync_error": False,
        })
        card.with_context(
            skip_card_sync=True,
            skip_biometric_verification_constraint=True,
        ).write(update_values)
        return card

    def _process_userinfo(self, log, body_text):
        count = 0
        for line in body_text.replace("\r", "\n").split("\n"):
            values = self._values(line)
            pin = values.get("PIN")
            if not pin:
                continue
            card = self._apply_userinfo_values(pin, values, log)
            self._complete_pull_command(card, "request_user", log, line)
            self._complete_pull_command(card, "request_privilege", log, line)
            self._complete_pull_command(card, "request_verification_mode", log, line)
            self._complete_pull_command(card, "request_profile_photo", log, line)
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
        if card:
            if request_type == "USERPIC":
                fields_to_update.append(("profile_photo", "request_profile_photo"))
            if request_type == "BIOPHOTO":
                fields_to_update.append(("biometric_photo", "request_biometric_photo"))
        if fields_to_update:
            display_image = prepared[1] if prepared else False
            update_values = {
                "sync_state": "synced",
                "last_sync_at": log.received_at,
                "last_sync_error": False,
            }
            for field, command_type in fields_to_update:
                update_values[field] = display_image
                if field == "biometric_photo":
                    update_values["has_face"] = bool(display_image)
                self._complete_pull_command(card, command_type, log, body_text)
            card.with_context(
                skip_card_sync=True,
                skip_biometric_verification_constraint=True,
            ).write(update_values)
            updated_fields = ", ".join(field for field, _command in fields_to_update)
            state, message = "processed", f"Updated {updated_fields} on device card"
        else:
            state, message = "not_applied", "Photo payload did not contain a supported PIN/Content pair"
        log.sudo().write({"processing_state": state, "processing_message": message})
        return int(state == "processed")

    def _apply_fingerprint_lines(self, lines):
        templates = {}
        reported_present = {}
        for line in lines:
            values = self._values(line)
            pin = values.get("PIN")
            if not pin:
                continue
            valid = values.get("VALID", "1") not in ("0", "False", "false")
            template = values.get("TMP")
            finger_index = (
                values.get("FID")
                or values.get("NO")
                or values.get("INDEX")
                or "0"
            )
            try:
                finger_index = str(max(0, min(9, int(finger_index))))
            except (TypeError, ValueError):
                finger_index = "0"
            templates[(pin, finger_index)] = (valid, template, values)
            reported_present[pin] = reported_present.get(pin, False) or valid

        Fingerprint = self.env["mdl.attendance.device.fingerprint"].sudo()
        updated = 0
        cards = {}
        def integer(values, key, default):
            try:
                return int(values.get(key, default))
            except (TypeError, ValueError):
                return default

        for (pin, finger_index), (valid, template, metadata) in templates.items():
            card = self._get_or_create_card(pin)
            if not card:
                continue
            cards[pin] = card
            fingerprint = Fingerprint.search([
                ("device_employee_id", "=", card.id),
                ("finger_index", "=", finger_index),
            ], limit=1)
            if valid and template:
                stored_template = template
                try:
                    base64.b64decode(template.encode("ascii"), validate=True)
                except (binascii.Error, UnicodeEncodeError, ValueError):
                    # The PUSH protocol specifies base64, but a few legacy
                    # firmwares post their opaque template string directly.
                    stored_template = base64.b64encode(
                        template.encode("utf-8")
                    ).decode("ascii")
                values = {
                    "device_employee_id": card.id,
                    "finger_index": finger_index,
                    "template_file": stored_template,
                    "filename": f"finger_{pin}_{finger_index}.fpt",
                    "source": "device",
                    "last_sync_at": fields.Datetime.now(),
                    "biodata_index": integer(metadata, "INDEX", 0),
                    "major_version": integer(metadata, "MAJORVER", 13),
                    "minor_version": integer(metadata, "MINORVER", 0),
                    "template_format": integer(metadata, "FORMAT", 0),
                    "is_duress": metadata.get("DURESS", "0") in (
                        "1", "True", "true"
                    ),
                }
                if fingerprint:
                    fingerprint.with_context(skip_fingerprint_sync=True).write(values)
                else:
                    Fingerprint.with_context(skip_fingerprint_sync=True).create(values)
                updated += 1
            elif not valid and fingerprint:
                fingerprint.with_context(skip_fingerprint_sync=True).unlink()
                updated += 1

        for pin, card in cards.items():
            present = bool(card.fingerprint_ids.filtered(
                lambda fingerprint: fingerprint.source == "device"
            )) or reported_present.get(pin, False)
            card.with_context(
                skip_card_sync=True,
                skip_biometric_verification_constraint=True,
            ).write({"has_fingerprint": present})
        return updated

    def _complete_fingerprint_verifications(self, lines, log):
        """Compare a terminal BIODATA read-back with pending push requests."""
        reported = {}
        for line in lines:
            values = self._values(line)
            pin = values.get("PIN")
            if not pin:
                continue
            finger_index = values.get("FID") or values.get("NO") or values.get("INDEX") or "0"
            try:
                finger_index = str(max(0, min(9, int(finger_index))))
            except (TypeError, ValueError):
                finger_index = "0"
            valid = values.get("VALID", "1") not in ("0", "False", "false")
            reported[(pin, finger_index)] = (valid, values.get("TMP"))

        Command = self.env["mdl.attendance.device.command"].sudo()
        commands = Command.search([
            ("device_id", "=", self.device.id),
            ("device_employee_id", "!=", False),
            ("command_type", "=", "request_fingerprints"),
            ("fingerprint_index", "!=", False),
            ("state", "in", ["queued", "sent"]),
        ], order="id")
        full_table = bool(re.search(
            r"(?:^|&)table=BIODATA(?:&|$)",
            log.query_string or "",
            re.I,
        ))
        completed = 0
        for command in commands:
            key = (
                command.device_employee_id.device_user_id,
                command.fingerprint_index,
            )
            result = reported.get(key)
            expected_hash = command.fingerprint_verification_hash
            return_code = False
            message = False
            if result:
                valid, payload = result
                if expected_hash:
                    actual_hash = Command._fingerprint_payload_hash(payload) if valid and payload else False
                    if actual_hash == expected_hash:
                        return_code = 0
                        message = "Fingerprint BIODATA read-back matched the pushed template"
                    else:
                        return_code = -1
                        message = "Fingerprint BIODATA read-back did not match the pushed template"
                elif valid and payload:
                    return_code = -1
                    message = "Fingerprint still exists on the terminal after deletion"
                else:
                    return_code = 0
                    message = "Fingerprint deletion verified by BIODATA read-back"
            elif full_table:
                if expected_hash:
                    return_code = -1
                    message = "The pushed fingerprint was not returned by the terminal"
                else:
                    return_code = 0
                    message = "Fingerprint deletion verified; the slot is absent from BIODATA"
            if return_code is not False:
                command.with_context(
                    fingerprint_payload_verified=True,
                ).mark_result(return_code, message, log)
                completed += 1
        return completed

    def _partition_biodata_lines(self, lines):
        """Split ZKTeco's unified BIODATA table by biometric type.

        Modern PUSH firmwares use Type/BioType 1 for fingerprints, 2 for
        face templates, and 9 for visible-light face data.  Older face-only
        payloads omit the type, so keep treating an untyped BIODATA row as a
        face template for backwards compatibility.
        """
        fingerprint_lines = []
        face_lines = []
        for line in lines:
            values = self._values(line)
            biometric_type = str(
                values.get("TYPE") or values.get("BIOTYPE") or ""
            ).strip().upper()
            if biometric_type in ("1", "FP", "FINGER", "FINGERPRINT"):
                fingerprint_lines.append(line)
            else:
                face_lines.append(line)
        return fingerprint_lines, face_lines

    def _process_fingertmp(self, log, body_text):
        lines = body_text.replace("\r", "\n").split("\n")
        updated = self._apply_fingerprint_lines(lines)
        self._complete_fingerprint_verifications(lines, log)
        state = "processed" if updated else "not_applied"
        log.sudo().write({
            "processing_state": state,
            "processing_message": f"Updated {updated} fingerprint enrollment state(s)",
        })
        return updated

    def _apply_face_lines(self, lines):
        states = {}
        values_by_pin = {}
        for line in lines:
            values = self._values(line)
            pin, template = values.get("PIN"), values.get("TMP")
            if not pin:
                continue
            valid = values.get("VALID", "1") not in ("0", "False", "false")
            present = bool(valid and template)
            states[pin] = states.get(pin, False) or present
            if present:
                values_by_pin[pin] = values
        updated = 0
        def integer(values, key, default):
            try:
                return int(values.get(key, default))
            except (TypeError, ValueError):
                return default

        for pin, present in states.items():
            card = self._get_or_create_card(pin)
            if not card:
                continue
            values = values_by_pin.get(pin, {})
            update_values = {
                "has_face": present,
                "face_template": values.get("TMP") if present else False,
                "face_template_no": integer(values, "NO", 4),
                "face_template_index": integer(values, "INDEX", 0),
                "face_template_major_ver": integer(values, "MAJORVER", 13),
                "face_template_minor_ver": integer(values, "MINORVER", 0),
            }
            card.with_context(
                skip_card_sync=True,
                skip_biometric_verification_constraint=True,
            ).write(update_values)
            updated += 1
        return updated

    def _process_biodata(self, log, body_text):
        lines = body_text.replace("\r", "\n").split("\n")
        fingerprint_lines, face_lines = self._partition_biodata_lines(lines)
        updated_fingerprints = self._apply_fingerprint_lines(fingerprint_lines)
        self._complete_fingerprint_verifications(fingerprint_lines, log)
        updated_faces = self._apply_face_lines(face_lines)
        for line in face_lines:
            values = self._values(line)
            card = self._get_or_create_card(values.get("PIN")) if values.get("PIN") else False
            self._complete_pull_command(card, "request_biometric_photo", log, line)
        updated = updated_fingerprints + updated_faces
        state = "processed" if updated else "not_applied"
        message = (
            f"Updated {updated_fingerprints} fingerprint and "
            f"{updated_faces} face enrollment state(s)"
            if updated
            else "BIODATA did not contain a supported biometric template"
        )
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
