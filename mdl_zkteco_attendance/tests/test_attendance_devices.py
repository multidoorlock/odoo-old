from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestAttendanceDevices(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.device = cls.env["mdl.attendance.device"].create({
            "name": "Test clock", "manufacturer": "zkteco",
            "device_identifier": "TEST-SN", "company_id": cls.env.company.id,
            "timezone": "UTC", "punch_state_column": 3,
            "punch_in_values": "1", "punch_out_values": "15",
        })
        cls.employee = cls.env["hr.employee"].create({"name": "Clock Employee", "company_id": cls.env.company.id})
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

    def test_new_card_copies_employee_name_and_profile_photo(self):
        self.employee.image_1920 = (
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            b"+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )

        draft = self.env["mdl.attendance.device.employee"].new({
            "device_id": self.device.id,
        })
        draft.employee_id = self.employee
        draft._onchange_employee_id_set_card_identity()
        self.assertEqual(draft.device_name, self.employee.name)
        self.assertEqual(draft.profile_photo, self.employee.image_1920)

        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.device.id,
            "employee_id": self.employee.id,
        })
        self.assertEqual(card.device_name, self.employee.name)
        self.assertEqual(card.profile_photo, self.employee.image_1920)

    def test_device_language_syncs_employee_translation_to_card(self):
        self.assertFalse(self.env["resource.resource"]._fields["name"].translate)
        self.assertTrue(self.env["hr.employee"]._fields["name"].translate)
        self.assertFalse(self.env["mdl.attendance.device.employee"]._fields["device_name"].translate)

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
        self.device.write({"device_language": language.code})
        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.device.id,
            "employee_id": self.employee.id,
            "device_name": "This value must be overwritten",
        })

        command = self.device._adapter().build_command("update_name", card)
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

        created_employee = self.env["hr.employee"].create({
            "name": "Created through translated name field",
            "company_id": self.env.company.id,
        })
        self.assertEqual(created_employee.name, "Created through translated name field")

    def test_inactive_clock_language_falls_back_to_current_odoo_language(self):
        language_code = "ar_001" if self.env.lang != "ar_001" else "he_IL"
        language = self.env["res.lang"].with_context(active_test=False).search([
            ("code", "=", language_code),
        ], limit=1)
        if language and language.active:
            language.active = False

        self.device.device_language = language_code
        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.device.id,
            "employee_id": self.employee.id,
        })
        self.assertEqual(card.device_name, self.employee.name)

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
            ["open_attendance", "flip_event"],
        )
        self.assertEqual(
            attendance_items["in"]["actions"][1]["label"],
            "הפוך ליציאה",
        )
        self.assertEqual(
            [action["key"] for action in attendance_items["out"]["actions"]],
            ["open_attendance", "flip_event"],
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
        self.assertEqual(action["tag"], "reload")
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
            [action["key"] for action in item["actions"]] == ["open_attendance"]
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
        other_employee = self.env["hr.employee"].create({
            "name": "Edited Timeline Employee", "company_id": self.env.company.id,
        })
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
        )
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        open_item = next(item for item in row["items"] if item["id"] == f"attendance:{open_attendance.id}:in")
        self.assertEqual(open_item["state"], "1.5")

    def test_conflict_timeline_overdue_open_attendance_stays_green(self):
        now = fields.Datetime.now()
        open_attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": now - timedelta(days=3),
        })
        conflict = self._pending_event(now - timedelta(minutes=1), "in", "overdue-open-context")
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
        self.assertEqual(open_item["state"], "1.5")
        self.assertFalse(any(item.get("placeholder") for item in row["items"]))
        self.assertFalse(any(
            connection["id"] == f"attendance:{open_attendance.id}"
            for connection in row["connections"]
        ))
        self.assertEqual(
            [action["key"] for action in open_item["actions"]],
            ["open_attendance"],
        )

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
        self.assertEqual(language_push.raw_command, "SET OPTION Language=69")
        self.assertEqual(cooldown_push.raw_command, "SET OPTION ReCheckMin=7")
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
            "request_device_options", "INFO",
        )
        adapter = self.device._adapter()
        adapter.process_command_response(
            options_query, "INFO\nOPTIONS\nLanguage=66\nReCheckMin=4",
        )
        self.device.invalidate_recordset()
        self.assertEqual(self.device.device_language, "ar_001")
        self.assertEqual(self.device.attendance_cooldown_minutes, 4)
        self.assertFalse(Command.search_count([
            ("device_id", "=", self.device.id),
            ("command_type", "in", ["update_device_language", "update_device_cooldown"]),
            ("state", "=", "queued"),
        ]))

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

    def test_conflict_view_reconciles_a_stale_valid_pair_automatically(self):
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
        self.assertEqual(check_in.attendance_id, check_out.attendance_id)
        self.assertTrue(check_in.attendance_id)
        self.assertEqual(
            (check_in | check_out).mapped("processing_state"),
            ["processed", "processed"],
        )
        self.assertNotIn(self.employee.id, [row["employee_id"] for row in data["rows"]])

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
