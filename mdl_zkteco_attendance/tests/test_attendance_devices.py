import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestAttendanceDevices(TransactionCase):
    @classmethod
    def _employee_vals(cls, name, company):
        """Keep clock tests compatible with optional payroll constraints."""
        vals = {"name": name, "company_id": company.id}
        Employee = cls.env["hr.employee"]
        if "mdl_wage_type" in Employee._fields:
            vals["mdl_wage_type"] = "mdl_monthly"
        if "structure_type_id" in Employee._fields:
            monthly_structure_type = cls.env[
                "hr.payroll.structure.type"
            ].search([("wage_type", "=", "monthly")], limit=1)
            if monthly_structure_type:
                vals["structure_type_id"] = monthly_structure_type.id
        return vals

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.device = cls.env["mdl.attendance.device"].create({
            "name": "Test clock", "manufacturer": "zkteco",
            "device_identifier": "TEST-SN", "company_id": cls.env.company.id,
            "timezone": "UTC", "punch_state_column": 3,
            "punch_in_values": "1", "punch_out_values": "15",
        })
        cls.other_device = cls.env["mdl.attendance.device"].create({
            "name": "Second test clock", "manufacturer": "zkteco",
            "device_identifier": "TEST-SN-2", "company_id": cls.env.company.id,
            "timezone": "UTC", "punch_state_column": 3,
            "punch_in_values": "1", "punch_out_values": "15",
        })
        cls.employee = cls.env["hr.employee"].create(
            cls._employee_vals("Clock Employee", cls.env.company)
        )
        cls.card = cls.env["mdl.attendance.device.employee"].with_context(attendance_device_discovery=True).create({
            "device_id": cls.device.id, "device_user_id": "74", "device_name": "Clock Employee",
            "employee_id": cls.employee.id,
        })

    def _log(self):
        return self.env["mdl.attendance.device.log"].create({
            "device_id": self.device.id, "device_identifier": self.device.device_identifier,
            "request_type": "ATTLOG", "http_method": "POST", "endpoint": "/iclock/cdata",
        })

    def _pending_event(self, event_datetime, punch_state, suffix):
        return self.env["mdl.attendance.device.event"].create({
            "log_id": self._log().id,
            "device_id": self.device.id,
            "device_employee_id": self.card.id,
            "employee_id": self.employee.id,
            "device_user_id": self.card.device_user_id,
            "event_datetime": event_datetime,
            "raw_line": "timeline test",
            "raw_punch_state": punch_state,
            "punch_state": punch_state,
            "event_fingerprint": f"timeline:{suffix}",
            "processing_state": "not_applied",
            "processing_message": "Timeline test event",
        })

    def _reconcile_employee(self):
        return self.env["mdl.attendance.device.event"]._timeline_reconcile_employee_ids(
            [self.employee.id],
        )

    def test_employee_archive_only_restores_cards_archived_by_employee(self):
        manual_card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.other_device.id,
            "device_user_id": "archive-manual",
            "employee_id": self.employee.id,
        })
        manual_card.active = False

        self.employee.active = False
        self.card.invalidate_recordset(["active", "archived_by_employee"])
        self.assertFalse(self.card.active)
        self.assertTrue(self.card.archived_by_employee)

        with self.assertRaises(ValidationError):
            self.card.active = True

        self.employee.active = True
        self.card.invalidate_recordset(["active", "archived_by_employee"])
        manual_card.invalidate_recordset(["active", "archived_by_employee"])
        self.assertTrue(self.card.active)
        self.assertFalse(self.card.archived_by_employee)
        self.assertFalse(manual_card.active)
        self.assertFalse(manual_card.archived_by_employee)

    def test_employee_can_only_have_one_active_card_per_device(self):
        with self.assertRaises(ValidationError):
            self.env["mdl.attendance.device.employee"].with_context(
                attendance_device_discovery=True,
            ).create({
                "device_id": self.device.id,
                "device_user_id": "duplicate-employee",
                "employee_id": self.employee.id,
            })

        self.card.active = False
        replacement = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.device.id,
            "device_user_id": "replacement-employee",
            "employee_id": self.employee.id,
        })
        self.assertTrue(replacement.active)
        with self.assertRaises(ValidationError):
            self.card.active = True

    def test_manual_attendance_creates_and_keeps_endpoint_events_in_sync(self):
        check_in = fields.Datetime.now() - timedelta(hours=8)
        check_out = check_in + timedelta(hours=7)
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": check_in,
            "check_out": check_out,
        })
        events = self.env["mdl.attendance.device.event"].search([
            ("attendance_id", "=", attendance.id),
        ]).sorted("event_datetime")
        self.assertEqual(len(events), 2)
        self.assertTrue(all(events.mapped("odoo_generated")))
        self.assertEqual(events.mapped("punch_state"), ["in", "out"])

        new_check_out = check_out + timedelta(minutes=30)
        attendance.check_out = new_check_out
        events.invalidate_recordset(["event_datetime"])
        self.assertEqual(events[-1].event_datetime, new_check_out)

    def test_technical_absence_skips_an_overlapping_open_attendance(self):
        check_in = fields.Datetime.to_datetime("2026-09-08 21:00:00")
        existing = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": check_in,
        })

        technical = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": check_in + timedelta(hours=3),
            "check_out": check_in + timedelta(hours=3, seconds=1),
            "in_mode": "technical",
            "out_mode": "technical",
        })

        self.assertFalse(technical)
        self.assertEqual(
            self.env["hr.attendance"].search_count([
                ("employee_id", "=", self.employee.id),
            ]),
            1,
        )
        self.assertEqual(existing.check_in, check_in)

        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["hr.attendance"].create({
                "employee_id": self.employee.id,
                "check_in": check_in + timedelta(hours=4),
            })

    def test_manual_attendance_reuses_matching_raw_event(self):
        check_in = fields.Datetime.now() - timedelta(hours=2)
        raw_event = self._pending_event(check_in, "in", "reuse-manual")
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": check_in,
        })
        raw_event.invalidate_recordset(["attendance_id", "processing_state"])
        self.assertEqual(raw_event.attendance_id, attendance)
        self.assertEqual(raw_event.processing_state, "processed")
        self.assertFalse(raw_event.odoo_generated)

    def test_attendance_does_not_reuse_legacy_event_from_another_company(self):
        other_company = self.env["res.company"].create({
            "name": "Attendance endpoint company",
        })
        other_employee = self.env["hr.employee"].with_company(other_company).create(
            self._employee_vals("Other-company attendance employee", other_company)
        )
        check_in = fields.Datetime.now() - timedelta(hours=3)
        attendance = self.env["hr.attendance"].with_company(other_company).with_context(
            skip_attendance_event_sync=True,
        ).create({
            "employee_id": other_employee.id,
            "check_in": check_in,
        })
        legacy_event = self._pending_event(check_in, "in", "legacy-other-company")
        legacy_event.with_context(attendance_event_system_write=True).write({
            "attendance_id": attendance.id,
        })

        attendance.with_context(
            skip_attendance_event_sync=False,
        ).with_company(other_company)._ensure_attendance_device_events()

        legacy_event.invalidate_recordset([
            "attendance_id", "processing_state", "processing_message",
        ])
        self.assertFalse(legacy_event.attendance_id)
        self.assertEqual(legacy_event.processing_state, "not_applied")
        replacement = self.env["mdl.attendance.device.event"].search([
            ("attendance_id", "=", attendance.id),
        ])
        self.assertEqual(len(replacement), 1)
        self.assertTrue(replacement.odoo_generated)
        self.assertEqual(replacement.company_id, other_company)
        self.assertEqual(replacement.employee_id, other_employee)

    def test_new_card_copies_employee_name_and_profile_photo(self):
        self.employee.image_1920 = (
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            b"+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )

        draft = self.env["mdl.attendance.device.employee"].new({
            "device_id": self.other_device.id,
        })
        draft.employee_id = self.employee
        draft._onchange_employee_id_set_card_identity()
        self.assertEqual(draft.device_name, self.employee.name)
        self.assertEqual(draft.profile_photo, self.employee.image_1920)

        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.other_device.id,
            "employee_id": self.employee.id,
        })
        self.assertEqual(card.device_name, self.employee.name)
        self.assertEqual(card.profile_photo, self.employee.image_1920)

    def test_device_language_syncs_employee_translation_to_card(self):
        self.assertFalse(self.env["resource.resource"]._fields["name"].translate)
        self.assertTrue(self.env["hr.employee"]._fields["name"].translate)
        self.assertTrue(self.env["hr.employee.public"]._fields["name"].translate)
        self.assertFalse(self.env["mdl.attendance.device.employee"]._fields["device_name"].translate)

        public_employee = self.env["hr.employee.public"].browse(self.employee.id)
        self.assertIsInstance(public_employee.name, str)
        self.assertTrue(public_employee.avatar_128)

        language = self.env["res.lang"].search([
            ("code", "in", ["he_IL", "ar_001", "en_US"]),
            ("code", "!=", self.env.lang),
        ], limit=1)
        if not language:
            self.skipTest("A second supported active language is required for this test")

        translated_name = "Selected clock language employee name"
        self.employee.update_field_translations("name", {
            language.code: translated_name,
        })
        self.other_device.write({"device_language": language.code})
        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.other_device.id,
            "employee_id": self.employee.id,
            "device_name": "This value must be overwritten",
        })

        command = self.other_device._adapter().build_command("update_name", card)
        self.assertIn(f"Name={translated_name}", command)
        self.assertEqual(card.device_name, translated_name)

        edited_name = "Edited employee translation"
        self.employee.update_field_translations("name", {
            language.code: edited_name,
        })
        self.assertEqual(card.device_name, edited_name)

        card.write({"device_name": "Manual card name"})
        card.write({"employee_id": self.employee.id})
        self.assertEqual(card.device_name, edited_name)

        created_employee = self.env["hr.employee"].create(
            self._employee_vals(
                "Created through translated name field", self.env.company,
            )
        )
        self.assertEqual(created_employee.name, "Created through translated name field")

    def test_inactive_clock_language_falls_back_to_current_odoo_language(self):
        language_code = "ar_001" if self.env.lang != "ar_001" else "he_IL"
        language = self.env["res.lang"].with_context(active_test=False).search([
            ("code", "=", language_code),
        ], limit=1)
        if language and language.active:
            # The optional Website module prevents deactivating any language
            # assigned to a website.  This test only needs an inactive language
            # in its rolled-back transaction, so write the field directly.
            language._fields["active"].write(language, False)

        self.other_device.device_language = language_code
        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.other_device.id,
            "employee_id": self.employee.id,
        })
        self.assertEqual(card.device_name, self.employee.name)

    def test_manual_identity_sync_between_card_and_employee(self):
        employee_photo = (
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            b"+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.employee.image_1920 = employee_photo
        self.card.with_context(skip_card_sync=True).write({
            "device_name": "Old card name",
            "profile_photo": False,
        })

        self.card.action_pull_from_employee()
        self.assertEqual(
            self.card.device_name,
            self.employee._attendance_device_name(self.device),
        )
        self.assertEqual(self.card.profile_photo, self.employee.image_1920)

        self.card.with_context(skip_card_sync=True).write({
            "device_name": "Name received from clock",
            "profile_photo": employee_photo,
        })
        self.card.action_push_to_employee()
        self.assertEqual(self.employee.image_1920, self.card.profile_photo)
        language = self.env["res.lang"]._lang_get(self.device.device_language)
        language_code = language.code if language else (self.env.lang or "en_US")
        self.assertEqual(
            self.employee.with_context(lang=language_code).name,
            "Name received from clock",
        )

    def test_clock_profile_photo_becomes_missing_biometric_photo(self):
        photo = (
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            b"+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.card.with_context(
            skip_card_sync=True,
            skip_biometric_verification_constraint=True,
        ).write({"profile_photo": False, "biometric_photo": False, "has_face": False})

        self.device._adapter().process_payload(
            self._log(), "USERPIC", b"",
            f"USERPIC PIN=74\tContent={photo.decode()}",
        )
        self.card.invalidate_recordset(["profile_photo", "biometric_photo", "has_face"])
        self.assertEqual(self.card.profile_photo, self.card.biometric_photo)
        self.assertTrue(self.card.has_face)

        existing_biometric = photo
        self.card.with_context(
            skip_card_sync=True,
            skip_biometric_verification_constraint=True,
        ).write({"biometric_photo": existing_biometric})
        self.device._adapter().process_payload(
            self._log(), "USERPIC", b"",
            f"USERPIC PIN=74\tContent={photo.decode()}",
        )
        self.assertEqual(self.card.biometric_photo, existing_biometric)

    def test_verification_mode_requires_enrolled_biometrics(self):
        card = self.card
        card.write({
            "verification_mode": "0",
            "has_face": False,
            "has_fingerprint": False,
        })

        # Slash-separated modes are alternatives and do not require enrollment.
        card.write({"verification_mode": "5"})

        with self.assertRaises(ValidationError), self.cr.savepoint():
            card.write({"verification_mode": "1"})
        card.invalidate_recordset()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            card.write({"verification_mode": "15"})
        card.invalidate_recordset()

        card.write({"has_fingerprint": True, "verification_mode": "1"})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            card.write({"verification_mode": "16"})
        card.invalidate_recordset()

        card.write({"has_face": True, "verification_mode": "16"})
        self.assertEqual(card.verification_mode, "16")

    def test_device_employee_menu_uses_preference_action_and_versioned_icon(self):
        preference_action = self.env.ref(
            "mdl_zkteco_attendance.action_device_employee_preference"
        )
        menu = self.env.ref("mdl_zkteco_attendance.menu_device_employees")
        root_menu = self.env.ref("mdl_zkteco_attendance.menu_attendance_devices_root")

        self.assertEqual(
            preference_action.tag,
            "mdl_zkteco_attendance.device_employee_preference",
        )
        self.assertEqual(menu.action, preference_action)
        self.assertEqual(
            root_menu.web_icon,
            "mdl_zkteco_attendance,static/description/icon_menu_v2.png",
        )

    def test_in_out_and_duplicate(self):
        adapter = self.device._adapter()
        log = self._log()
        adapter.process_payload(log, "ATTLOG", b"", "74\t2026-08-11 08:00:00\t255\t1\t0\n74\t2026-08-11 17:00:00\t255\t15\t0")
        events = log.event_ids.sorted("event_datetime")
        self.assertEqual(events.mapped("processing_state"), ["processed", "processed"])
        self.assertEqual(events[0].attendance_id, events[1].attendance_id)
        self.assertEqual(events[0].attendance_id.check_in.hour, 8)
        self.assertEqual(events[1].attendance_id.check_out.hour, 17)
        self.assertEqual(self.device.last_attendance_sync_at, log.received_at)
        duplicate_log = self._log()
        adapter.process_payload(duplicate_log, "ATTLOG", b"", "74\t2026-08-11 08:00:00\t255\t1\t0")
        self.assertEqual(duplicate_log.event_ids.processing_state, "ignored")

    def test_device_cooldown_filters_only_repeated_same_kind_punches(self):
        self.device.write({"attendance_cooldown_minutes": 5})
        log = self._log()
        self.device._adapter().process_payload(
            log,
            "ATTLOG",
            b"",
            "74\t2026-08-12 08:00:00\t255\t1\t0\n"
            "74\t2026-08-12 08:02:00\t255\t1\t0\n"
            "74\t2026-08-12 08:03:00\t255\t15\t0",
        )
        first_in, repeated_in, out_event = log.event_ids.sorted(
            lambda event: (event.event_datetime, event.id),
        )

        self.assertEqual(first_in.processing_state, "processed")
        self.assertEqual(repeated_in.processing_state, "ignored")
        self.assertIn("Cooldown", repeated_in.processing_message)
        self.assertEqual(out_event.processing_state, "processed")
        self.assertEqual(first_in.attendance_id, out_event.attendance_id)
        self.assertEqual(repeated_in.attendance_id, first_in.attendance_id)

        later_log = self._log()
        self.device._adapter().process_payload(
            later_log, "ATTLOG", b"", "74\t2026-08-12 08:06:00\t255\t1\t0",
        )
        self.assertNotEqual(later_log.event_ids.processing_state, "ignored")

    def test_device_cooldown_must_not_be_negative(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.device.write({"attendance_cooldown_minutes": -1})

    def test_new_zkteco_device_maps_standard_zero_and_one_punch_values(self):
        self.assertEqual(self.device._adapter().map_punch_state("0"), "unknown")
        device = self.env["mdl.attendance.device"].create({
            "name": "Default mapping clock",
            "manufacturer": "zkteco",
            "device_identifier": "DEFAULT-MAPPING-SN",
            "company_id": self.env.company.id,
            "timezone": "UTC",
        })
        self.assertEqual(device.punch_in_values, "0")
        self.assertEqual(device.punch_out_values, "1")
        self.assertEqual(device._adapter().map_punch_state("0"), "in")
        self.assertEqual(device._adapter().map_punch_state("1"), "out")

        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": device.id,
            "device_user_id": "901",
            "device_name": self.employee.name,
            "employee_id": self.employee.id,
        })
        log = self.env["mdl.attendance.device.log"].create({
            "device_id": device.id,
            "device_identifier": device.device_identifier,
            "request_type": "ATTLOG",
            "http_method": "POST",
            "endpoint": "/iclock/cdata",
        })
        device._adapter().process_payload(
            log, "ATTLOG", b"", "901\t2026-08-10 08:00:00\t0\t1\t0",
        )
        event = log.event_ids
        self.assertEqual(event.device_employee_id, card)
        self.assertEqual(event.punch_state, "in")
        self.assertEqual(event.processing_state, "processed")
        self.assertTrue(event.attendance_id)
        self.assertEqual(event.attendance_id.check_in, event.event_datetime)

        device.write({"punch_in_values": False, "punch_out_values": False})
        self.assertEqual(device._adapter().map_punch_state("0"), "in")
        self.assertEqual(device._adapter().map_punch_state("1"), "out")

    def test_attendance_timeline_tiles_point_to_the_matching_source_events(self):
        log = self._log()
        self.device._adapter().process_payload(
            log, "ATTLOG", b"",
            "74\t2026-08-11 08:00:00\t255\t1\t0\n"
            "74\t2026-08-11 17:00:00\t255\t15\t0",
        )
        source_events = log.event_ids.sorted("event_datetime")
        attendance = source_events.attendance_id
        self._pending_event("2026-08-11 18:00:00", "out", "source-event-context")

        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-11 00:00:00", "2026-08-12 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        attendance_items = {
            item["kind"]: item
            for item in row["items"]
            if item["source"] == "attendance" and item["source_id"] == attendance.id
        }
        self.assertEqual(attendance_items["in"]["event_id"], source_events[0].id)
        self.assertEqual(attendance_items["out"]["event_id"], source_events[1].id)
        self.assertEqual(
            [action["key"] for action in attendance_items["in"]["actions"]],
            ["open_attendance", "flip_event", "dismiss_event"],
        )
        self.assertEqual(
            attendance_items["in"]["actions"][1]["label"],
            "הפוך ליציאה",
        )
        self.assertEqual(
            [action["key"] for action in attendance_items["out"]["actions"]],
            ["open_attendance", "flip_event", "dismiss_event"],
        )
        self.assertEqual(
            attendance_items["out"]["actions"][1]["label"],
            "הפוך לכניסה",
        )

    def test_conflict_attendance_action_uses_readonly_popup_view(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": "2026-08-11 08:00:00",
            "check_out": "2026-08-11 17:00:00",
        })
        action = self.env["mdl.attendance.device.event"].timeline_attendance_form_action(
            attendance.id,
        )
        readonly_view = self.env.ref(
            "mdl_zkteco_attendance.view_hr_attendance_conflict_readonly_form"
        )
        self.assertEqual(action["res_model"], "hr.attendance")
        self.assertEqual(action["res_id"], attendance.id)
        self.assertEqual(action["views"], [(readonly_view.id, "form")])
        self.assertEqual(action["target"], "new")
        self.assertFalse(action["context"]["edit"])

        combined_arch = readonly_view.get_combined_arch()
        self.assertIn('edit="false"', combined_arch)
        self.assertIn('create="false"', combined_arch)
        self.assertIn('delete="false"', combined_arch)

    def test_conflict_event_popup_is_editable_only_for_raw_events(self):
        event = self._pending_event("2026-08-11 18:30:00", "in", "popup-modes")
        Event = self.env["mdl.attendance.device.event"]

        editable_action = Event.timeline_event_form_action(event.id, False)
        editable_view = self.env.ref("mdl_zkteco_attendance.view_device_event_form")
        self.assertEqual(editable_action["res_id"], event.id)
        self.assertEqual(editable_action["views"], [(editable_view.id, "form")])
        self.assertTrue(editable_action["context"]["edit"])

        readonly_action = Event.timeline_event_form_action(event.id, True)
        readonly_view = self.env.ref(
            "mdl_zkteco_attendance.view_device_event_readonly_form"
        )
        self.assertEqual(readonly_action["res_id"], event.id)
        self.assertEqual(readonly_action["views"], [(readonly_view.id, "form")])
        self.assertFalse(readonly_action["context"]["edit"])
        combined_arch = readonly_view.get_combined_arch()
        self.assertIn('edit="false"', combined_arch)
        self.assertIn('create="false"', combined_arch)
        self.assertIn('delete="false"', combined_arch)

    def test_attendance_reconciliation_is_queued_once(self):
        command = self.device._queue_attendance_reconciliation()
        self.assertEqual(len(command), 1)
        self.assertEqual(command.command_type, "request_attendance_logs")
        self.assertTrue(command.raw_command.startswith("DATA QUERY ATTLOG StartTime="))
        self.assertIn("\tEndTime=", command.raw_command)
        self.device._queue_attendance_reconciliation()
        self.assertEqual(self.env["mdl.attendance.device.command"].search_count([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "request_attendance_logs"),
            ("state", "in", ["queued", "sent"]),
        ]), 1)

    def test_technical_role_has_full_log_access_while_manager_stays_readonly(self):
        technical_user = new_test_user(
            self.env,
            login="attendance-log-technical",
            groups="mdl_zkteco_attendance.group_attendance_device_technical",
            company_id=self.env.company.id,
        )
        manager_user = new_test_user(
            self.env,
            login="attendance-log-manager",
            groups="mdl_zkteco_attendance.group_attendance_device_manager",
            company_id=self.env.company.id,
        )
        technical_logs = self.env["mdl.attendance.device.log"].with_user(technical_user)
        manager_logs = self.env["mdl.attendance.device.log"].with_user(manager_user)

        for operation in ("read", "write", "create", "unlink"):
            self.assertTrue(technical_logs.has_access(operation), operation)
        self.assertTrue(manager_logs.has_access("read"))
        for operation in ("write", "create", "unlink"):
            self.assertFalse(manager_logs.has_access(operation), operation)

    def test_unlinked_card_waits(self):
        self.env["mdl.attendance.device.employee"].with_context(attendance_device_discovery=True).create({
            "device_id": self.device.id, "device_user_id": "75", "device_name": "Unknown",
        })
        log = self._log()
        self.device._adapter().process_payload(log, "ATTLOG", b"", "75\t2026-08-12 08:00:00\t255\t1\t0")
        self.assertEqual(log.event_ids.processing_state, "waiting_employee_link")
        self.assertFalse(log.event_ids.attendance_id)

    def test_double_in_not_applied(self):
        log = self._log()
        self.device._adapter().process_payload(log, "ATTLOG", b"", "74\t2026-08-13 08:00:00\t255\t1\t0\n74\t2026-08-13 08:05:00\t255\t1\t0")
        events = log.event_ids.sorted("event_datetime")
        self.assertEqual(events[0].processing_state, "processed")
        self.assertEqual(events[1].processing_state, "not_applied")
        self.assertTrue(events[1].processing_message)
        self.assertEqual(
            events[1].conflict_reason,
            "חסרה יציאה",
        )
        action = events[1].action_dismiss_conflict()
        self.assertTrue(events[1].conflict_dismissed)
        self.assertFalse(action)
        self.assertEqual(events[0].processing_state, "processed")
        self.assertTrue(events[0].attendance_id)

    def test_conflict_timeline_flip_closes_open_attendance_automatically(self):
        log = self._log()
        self.device._adapter().process_payload(
            log, "ATTLOG", b"",
            "74\t2026-08-13 08:00:00\t255\t1\t0\n74\t2026-08-13 08:05:00\t255\t1\t0",
        )
        events = log.event_ids.sorted("event_datetime")
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-01 00:00:00", "2026-09-01 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        conflict = next(item for item in row["items"] if item["id"] == f"event:{events[1].id}")
        self.assertEqual(conflict["state"], "2")
        self.assertEqual(conflict["reason"], "חסרה יציאה")

        self.env["mdl.attendance.device.event"].timeline_flip_event(events[1].id)
        events.invalidate_recordset()
        self.assertEqual(events.mapped("processing_state"), ["processed", "processed"])
        self.assertEqual(events[0].attendance_id, events[1].attendance_id)
        self.assertEqual(events[0].attendance_id.check_out, events[1].event_datetime)

    def test_conflict_timeline_pairs_events_and_creates_attendance_automatically(self):
        check_in_event = self._pending_event("2026-08-14 06:00:00", "in", "pair-in")
        check_out_event = self._pending_event("2026-08-14 16:00:00", "out", "pair-out")
        self._reconcile_employee()
        (check_in_event | check_out_event).invalidate_recordset()
        self.assertEqual(
            (check_in_event | check_out_event).mapped("processing_state"),
            ["processed", "processed"],
        )
        self.assertEqual(check_in_event.attendance_id, check_out_event.attendance_id)
        attendance = check_in_event.attendance_id
        self.assertEqual(attendance.check_in, check_in_event.event_datetime)
        self.assertEqual(attendance.check_out, check_out_event.event_datetime)
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-01 00:00:00", "2026-09-01 00:00:00",
        )
        self.assertNotIn(self.employee.id, [row["employee_id"] for row in data["rows"]])

    def test_green_attendance_pair_has_no_pair_menu(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": "2026-08-14 06:00:00",
            "check_out": "2026-08-14 16:00:00",
        })
        self._pending_event("2026-08-14 18:00:00", "out", "green-context-conflict")
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-14 00:00:00", "2026-08-15 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        connection = next(
            connection for connection in row["connections"]
            if connection["id"] == f"attendance:{attendance.id}"
        )
        self.assertEqual(connection["state"], "1")
        self.assertEqual(connection["actions"], [])
        green_items = [
            item for item in row["items"]
            if item["source"] == "attendance" and item["source_id"] == attendance.id
        ]
        self.assertTrue(all(
            [action["key"] for action in item["actions"]] == ["open_attendance", "flip_event", "dismiss_event"]
            for item in green_items
        ))

    def test_conflict_timeline_marks_blocked_pair_as_state_seven(self):
        self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": "2026-08-15 10:00:00",
            "check_out": "2026-08-15 12:00:00",
        })
        check_in_event = self._pending_event("2026-08-15 06:00:00", "in", "blocked-in")
        check_out_event = self._pending_event("2026-08-15 16:00:00", "out", "blocked-out")
        self._reconcile_employee()
        initial = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-01 00:00:00", "2026-09-01 00:00:00",
        )
        initial_row = next(row for row in initial["rows"] if row["employee_id"] == self.employee.id)
        initial_connection = next(
            connection for connection in initial_row["connections"]
            if connection["from"] == f"event:{check_in_event.id}"
            and connection["to"] == f"event:{check_out_event.id}"
        )
        self.assertEqual(initial_connection["state"], "7")
        self.assertTrue(initial_connection["blocked"])
        self.assertTrue(check_in_event.conflict_action_failed)
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-01 00:00:00", "2026-09-01 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        failed_items = [
            item for item in row["items"]
            if item["source_id"] in (check_in_event.id, check_out_event.id)
        ]
        self.assertEqual({item["state"] for item in failed_items}, {"7"})
        self.assertTrue(all(
            [action["key"] for action in item["actions"]]
            == ["flip_event", "dismiss_event"]
            for item in failed_items
        ))
        failed_connection = next(
            connection for connection in row["connections"]
            if connection["from"] == f"event:{check_in_event.id}"
            and connection["to"] == f"event:{check_out_event.id}"
        )
        self.assertEqual(failed_connection["actions"], [])

    def test_conflict_timeline_repeated_punches_pair_direct_neighbours_only(self):
        first_in = self._pending_event("2026-08-15 06:00:00", "in", "ambiguous-in-1")
        middle_in = self._pending_event("2026-08-15 06:05:00", "in", "ambiguous-in-2")
        middle_out = self._pending_event("2026-08-15 15:55:00", "out", "ambiguous-out-1")
        last_out = self._pending_event("2026-08-15 16:00:00", "out", "ambiguous-out-2")
        self._reconcile_employee()
        (first_in | middle_in | middle_out | last_out).invalidate_recordset()
        self.assertFalse(first_in.attendance_id)
        self.assertEqual(middle_in.attendance_id, middle_out.attendance_id)
        self.assertFalse(last_out.attendance_id)
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-15 00:00:00", "2026-08-16 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        green_connection = next(
            connection for connection in row["connections"]
            if connection["id"] == f"attendance:{middle_in.attendance_id.id}"
        )
        self.assertEqual(green_connection["state"], "1")
        items_by_id = {
            item.get("event_id") or item.get("source_id"): item
            for item in row["items"]
            if item.get("event_id") or item.get("source") == "event"
        }
        self.assertEqual(items_by_id[middle_in.id]["state"], "1")
        self.assertEqual(items_by_id[middle_out.id]["state"], "1")
        self.assertEqual(items_by_id[first_in.id]["state"], "2")
        self.assertEqual(items_by_id[last_out.id]["state"], "3")

    def test_neighbour_pair_over_24_hours_is_connected_but_red(self):
        check_in_event = self._pending_event(
            "2026-08-14 06:00:00", "in", "neighbour-over-24-in"
        )
        check_out_event = self._pending_event(
            "2026-08-15 06:01:00", "out", "neighbour-over-24-out"
        )
        self._reconcile_employee()
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-14 00:00:00", "2026-08-16 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        connection = next(
            connection for connection in row["connections"]
            if connection["from"] == f"event:{check_in_event.id}"
            and connection["to"] == f"event:{check_out_event.id}"
        )
        self.assertEqual(connection["state"], "7")
        self.assertTrue(connection["blocked"])
        pair_items = [
            item for item in row["items"]
            if item["source_id"] in (check_in_event.id, check_out_event.id)
        ]
        self.assertEqual({item["state"] for item in pair_items}, {"7"})
        self.assertTrue(all("24" in item["reason"] for item in pair_items))

    def test_blocked_out_keeps_existing_open_in_green_and_out_red(self):
        log = self._log()
        self.device._adapter().process_payload(
            log, "ATTLOG", b"", "74\t2026-08-14 06:00:00\t255\t1\t0",
        )
        in_event = log.event_ids
        open_attendance = in_event.attendance_id
        out_event = self._pending_event(
            "2026-08-15 07:00:00", "out", "blocked-open-out",
        )

        self._reconcile_employee()
        (in_event | out_event).invalidate_recordset()
        self.assertEqual(in_event.attendance_id, open_attendance)
        self.assertFalse(open_attendance.check_out)
        self.assertEqual(in_event.processing_state, "processed")
        self.assertFalse(out_event.attendance_id)
        self.assertEqual(out_event.processing_state, "not_applied")

        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-14 00:00:00", "2026-08-16 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        mixed_connection = next(
            connection for connection in row["connections"]
            if connection["from"] == f"attendance:{open_attendance.id}:in"
            and connection["to"] == f"event:{out_event.id}"
        )
        self.assertTrue(mixed_connection["blocked"])

    def test_pending_event_time_and_type_can_be_edited(self):
        event = self._pending_event("2026-08-15 08:00:00", "in", "editable-event")
        other_employee = self.env["hr.employee"].create(
            self._employee_vals("Edited Timeline Employee", self.env.company)
        )
        event.write({
            "event_datetime": "2026-08-15 08:30:00",
            "effective_punch_state": "out",
            "employee_id": other_employee.id,
        })
        self.assertEqual(event.event_datetime, fields.Datetime.to_datetime("2026-08-15 08:30:00"))
        self.assertEqual(event.manual_punch_state, "out")
        self.assertEqual(event.effective_punch_state, "out")
        self.assertEqual(event.employee_id, other_employee)
        self.assertEqual(event.processing_state, "not_applied")
        self.assertTrue(event.timeline_is_edited)

    def test_processed_event_time_edit_updates_attendance_and_marks_the_tile(self):
        log = self._log()
        self.device._adapter().process_payload(
            log, "ATTLOG", b"",
            "74\t2026-08-15 08:00:00\t255\t1\t0\n"
            "74\t2026-08-15 17:00:00\t255\t15\t0",
        )
        in_event, out_event = log.event_ids.sorted("event_datetime")
        attendance = in_event.attendance_id

        in_event.write({"event_datetime": "2026-08-15 07:45:00"})
        self.assertEqual(
            attendance.check_in,
            fields.Datetime.to_datetime("2026-08-15 07:45:00"),
        )
        self.assertEqual(
            attendance.check_out,
            fields.Datetime.to_datetime("2026-08-15 17:00:00"),
        )
        self.assertTrue(in_event.timeline_is_edited)
        self.assertFalse(out_event.timeline_is_edited)

        self._pending_event("2026-08-15 18:00:00", "out", "edited-green-context")
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-15 00:00:00", "2026-08-16 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        in_item = next(
            item for item in row["items"]
            if item.get("event_id") == in_event.id and item["kind"] == "in"
        )
        self.assertTrue(in_item["edited"])

        in_event.write({"event_datetime": "2026-08-15 08:00:00"})
        self.assertFalse(in_event.timeline_is_edited)

    def test_open_in_time_edit_keeps_the_same_attendance_id(self):
        log = self._log()
        self.device._adapter().process_payload(
            log, "ATTLOG", b"", "74\t2026-08-15 08:00:00\t255\t1\t0",
        )
        in_event = log.event_ids
        attendance = in_event.attendance_id

        in_event.write({"event_datetime": "2026-08-15 08:10:00"})
        in_event.invalidate_recordset()
        self.assertEqual(in_event.attendance_id, attendance)
        self.assertEqual(
            attendance.check_in,
            fields.Datetime.to_datetime("2026-08-15 08:10:00"),
        )
        self.assertFalse(attendance.check_out)

    def test_processed_event_invalid_edit_removes_attendance_and_keeps_events_red(self):
        log = self._log()
        self.device._adapter().process_payload(
            log, "ATTLOG", b"",
            "74\t2026-08-16 08:00:00\t255\t1\t0\n"
            "74\t2026-08-16 17:00:00\t255\t15\t0",
        )
        in_event = log.event_ids.sorted("event_datetime")[0]
        attendance = in_event.attendance_id
        in_event.write({"event_datetime": "2026-08-16 18:00:00"})
        in_event.invalidate_recordset()
        attendance.invalidate_recordset()
        self.assertFalse(attendance.exists())
        events = log.event_ids.sorted("event_datetime")
        self.assertEqual(set(events.mapped("processing_state")), {"not_applied"})
        self.assertFalse(any(events.mapped("attendance_id")))

    def test_same_valid_pair_keeps_attendance_id_and_broken_pair_is_recreated(self):
        in_event = self._pending_event("2026-08-15 06:00:00", "in", "dynamic-pair-in")
        out_event = self._pending_event("2026-08-15 07:00:00", "out", "dynamic-pair-out")
        self._reconcile_employee()
        original_attendance = in_event.attendance_id

        in_event.write({"event_datetime": "2026-08-15 05:30:00"})
        self.assertEqual(in_event.attendance_id, original_attendance)
        self.assertEqual(out_event.attendance_id, original_attendance)
        self.assertEqual(
            original_attendance.check_in,
            fields.Datetime.to_datetime("2026-08-15 05:30:00"),
        )

        out_event.write({"effective_punch_state": "in"})
        self.assertFalse(original_attendance.exists())
        self.assertFalse(in_event.attendance_id)
        self.assertFalse(out_event.attendance_id)
        self.assertEqual(set((in_event | out_event).mapped("processing_state")), {"not_applied"})

        out_event.write({"effective_punch_state": "out"})
        self.assertTrue(in_event.attendance_id)
        self.assertEqual(in_event.attendance_id, out_event.attendance_id)
        self.assertNotEqual(in_event.attendance_id.id, original_attendance.id)

    def test_manual_event_action_contains_explicit_form_view(self):
        action = self.env["mdl.attendance.device.event"].timeline_manual_event_action(
            self.employee.id, "out", "2026-08-15 16:00:00",
        )
        self.assertEqual(action["views"], [(False, "form")])

    def test_standalone_events_offer_only_color_specific_actions(self):
        out_event = self._pending_event("2026-08-15 05:00:00", "out", "standalone-out")
        first_in = self._pending_event("2026-08-15 06:00:00", "in", "standalone-in")
        second_in = self._pending_event("2026-08-15 07:00:00", "in", "standalone-red-in")
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-15 00:00:00", "2026-08-16 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        by_source_id = {
            item["source_id"]: item for item in row["items"] if item["source"] == "event"
        }
        self.assertEqual(
            {source_id: item["event_id"] for source_id, item in by_source_id.items()},
            {source_id: source_id for source_id in by_source_id},
        )
        self.assertFalse(any(item["linkable"] for item in by_source_id.values()))
        self.assertEqual(by_source_id[out_event.id]["state"], "3")
        self.assertEqual(
            [action["key"] for action in by_source_id[out_event.id]["actions"]],
            ["flip_event", "dismiss_event"],
        )
        self.assertEqual(by_source_id[first_in.id]["state"], "2")
        self.assertEqual(
            [action["key"] for action in by_source_id[first_in.id]["actions"]],
            ["flip_event", "dismiss_event"],
        )
        self.assertEqual(by_source_id[second_in.id]["state"], "2")
        self.assertEqual(
            [action["key"] for action in by_source_id[second_in.id]["actions"]],
            ["flip_event", "dismiss_event"],
        )

    def test_conflict_timeline_open_attendance_states_follow_schedule_window(self):
        now = fields.Datetime.now() + timedelta(days=1)
        open_attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": now,
        })
        conflict = self._pending_event(now + timedelta(minutes=1), "in", "current-open-context")
        conflict.write({"processing_message": "Employee already has an open attendance"})
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            fields.Datetime.to_string(now - timedelta(days=1)),
            fields.Datetime.to_string(now + timedelta(days=1)),
            [("event_datetime", "!=", False)],
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        open_item = next(item for item in row["items"] if item["id"] == f"attendance:{open_attendance.id}:in")
        self.assertEqual(open_item["state"], "1.5")

    def test_conflict_timeline_overdue_open_attendance_is_conflict(self):
        now = fields.Datetime.now()
        open_attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": now - timedelta(days=3),
        })
        conflict = self._pending_event(
            open_attendance.check_in + timedelta(minutes=1), "in", "overdue-open-context",
        )
        conflict.write({"processing_message": "Employee already has an open attendance"})
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            fields.Datetime.to_string(now - timedelta(days=4)),
            fields.Datetime.to_string(now + timedelta(days=1)),
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        open_item = next(
            item for item in row["items"]
            if item["id"] == f"attendance:{open_attendance.id}:in"
        )
        self.assertEqual(open_item["state"], "2")
        self.assertFalse(any(item.get("placeholder") for item in row["items"]))
        self.assertFalse(any(
            connection["id"] == f"attendance:{open_attendance.id}"
            for connection in row["connections"]
        ))
        self.assertEqual(
            [action["key"] for action in open_item["actions"]],
            ["open_attendance", "flip_event", "dismiss_event"],
        )

    def test_single_processed_in_uses_daily_hours_not_schedule(self):
        hours = self.employee.resource_calendar_id.hours_per_day or 8.0
        now = fields.Datetime.now()
        Event = self.env["mdl.attendance.device.event"]
        self.assertFalse(Event._timeline_open_in_overdue(
            now, self.employee, now + timedelta(hours=hours),
        ))
        self.assertTrue(Event._timeline_open_in_overdue(
            now, self.employee, now + timedelta(hours=hours, seconds=1),
        ))
        check_in = now - timedelta(hours=hours, minutes=-5)
        event = self._pending_event(check_in, "in", "single-within-daily-hours")
        event.action_process()
        self.assertEqual(event.processing_state, "processed")
        self.assertFalse(event.attendance_id.check_out)
        later_in = self._pending_event(check_in + timedelta(minutes=1), "in", "second-within-daily-hours")
        later_in.action_process()
        self.assertEqual(later_in.processing_state, "not_applied")
        conflicts = self.env["mdl.attendance.device.event"].search([
            ("id", "in", (event | later_in).ids), ("mdl_is_conflict", "=", True),
        ])
        self.assertFalse(conflicts)
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            fields.Datetime.to_string(check_in - timedelta(hours=1)),
            fields.Datetime.to_string(now + timedelta(hours=1)),
        )
        self.assertNotIn(self.employee.id, [row["employee_id"] for row in data["rows"]])

    def test_single_processed_in_becomes_conflict_after_daily_hours(self):
        hours = self.employee.resource_calendar_id.hours_per_day or 8.0
        now = fields.Datetime.now()
        check_in = now - timedelta(hours=hours, minutes=5)
        event = self._pending_event(check_in, "in", "single-over-daily-hours")
        event.action_process()
        self.assertEqual(event.processing_state, "processed")
        self.assertIn(event, self.env["mdl.attendance.device.event"].search([
            ("id", "=", event.id), ("mdl_is_conflict", "=", True),
        ]))
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            fields.Datetime.to_string(check_in - timedelta(hours=1)),
            fields.Datetime.to_string(now + timedelta(hours=1)),
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        item = next(item for item in row["items"] if item["id"] == f"attendance:{event.attendance_id.id}:in")
        self.assertEqual(item["state"], "2")
        self.assertIn("מכסת השעות היומית", item["reason"])

    def test_conflict_timeline_excludes_open_attendance_without_raw_events(self):
        now = fields.Datetime.now()
        open_attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": now - timedelta(days=3),
        })
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            fields.Datetime.to_string(now - timedelta(days=4)),
            fields.Datetime.to_string(now + timedelta(days=1)),
        )
        self.assertNotIn(self.employee.id, [row["employee_id"] for row in data["rows"]])

    def test_conflict_timeline_long_attendance_stays_green_as_context(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": "2026-08-18 01:00:00",
            "check_out": "2026-08-18 22:00:00",
        })
        self._pending_event("2026-08-18 23:00:00", "out", "long-attendance-context")
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-18 00:00:00", "2026-08-19 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        items = [
            item for item in row["items"]
            if item["source"] == "attendance" and item["source_id"] == attendance.id
        ]
        self.assertEqual(len(items), 2)
        self.assertEqual({item["state"] for item in items}, {"1"})

    def test_manual_conflict_event_does_not_change_attendance(self):
        wizard = self.env["mdl.attendance.conflict.event.wizard"].create({
            "employee_id": self.employee.id,
            "device_id": self.device.id,
            "punch_state": "out",
            "event_datetime": "2026-08-16 16:00:00",
        })
        before = self.env["hr.attendance"].search_count([("employee_id", "=", self.employee.id)])
        wizard.action_create_event()
        event = self.env["mdl.attendance.device.event"].search([
            ("employee_id", "=", self.employee.id),
            ("event_datetime", "=", "2026-08-16 16:00:00"),
        ], order="id desc", limit=1)
        self.assertEqual(event.processing_state, "not_applied")
        self.assertEqual(event.punch_state, "out")
        self.assertEqual(event.log_id.request_type, "MANUAL")
        self.assertEqual(
            self.env["hr.attendance"].search_count([("employee_id", "=", self.employee.id)]),
            before,
        )

    @mute_logger("odoo.addons.mdl_zkteco_attendance.services.adapters.zkteco")
    def test_malformed_line_is_preserved_as_error_event(self):
        log = self._log()
        self.device._adapter().process_payload(log, "ATTLOG", b"", "malformed-attlog-line")
        self.assertEqual(len(log.event_ids), 1)
        self.assertEqual(log.event_ids.processing_state, "error")
        self.assertEqual(log.event_ids.raw_line, "malformed-attlog-line")

    def test_manual_cards_use_maximum_identifier_plus_one(self):
        self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True
        ).create({
            "device_id": self.device.id,
            "device_user_id": "100",
            "device_name": "Highest existing card",
        })
        card = self.env["mdl.attendance.device.employee"].create({
            "device_id": self.device.id,
            "device_name": "New system card",
        })
        self.assertEqual(card.device_user_id, "101")
        self.assertFalse(card.employee_id)
        self.assertTrue(card.device_id)
        self.assertEqual(card.sync_state, "pending_push")
        self.assertTrue(card.env["mdl.attendance.device.command"].search_count([
            ("device_employee_id", "=", card.id),
            ("command_type", "=", "create_user"),
            ("state", "=", "queued"),
        ]))

    def test_native_import_requires_explicit_device_user_id(self):
        cards = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
            import_file=True,
        )
        with self.assertRaises(ValidationError):
            cards.create({
                "device_id": self.device.id,
                "device_name": "Missing imported identifier",
            })
        card = cards.create({
            "device_id": self.device.id,
            "device_user_id": "imported-901",
            "device_name": "Imported card",
        })
        self.assertEqual(card.device_user_id, "imported-901")

    def test_deleting_odoo_card_queues_device_deletion(self):
        card = self.env["mdl.attendance.device.employee"].create({
            "device_id": self.device.id,
            "device_name": "Delete me",
        })
        pin = card.device_user_id
        card.unlink()
        command = self.env["mdl.attendance.device.command"].search([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "delete_user"),
            ("state", "=", "queued"),
        ], order="id desc", limit=1)
        self.assertEqual(command.raw_command, f"DATA DELETE USERINFO PIN={pin}")
        self.assertFalse(command.device_employee_id)

    def test_user_privilege_and_verification_push_and_pull(self):
        self.card.write({
            "device_privilege": "14",
            "has_face": True,
            "has_fingerprint": True,
            "verification_mode": "19",
        })
        adapter = self.device._adapter()
        self.assertEqual(adapter.build_command("update_privilege", self.card),
                         "DATA UPDATE USERINFO PIN=74\tName=Clock Employee\tPri=14\tVerify=19")
        self.assertEqual(adapter.build_command("update_verification_mode", self.card),
                         "DATA UPDATE USERINFO PIN=74\tName=Clock Employee\tPri=14\tVerify=19")
        self.card._queue_command("request_privilege")
        self.card._queue_command("request_verification_mode")
        self.card._queue_command("request_user")
        log = self._log()
        adapter.process_payload(
            log, "USERINFO", b"", "USER PIN=74\tName=Clock Employee Updated\tPri=0\tVerify=15",
        )
        self.assertEqual(self.card.device_name, "Clock Employee Updated")
        self.assertEqual(self.card.device_privilege, "0")
        self.assertEqual(self.card.verification_mode, "15")

    def test_device_delete_operlog_deletes_odoo_card_without_loop(self):
        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True
        ).create({
            "device_id": self.device.id,
            "device_user_id": "222",
            "device_name": "Deleted on clock",
        })
        log = self._log()
        log.write({"request_type": "OPERLOG"})
        self.device._adapter().process_payload(
            log, "OPERLOG", b"", "OPLOG 9\t0\t2026-08-19 10:00:00\t222\t0\t0\t0\n"
        )
        self.assertFalse(card.exists())
        self.assertFalse(self.env["mdl.attendance.device.command"].search_count([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "delete_user"),
            ("raw_command", "=", "DATA DELETE USERINFO PIN=222"),
        ]))

    def test_card_fields_are_pushed_automatically_without_manual_sync(self):
        self.card.with_context(
            skip_card_sync=True,
            skip_biometric_verification_constraint=True,
        ).write({"has_face": True, "has_fingerprint": True})
        self.card.write({
            "device_name": "Automatic clock name",
            "device_privilege": "14",
            "verification_mode": "19",
        })

        commands = self.env["mdl.attendance.device.command"].search([
            ("device_employee_id", "=", self.card.id),
            ("state", "=", "queued"),
            ("command_type", "in", [
                "update_name", "update_privilege", "update_verification_mode",
            ]),
        ])
        self.assertEqual(
            set(commands.mapped("command_type")),
            {"update_name", "update_privilege", "update_verification_mode"},
        )
        self.assertTrue(all("Name=Automatic clock name" in command.raw_command for command in commands))

    def test_clock_user_and_biometrics_are_applied_without_manual_pull(self):
        adapter = self.device._adapter()
        log = self._log()
        adapter.process_payload(
            log,
            "USERINFO",
            b"",
            "USER PIN=74\tName=Changed on terminal\tPri=14\tVerify=19\tFPCount=2\tFaceCount=1",
        )
        self.card.invalidate_recordset()
        self.assertEqual(self.card.device_name, "Changed on terminal")
        self.assertEqual(self.card.device_privilege, "14")
        self.assertEqual(self.card.verification_mode, "19")
        self.assertTrue(self.card.has_fingerprint)
        self.assertTrue(self.card.has_face)

        adapter.process_payload(
            self._log(), "USERINFO", b"",
            "USER PIN=74\tName=Changed on terminal\tPri=0\tVerify=0\tFPCount=0\tFaceCount=0",
        )
        self.card.invalidate_recordset()
        self.assertFalse(self.card.has_fingerprint)
        self.assertFalse(self.card.has_face)

    def test_existing_face_template_backfills_readonly_face_flag(self):
        self.card.with_context(
            skip_card_sync=True,
            skip_biometric_verification_constraint=True,
        ).write({"face_template": b"dGVzdC1mYWNlLXRlbXBsYXRl", "has_face": False})
        self.env.flush_all()
        self.env["mdl.attendance.device.employee"].init()
        self.card.invalidate_recordset(["has_face"])
        self.assertTrue(self.card.has_face)

    def test_unified_biodata_updates_fingerprint_and_face_independently(self):
        face_card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.device.id,
            "device_user_id": "75",
            "device_name": "Face only",
        })
        (self.card | face_card).with_context(
            skip_card_sync=True,
            skip_biometric_verification_constraint=True,
        ).write({"has_face": False, "has_fingerprint": False})

        log = self._log()
        self.device._adapter().process_payload(
            log,
            "BIODATA",
            b"",
            "BIODATA PIN=74\tType=1\tValid=1\tTMP=fingerprint-template\n"
            "BIODATA PIN=75\tBioType=9\tValid=1\tTMP=face-template",
        )
        (self.card | face_card).invalidate_recordset(
            ["has_face", "has_fingerprint"]
        )
        self.assertTrue(self.card.has_fingerprint)
        self.assertFalse(self.card.has_face)
        self.assertTrue(face_card.has_face)
        self.assertFalse(face_card.has_fingerprint)

        self.device._adapter().process_payload(
            self._log(),
            "BIODATA",
            b"",
            "BIODATA PIN=74\tType=1\tValid=0\tTMP=",
        )
        self.card.invalidate_recordset(["has_fingerprint"])
        self.assertFalse(self.card.has_fingerprint)

    def test_operlog_unified_fingerprint_biodata_updates_card_flag(self):
        self.card.with_context(
            skip_card_sync=True,
            skip_biometric_verification_constraint=True,
        ).write({"has_face": False, "has_fingerprint": False})
        self.device._adapter().process_payload(
            self._log(),
            "OPERLOG",
            b"",
            "BIODATA PIN=74\tType=1\tValid=1\tTMP=fingerprint-template",
        )
        self.card.invalidate_recordset(["has_face", "has_fingerprint"])
        self.assertTrue(self.card.has_fingerprint)
        self.assertFalse(self.card.has_face)

    def test_fingerprint_binary_file_queues_push_and_delete_commands(self):
        raw_template = b"ZKFP-template-binary\x00\x01\x02"
        fingerprint = self.env["mdl.attendance.device.fingerprint"].create({
            "device_employee_id": self.card.id,
            "finger_index": "6",
            "template_file": base64.b64encode(raw_template),
            "filename": "finger_6.fpt",
        })
        self.card.invalidate_recordset(["has_fingerprint"])
        self.assertFalse(self.card.has_fingerprint)
        command = self.env["mdl.attendance.device.command"].search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "update_fingerprint"),
            ("fingerprint_index", "=", "6"),
            ("state", "=", "queued"),
        ], limit=1)
        payload = base64.b64encode(raw_template).decode("ascii")
        self.assertEqual(
            command.raw_command,
            "DATA UPDATE BIODATA Pin=74\tNo=6\tIndex=0\tValid=1"
            "\tDuress=0\tType=1\tMajorVer=13\tMinorVer=0\tFormat=0"
            f"\tTmp={payload}",
        )

        fingerprint.with_context(skip_fingerprint_sync=False).unlink()
        self.card.invalidate_recordset(["has_fingerprint"])
        self.assertFalse(self.card.has_fingerprint)
        delete_command = self.env["mdl.attendance.device.command"].search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "delete_fingerprint"),
            ("fingerprint_index", "=", "6"),
            ("state", "=", "queued"),
        ], limit=1)
        self.assertEqual(
            delete_command.raw_command,
            "DATA DELETE BIODATA Pin=74\tType=1\tNo=6",
        )

    def test_terminal_fingerprint_enrollment_is_pulled_automatically(self):
        Command = self.env["mdl.attendance.device.command"]
        Command.search([("device_employee_id", "=", self.card.id)]).unlink()
        adapter = self.device._adapter()

        adapter.process_payload(
            self._log(),
            "OPERLOG",
            b"",
            "OPLOG 6\t0\t2026-08-26 09:00:00\t74\t6\t1048\t0",
        )
        snapshot = Command.search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "request_fingerprints"),
            ("fingerprint_index", "=", False),
        ], limit=1)
        self.assertTrue(snapshot)
        self.assertEqual(snapshot.raw_command, "DATA QUERY BIODATA Pin=74")

        snapshot.mark_sent()
        snapshot.mark_result(0, "ID=10&Return=0&CMD=DATA")
        self.assertEqual(snapshot.state, "sent")
        payload = base64.b64encode(b"enrolled-directly-on-clock").decode("ascii")
        log = self._log()
        log.write({
            "request_type": "BIODATA",
            "query_string": "SN=TEST-SN&table=BIODATA&OpStamp=10000",
        })
        adapter.process_payload(
            log,
            "BIODATA",
            b"",
            "BIODATA Pin=74\tNo=6\tIndex=0\tValid=1\tDuress=0"
            "\tType=1\tMajorVer=13\tMinorVer=0\tFormat=0"
            f"\tTmp={payload}",
        )

        fingerprint = self.card.fingerprint_ids
        snapshot.invalidate_recordset()
        self.card.invalidate_recordset(["has_fingerprint"])
        self.assertEqual(snapshot.state, "done")
        self.assertEqual(fingerprint.finger_index, "6")
        self.assertEqual(fingerprint.source, "device")
        self.assertTrue(self.card.has_fingerprint)

    def test_terminal_fingerprint_delete_reconciles_only_missing_slot(self):
        Fingerprint = self.env[
            "mdl.attendance.device.fingerprint"
        ].with_context(skip_fingerprint_sync=True)
        first = Fingerprint.create({
            "device_employee_id": self.card.id,
            "finger_index": "1",
            "template_file": base64.b64encode(b"finger-one"),
            "source": "device",
        })
        second = Fingerprint.create({
            "device_employee_id": self.card.id,
            "finger_index": "6",
            "template_file": base64.b64encode(b"finger-six"),
            "source": "device",
        })
        adapter = self.device._adapter()
        adapter.process_payload(
            self._log(),
            "OPERLOG",
            b"",
            "OPLOG 10\t0\t2026-08-26 09:05:00\t74\t0\t0\t0",
        )
        snapshot = self.env["mdl.attendance.device.command"].search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "request_fingerprints"),
            ("fingerprint_index", "=", False),
        ], limit=1)
        snapshot.mark_sent()
        snapshot.mark_result(0, "ID=11&Return=0&CMD=DATA")
        payload = base64.b64encode(b"finger-six").decode("ascii")
        log = self._log()
        log.write({
            "request_type": "BIODATA",
            "query_string": "SN=TEST-SN&table=BIODATA&OpStamp=10001",
        })
        adapter.process_payload(
            log,
            "BIODATA",
            b"",
            "BIODATA Pin=74\tNo=6\tIndex=0\tValid=1\tDuress=0"
            "\tType=1\tMajorVer=13\tMinorVer=0\tFormat=0"
            f"\tTmp={payload}",
        )

        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(self.card.fingerprint_ids.mapped("finger_index"), ["6"])
        self.card.invalidate_recordset(["has_fingerprint"])
        self.assertTrue(self.card.has_fingerprint)

        adapter.process_payload(
            self._log(),
            "OPERLOG",
            b"",
            "OPLOG 10\t0\t2026-08-26 09:06:00\t74\t0\t0\t0",
        )
        last_snapshot = self.env["mdl.attendance.device.command"].search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "request_fingerprints"),
            ("fingerprint_index", "=", False),
            ("state", "=", "queued"),
        ], limit=1)
        last_snapshot.mark_sent()
        last_snapshot.mark_result(0, "ID=14&Return=0&CMD=DATA")
        empty_log = self._log()
        empty_log.write({
            "request_type": "BIODATA",
            "query_string": "SN=TEST-SN&table=BIODATA&OpStamp=10003",
        })
        adapter.process_payload(empty_log, "BIODATA", b"", "")
        self.assertFalse(second.exists())
        self.card.invalidate_recordset(["has_fingerprint"])
        self.assertFalse(self.card.has_fingerprint)

    def test_odoo_fingerprint_delete_is_verified_absent_on_terminal(self):
        fingerprint = self.env[
            "mdl.attendance.device.fingerprint"
        ].with_context(skip_fingerprint_sync=True).create({
            "device_employee_id": self.card.id,
            "finger_index": "4",
            "template_file": base64.b64encode(b"finger-four"),
            "source": "device",
        })
        fingerprint.with_context(skip_fingerprint_sync=False).unlink()
        Command = self.env["mdl.attendance.device.command"]
        delete = Command.search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "delete_fingerprint"),
            ("fingerprint_index", "=", "4"),
        ], limit=1)
        self.assertEqual(
            delete.raw_command,
            "DATA DELETE BIODATA Pin=74\tType=1\tNo=4",
        )
        delete.mark_sent()
        delete.mark_result(0, "ID=12&Return=0&CMD=DATA")
        verification = Command.search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "request_fingerprints"),
            ("fingerprint_index", "=", "4"),
        ], limit=1)
        verification.mark_sent()
        verification.mark_result(0, "ID=13&Return=0&CMD=DATA")
        log = self._log()
        log.write({
            "request_type": "BIODATA",
            "query_string": "SN=TEST-SN&table=BIODATA&OpStamp=10002",
        })
        self.device._adapter().process_payload(log, "BIODATA", b"", "")
        verification.invalidate_recordset()
        self.card.invalidate_recordset(["has_fingerprint", "sync_state"])
        self.assertEqual(verification.state, "done")
        self.assertFalse(self.card.has_fingerprint)
        self.assertEqual(self.card.sync_state, "synced")

    def test_fingerprint_number_cannot_change_after_creation(self):
        fingerprint = self.env[
            "mdl.attendance.device.fingerprint"
        ].with_context(skip_fingerprint_sync=True).create({
            "device_employee_id": self.card.id,
            "finger_index": "3",
            "template_file": base64.b64encode(b"finger-three"),
        })
        self.assertTrue(fingerprint.finger_index_locked)
        fingerprint.write({"finger_index": "3"})
        fingerprint.write({
            "template_file": base64.b64encode(b"replacement-template"),
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            fingerprint.write({"finger_index": "4"})

    def test_zkteco_ini_upload_extracts_matching_user_and_finger(self):
        raw_template = b"ZKFP-from-ini\x00\x03"
        payload = base64.b64encode(raw_template).decode("ascii")
        ini_content = (
            "[User_12]\nFPT_6=QUJD\nNoFingers=1\n\n"
            f"[User_74]\nFPT_6={payload}\nNoFingers=1\n"
        )
        self.env["mdl.attendance.device.fingerprint"].create({
            "device_employee_id": self.card.id,
            "finger_index": "6",
            "template_file": base64.b64encode(ini_content.encode("utf-8")),
            "filename": "clock_backup.ini",
        })
        command = self.env["mdl.attendance.device.command"].search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "update_fingerprint"),
            ("fingerprint_index", "=", "6"),
        ], limit=1)
        self.assertIn(f"Tmp={payload}", command.raw_command)
        self.assertNotIn("W1VzZXJf", command.raw_command)

    def test_fingerprint_number_is_unique_per_card(self):
        Fingerprint = self.env["mdl.attendance.device.fingerprint"].with_context(
            skip_fingerprint_sync=True,
        )
        values = {
            "device_employee_id": self.card.id,
            "finger_index": "4",
            "template_file": base64.b64encode(b"finger-four"),
        }
        Fingerprint.create(values)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Fingerprint.create(values)

    def test_ini_user_number_matches_card_identifier_with_leading_zeroes(self):
        zero_padded_card = self.env[
            "mdl.attendance.device.employee"
        ].with_context(attendance_device_discovery=True).create({
            "device_id": self.device.id,
            "device_user_id": "0075",
            "device_name": "Zero padded",
        })
        payload = base64.b64encode(b"zero-padded-user-fingerprint").decode("ascii")
        ini_content = f"[User_75]\nFPT_3={payload}\nNoFingers=1\n"
        fingerprint = self.env["mdl.attendance.device.fingerprint"].create({
            "device_employee_id": zero_padded_card.id,
            "finger_index": "3",
            "template_file": base64.b64encode(ini_content.encode("utf-8")),
            "filename": "clock_backup.ini",
        })
        command = self.env["mdl.attendance.device.command"].search([
            ("device_employee_id", "=", zero_padded_card.id),
            ("command_type", "=", "update_fingerprint"),
            ("fingerprint_index", "=", "3"),
        ], limit=1)
        self.assertEqual(fingerprint._template_payload(), payload)
        self.assertIn(f"Pin=0075", command.raw_command)
        self.assertIn(f"Tmp={payload}", command.raw_command)

    def test_fingerprint_biodata_push_is_verified_by_native_readback(self):
        Command = self.env["mdl.attendance.device.command"]
        Command.search([("device_employee_id", "=", self.card.id)]).unlink()
        raw_template = b"native-mb560-fingerprint-template"
        payload = base64.b64encode(raw_template).decode("ascii")
        fingerprint = self.env["mdl.attendance.device.fingerprint"].create({
            "device_employee_id": self.card.id,
            "finger_index": "6",
            "template_file": base64.b64encode(raw_template),
            "filename": "native_6.fpt",
        })
        self.card.invalidate_recordset(["has_fingerprint", "sync_state"])
        self.assertFalse(self.card.has_fingerprint)
        self.assertEqual(self.card.sync_state, "pending_push")

        push = Command.search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "update_fingerprint"),
            ("fingerprint_index", "=", "6"),
        ], limit=1)
        push.mark_sent()
        push.mark_result(0, "ID=1&Return=0&CMD=DATA")
        verification = Command.search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "request_fingerprints"),
            ("fingerprint_index", "=", "6"),
        ], limit=1)
        self.assertEqual(
            verification.raw_command,
            "DATA QUERY BIODATA Pin=74",
        )
        self.assertTrue(verification.fingerprint_verification_hash)
        self.card.invalidate_recordset(["sync_state"])
        self.assertEqual(self.card.sync_state, "pending_pull")

        verification.mark_sent()
        verification.mark_result(0, "ID=2&Return=0&CMD=DATA")
        self.assertEqual(verification.state, "sent")
        log = self._log()
        log.write({
            "request_type": "BIODATA",
            "query_string": "SN=TEST-SN&table=BIODATA&OpStamp=9999",
        })
        self.device._adapter().process_payload(
            log,
            "BIODATA",
            b"",
            "BIODATA Pin=74\tNo=6\tIndex=0\tValid=1\tDuress=0"
            "\tType=1\tMajorVer=13\tMinorVer=0\tFormat=0"
            f"\tTmp={payload}",
        )
        verification.invalidate_recordset()
        fingerprint.invalidate_recordset()
        self.card.invalidate_recordset(["has_fingerprint", "sync_state"])
        self.assertEqual(verification.state, "done")
        self.assertTrue(self.card.has_fingerprint)
        self.assertEqual(self.card.sync_state, "synced")
        self.assertEqual(fingerprint.source, "device")
        self.assertEqual(fingerprint.major_version, 13)
        self.assertEqual(fingerprint.minor_version, 0)
        self.assertEqual(fingerprint.template_format, 0)

    def test_fingerprint_push_missing_from_full_biodata_is_an_error(self):
        Command = self.env["mdl.attendance.device.command"]
        Command.search([("device_employee_id", "=", self.card.id)]).unlink()
        fingerprint = self.env["mdl.attendance.device.fingerprint"].create({
            "device_employee_id": self.card.id,
            "finger_index": "1",
            "template_file": base64.b64encode(b"rejected-template"),
        })
        push = Command.search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "update_fingerprint"),
        ], limit=1)
        push.mark_result(0, "ID=3&Return=0&CMD=DATA")
        verification = Command.search([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "request_fingerprints"),
            ("fingerprint_index", "=", "1"),
        ], limit=1)
        verification.mark_result(0, "ID=4&Return=0&CMD=DATA")
        log = self._log()
        log.write({
            "request_type": "BIODATA",
            "query_string": "SN=TEST-SN&table=BIODATA&OpStamp=9999",
        })
        self.device._adapter().process_payload(
            log,
            "BIODATA",
            b"",
            "BIODATA Pin=75\tNo=0\tIndex=0\tValid=1\tDuress=0"
            "\tType=9\tMajorVer=40\tMinorVer=1\tFormat=0\tTmp=face",
        )
        verification.invalidate_recordset()
        fingerprint.invalidate_recordset()
        self.card.invalidate_recordset(["has_fingerprint", "sync_state"])
        self.assertEqual(verification.state, "failed")
        self.assertIn("not returned", verification.error_message)
        self.assertEqual(fingerprint.source, "odoo")
        self.assertFalse(self.card.has_fingerprint)
        self.assertEqual(self.card.sync_state, "error")

    def test_fingerprint_pull_stores_each_template_and_updates_checkbox(self):
        first_payload = base64.b64encode(b"finger-zero").decode("ascii")
        second_payload = base64.b64encode(b"finger-six").decode("ascii")
        self.device._adapter().process_payload(
            self._log(),
            "FINGERTMP",
            b"",
            f"FP PIN=74\tFID=0\tValid=1\tTMP={first_payload}\n"
            f"FP PIN=74\tFID=6\tValid=1\tTMP={second_payload}",
        )
        fingerprints = self.card.fingerprint_ids.sorted("finger_index")
        self.assertEqual(fingerprints.mapped("finger_index"), ["0", "6"])
        self.assertEqual(
            base64.b64decode(fingerprints[0].template_file), b"finger-zero"
        )
        self.assertEqual(
            base64.b64decode(fingerprints[1].template_file), b"finger-six"
        )
        self.assertTrue(self.card.has_fingerprint)
        self.assertFalse(self.env["mdl.attendance.device.command"].search_count([
            ("device_employee_id", "=", self.card.id),
            ("command_type", "=", "update_fingerprint"),
        ]))

        self.device._adapter().process_payload(
            self._log(), "FINGERTMP", b"", "FP PIN=74\tFID=0\tValid=0\tTMP="
        )
        self.assertEqual(self.card.fingerprint_ids.mapped("finger_index"), ["6"])
        self.assertTrue(self.card.has_fingerprint)
        self.device._adapter().process_payload(
            self._log(), "FINGERTMP", b"", "FP PIN=74\tFID=6\tValid=0\tTMP="
        )
        self.assertFalse(self.card.fingerprint_ids)
        self.assertFalse(self.card.has_fingerprint)

    def test_successful_biometric_photo_push_updates_readonly_face_flag(self):
        image = (
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            b"+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.card.with_context(
            skip_card_sync=True,
            skip_biometric_verification_constraint=True,
        ).write({"biometric_photo": image, "has_face": False})
        command = self.env["mdl.attendance.device.command"].create({
            "device_id": self.device.id,
            "device_employee_id": self.card.id,
            "command_type": "update_biometric_photo",
            "state": "sent",
            "raw_command": "DATA UPDATE BIOPHOTO PIN=74",
        })
        command.mark_result(0, "OK")
        self.assertTrue(self.card.has_face)

        self.card.with_context(
            skip_card_sync=True,
            skip_biometric_verification_constraint=True,
        ).write({"biometric_photo": False})
        delete_command = self.env["mdl.attendance.device.command"].create({
            "device_id": self.device.id,
            "device_employee_id": self.card.id,
            "command_type": "update_biometric_photo",
            "state": "sent",
            "raw_command": "DATA DELETE BIOPHOTO PIN=74 Type=9",
        })
        delete_command.mark_result(0, "OK")
        self.assertFalse(self.card.has_face)

    def test_device_language_and_cooldown_are_synchronized_both_directions(self):
        self.device.write({
            "device_language": "en_US",
            "attendance_cooldown_minutes": 7,
        })
        Command = self.env["mdl.attendance.device.command"]
        language_push = Command.search([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "update_device_language"),
        ], order="id desc", limit=1)
        cooldown_push = Command.search([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "update_device_cooldown"),
        ], order="id desc", limit=1)
        self.assertEqual(language_push.raw_command, "SET OPTIONS Language=69")
        self.assertEqual(
            cooldown_push.raw_command,
            "SET OPTIONS RecheckMin=1,AlarmReRec=7",
        )
        reload_command = Command.search([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "reload_device_options"),
            ("state", "=", "queued"),
        ], order="id desc", limit=1)
        self.assertEqual(reload_command.raw_command, "RELOAD OPTIONS")
        self.assertGreater(reload_command.id, language_push.id)
        self.assertGreater(reload_command.id, cooldown_push.id)

        language_push.mark_result(0, "OK")
        cooldown_push.mark_result(0, "OK")
        reload_command.mark_result(0, "OK")
        options_query = self.device._queue_device_command(
            "request_device_options",
            "GET OPTIONS Language,RecheckMin,AlarmReRec",
        )
        adapter = self.device._adapter()
        adapter.process_command_response(
            options_query,
            "Language=66,RecheckMin=1,AlarmReRec=4",
        )
        self.device.invalidate_recordset()
        self.assertEqual(self.device.device_language, "ar_001")
        self.assertEqual(self.device.attendance_cooldown_minutes, 4)
        self.assertFalse(Command.search_count([
            ("device_id", "=", self.device.id),
            ("command_type", "in", ["update_device_language", "update_device_cooldown"]),
            ("state", "=", "queued"),
        ]))

    def test_unsolicited_options_payload_updates_managed_device_settings(self):
        self.device.with_context(skip_device_setting_sync=True).write({
            "device_language": "he_IL",
            "attendance_cooldown_minutes": 0,
        })
        log = self._log()
        log.request_type = "OPTIONS"
        count = self.device._adapter().process_payload(
            log,
            "OPTIONS",
            b"",
            "~DeviceName=MB560-VL,Language=66,RecheckMin=1,AlarmReRec=9",
        )
        self.device.invalidate_recordset()
        self.assertEqual(count, 2)
        self.assertEqual(self.device.device_language, "ar_001")
        self.assertEqual(self.device.attendance_cooldown_minutes, 9)
        self.assertEqual(log.processing_state, "processed")

    def test_device_setting_operlog_with_zero_pin_triggers_immediate_readback(self):
        Command = self.env["mdl.attendance.device.command"]
        Command.search([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "request_device_options"),
        ]).unlink()
        log = self._log()
        log.request_type = "OPERLOG"
        self.device._adapter().process_payload(
            log,
            "OPERLOG",
            b"",
            "OPLOG 108\t0\t2026-08-25 11:22:42\t0\tLanguage\t0\t0",
        )
        command = Command.search([
            ("device_id", "=", self.device.id),
            ("command_type", "=", "request_device_options"),
        ], limit=1)
        self.assertEqual(
            command.raw_command,
            "GET OPTIONS Language,RecheckMin,AlarmReRec",
        )

    def test_single_device_sync_wizard_queues_complete_pull_without_biophoto(self):
        Command = self.env["mdl.attendance.device.command"]
        Command.search([("device_id", "=", self.device.id)]).unlink()
        wizard = self.env["mdl.attendance.device.sync.wizard"].create({
            "device_id": self.device.id,
            "direction": "pull",
        })
        wizard.action_confirm()
        commands = Command.search([("device_id", "=", self.device.id)])
        self.assertTrue({
            "request_users",
            "request_fingerprints",
            "request_face_templates",
            "request_device_options",
            "request_attendance_logs",
            "request_profile_photo",
        }.issubset(set(commands.mapped("command_type"))))
        self.assertNotIn("request_biometric_photo", commands.mapped("command_type"))
        option_command = commands.filtered(
            lambda item: item.command_type == "request_device_options"
        )
        self.assertEqual(
            option_command.raw_command,
            "GET OPTIONS Language,RecheckMin,AlarmReRec",
        )
        fingerprint_command = commands.filtered(
            lambda item: item.command_type == "request_fingerprints"
        )
        self.assertEqual(fingerprint_command.raw_command, "DATA QUERY BIODATA")

    def test_single_device_sync_wizard_queues_complete_push(self):
        Command = self.env["mdl.attendance.device.command"]
        Command.search([("device_id", "=", self.device.id)]).unlink()
        self.card.with_context(skip_card_sync=True).write({
            "profile_photo": False,
            "biometric_photo": False,
        })
        wizard = self.env["mdl.attendance.device.sync.wizard"].create({
            "device_id": self.device.id,
            "direction": "push",
        })
        wizard.action_confirm()
        commands = Command.search([("device_id", "=", self.device.id)])
        self.assertTrue({
            "update_device_language",
            "update_device_cooldown",
            "reload_device_options",
            "create_user",
        }.issubset(set(commands.mapped("command_type"))))
        self.assertFalse(commands.filtered(
            lambda command: command.command_type in (
                "update_profile_photo", "update_biometric_photo",
            )
        ))

    def test_empty_card_fields_are_never_queued_for_push(self):
        Command = self.env["mdl.attendance.device.command"]
        Command.search([("device_employee_id", "=", self.card.id)]).unlink()
        self.card.with_context(skip_card_sync=True).write({
            "device_name": False,
            "profile_photo": False,
            "biometric_photo": False,
        })

        self.card.write({
            "device_name": False,
            "profile_photo": False,
            "biometric_photo": False,
        })
        self.card._queue_command("update_name")
        self.card._queue_command("update_profile_photo")
        self.card._queue_command("update_biometric_photo")
        commands = Command.search([("device_employee_id", "=", self.card.id)])
        self.assertFalse(commands.filtered(
            lambda command: command.command_type in (
                "update_name", "update_profile_photo", "update_biometric_photo",
            )
        ))
        create_command = self.device._adapter().build_command("create_user", self.card)
        self.assertNotIn("\tName=", create_command)

    def test_hourly_fallback_queues_all_clock_reconciliation_requests(self):
        commands = self.device._queue_automatic_sync(force=True)
        self.assertEqual(
            set(commands.mapped("command_type")),
            {
                "request_users",
                "request_fingerprints",
                "request_face_templates",
                "request_device_options",
            },
        )
        self.assertTrue(self.device.last_automatic_sync_at)
        self.assertFalse(self.device._queue_automatic_sync())

    def test_conflict_view_does_not_mutate_a_stale_valid_pair(self):
        check_in = self._pending_event(
            "2026-08-24 13:43:10", "in", "stale-view-in",
        )
        check_out = self._pending_event(
            "2026-08-24 13:43:50", "out", "stale-view-out",
        )
        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-24 00:00:00", "2026-08-25 00:00:00",
        )
        (check_in | check_out).invalidate_recordset()
        self.assertFalse(check_in.attendance_id)
        self.assertFalse(check_out.attendance_id)
        self.assertEqual(
            (check_in | check_out).mapped("processing_state"),
            ["not_applied", "not_applied"],
        )
        self.assertIn(self.employee.id, [row["employee_id"] for row in data["rows"]])

    def test_same_minute_events_pair_only_direct_deterministic_neighbours(self):
        first_out = self._pending_event(
            "2026-08-24 13:43:05", "out", "same-minute-out-first",
        )
        middle_in = self._pending_event(
            "2026-08-24 13:43:15", "in", "same-minute-in-middle",
        )
        middle_out = self._pending_event(
            "2026-08-24 13:43:30", "out", "same-minute-out-middle",
        )
        last_in = self._pending_event(
            "2026-08-24 13:43:45", "in", "same-minute-in-last",
        )
        self._reconcile_employee()
        events = first_out | middle_in | middle_out | last_in
        events.invalidate_recordset()
        self.assertFalse(first_out.attendance_id)
        self.assertEqual(middle_in.attendance_id, middle_out.attendance_id)
        self.assertTrue(middle_in.attendance_id)
        self.assertFalse(last_in.attendance_id)

        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-24 00:00:00", "2026-08-25 00:00:00",
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        source_sort_ids = [
            item["sort_id"] for item in row["items"] if item.get("sort_id")
        ]
        self.assertEqual(source_sort_ids, sorted(source_sort_ids))
        self.assertFalse(any(
            connection["from"] == f"event:{first_out.id}"
            or connection["to"] == f"event:{last_in.id}"
            for connection in row["connections"]
        ))

    def test_existing_attendance_endpoints_are_not_stolen_by_an_intermediate_event(self):
        log = self._log()
        self.device._adapter().process_payload(
            log, "ATTLOG", b"",
            "74\t2026-08-24 06:00:00\t255\t1\t0\n"
            "74\t2026-08-24 16:00:00\t255\t15\t0",
        )
        in_event, out_event = log.event_ids.sorted("event_datetime")
        attendance = in_event.attendance_id
        extra_in = self._pending_event(
            "2026-08-24 12:00:00", "in", "between-known-pair",
        )
        self._reconcile_employee()
        (in_event | out_event | extra_in).invalidate_recordset()
        self.assertEqual(in_event.attendance_id, attendance)
        self.assertEqual(out_event.attendance_id, attendance)
        self.assertFalse(extra_in.attendance_id)
        self.assertEqual(extra_in.processing_state, "not_applied")

        data = self.env["mdl.attendance.device.event"].get_conflict_timeline(
            "2026-08-24 00:00:00", "2026-08-25 00:00:00",
        )
        row = next(
            row for row in data["rows"]
            if row["employee_id"] == self.employee.id
        )
        attendance_connection = next(
            connection for connection in row["connections"]
            if connection["id"] == f"attendance:{attendance.id}"
        )
        self.assertEqual(attendance_connection["pair_type"], "attendance")
        attendance_endpoints = {
            f"attendance:{attendance.id}:in",
            f"attendance:{attendance.id}:out",
        }
        self.assertFalse(any(
            connection["id"] != attendance_connection["id"]
            and attendance_endpoints.intersection({
                connection["from"], connection["to"],
            })
            for connection in row["connections"]
        ))
