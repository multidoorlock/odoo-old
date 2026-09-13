"""Clock payload replay and timestamp regressions, through the real adapter."""

import hashlib
from unittest.mock import patch

from psycopg2.errors import SerializationFailure

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestClockIngestionRegressions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.device = cls.env["mdl.attendance.device"].create({
            "name": "Clock ingestion regression",
            "manufacturer": "zkteco",
            "device_identifier": "INGESTION-REGRESSION",
            "company_id": cls.env.company.id,
            "timezone": "Asia/Jerusalem",
            "punch_state_column": 3,
            "punch_in_values": "1",
            "punch_out_values": "15",
            "attendance_cooldown_minutes": 0,
        })
        employee_values = {
            "name": "Clock replay regression employee",
            "company_id": cls.env.company.id,
        }
        Employee = cls.env["hr.employee"]
        if "mdl_wage_type" in Employee._fields:
            employee_values["mdl_wage_type"] = "mdl_monthly"
        if "structure_type_id" in Employee._fields:
            structure = cls.env["hr.payroll.structure.type"].search([
                ("wage_type", "=", "monthly"),
            ], limit=1)
            if structure:
                employee_values["structure_type_id"] = structure.id
        cls.employee = Employee.create(employee_values)
        cls.card = cls.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": cls.device.id,
            "device_user_id": "701",
            "device_name": cls.employee.name,
            "employee_id": cls.employee.id,
        })

    def _ingest(self, payload):
        log = self.env["mdl.attendance.device.log"].create({
            "device_id": self.device.id,
            "device_identifier": self.device.device_identifier,
            "request_type": "ATTLOG",
            "http_method": "POST",
            "endpoint": "/iclock/cdata",
            "body": payload,
        })
        self.device._adapter().process_payload(
            log, "ATTLOG", payload.encode(), payload,
        )
        self.assertEqual(log.body, payload, "Raw device evidence must stay intact")
        return log

    def test_repeated_unmatched_exit_is_one_visible_conflict(self):
        payload = "701\t2026-09-03 06:23:03\t255\t15\t0"
        original = self._ingest(payload).event_ids
        self.assertEqual(original.processing_state, "not_applied")
        replay = self._ingest(payload).event_ids
        self.assertEqual(replay.processing_state, "ignored")
        self.assertEqual(replay.event_fingerprint, original.event_fingerprint)
        self.assertFalse(replay.attendance_id)
        original.action_process()
        self.assertEqual(original.processing_state, "not_applied")
        self.assertEqual(replay.processing_state, "ignored")
        self.assertEqual(self.env["mdl.attendance.device.event"].search_count([
            ("event_fingerprint", "=", original.event_fingerprint),
            ("processing_state", "!=", "ignored"),
        ]), 1)

    def test_hidden_unmatched_exit_is_not_resurrected_by_replay(self):
        payload = "701\t2026-09-03 06:23:03\t255\t15\t0"
        original = self._ingest(payload).event_ids
        original.action_dismiss_conflict()
        self.assertTrue(original.conflict_dismissed)
        replay = self._ingest(payload).event_ids
        self.assertEqual(replay.processing_state, "ignored")
        self.assertTrue(original.conflict_dismissed)
        self.assertFalse(replay.attendance_id)

    def test_hidden_exit_cannot_close_attendance_on_explicit_reprocess(self):
        hidden = self._ingest("701\t2026-09-03 17:00:00\t255\t15\t0").event_ids
        hidden.action_hide()
        incoming = self._ingest("701\t2026-09-03 08:00:00\t255\t1\t0").event_ids
        attendance = incoming.attendance_id
        self.assertTrue(attendance)
        self.assertFalse(attendance.check_out)
        hidden.action_process()
        hidden.invalidate_recordset()
        attendance.invalidate_recordset()
        self.assertTrue(hidden.conflict_dismissed)
        self.assertFalse(hidden.attendance_id)
        self.assertFalse(attendance.check_out)

    def test_hidden_waiting_entry_stays_excluded_after_card_link_and_retry(self):
        payload = "702\t2026-09-03 08:00:00\t255\t1\t0"
        hidden = self._ingest(payload).event_ids
        self.assertEqual(hidden.processing_state, "waiting_employee_link")
        hidden.action_hide()
        self.card.write({"employee_id": False})
        hidden.device_employee_id.write({"employee_id": self.employee.id})
        hidden.action_process()
        replay = self._ingest(payload).event_ids
        self.assertTrue(hidden.conflict_dismissed)
        self.assertFalse(hidden.attendance_id | replay.attendance_id)
        self.assertEqual(replay.processing_state, "ignored")
        self.assertFalse(self.env["hr.attendance"].search([
            ("employee_id", "=", self.employee.id),
        ]))

    def test_hidden_punch_is_not_a_cooldown_source_for_a_new_punch(self):
        self.device.attendance_cooldown_minutes = 5
        hidden = self._ingest("701\t2026-09-03 17:00:00\t255\t15\t0").event_ids
        hidden.action_hide()
        later = self._ingest("701\t2026-09-03 17:01:00\t255\t15\t0").event_ids
        self.assertEqual(later.processing_state, "not_applied")
        self.assertFalse(later.conflict_dismissed)
        self.assertNotEqual(hidden.event_fingerprint, later.event_fingerprint)

    def test_hidden_saved_entry_stays_excluded_when_original_payload_replays(self):
        incoming = "701\t2026-09-03 08:00:00\t255\t1\t0"
        outgoing = "701\t2026-09-03 17:00:00\t255\t15\t0"
        originals = self._ingest(incoming + "\n" + outgoing).event_ids
        saved = originals.attendance_id
        self.assertEqual(len(saved), 1)
        hidden = originals.filtered(lambda event: event.punch_state == "in")
        hidden.action_hide()
        self.assertFalse(saved.exists())
        replays = self._ingest(incoming + "\n" + outgoing).event_ids
        originals.action_process()
        self.assertEqual(set(replays.mapped("processing_state")), {"ignored"})
        self.assertFalse((originals | replays).mapped("attendance_id"))
        self.assertTrue(hidden.conflict_dismissed)

    def _pending_interval(self, user=None):
        log = self.env["mdl.attendance.device.log"].create({
            "device_id": self.device.id, "request_type": "ATTLOG",
        })
        adapter = self.device._adapter()
        incoming = adapter._create_attlog_event(
            log, "701\t2026-09-03 08:00:00\t255\t1\t0",
        )
        outgoing = adapter._create_attlog_event(
            log, "701\t2026-09-03 17:00:00\t255\t15\t0",
        )
        events = incoming | outgoing
        events.write({"processing_state": "not_applied"})
        Wizard = self.env["mdl.attendance.pending.wizard"]
        if user:
            Wizard = Wizard.with_user(user)
        wizard = Wizard.create({"device_employee_id": self.card.id})
        line = Wizard.env["mdl.attendance.pending.wizard.line"].create({
            "wizard_id": wizard.id,
            "check_in_event_id": incoming.id,
            "check_out_event_id": outgoing.id,
        })
        return events, line

    def test_pending_popup_hide_excludes_a_pair_that_was_saved_after_opening(self):
        events, line = self._pending_interval()
        events.action_process()
        saved = events.attendance_id
        self.assertEqual(len(saved), 1)
        result = line.action_dismiss()
        events.invalidate_recordset()
        self.assertTrue(all(events.mapped("conflict_dismissed")))
        self.assertFalse(saved.exists())
        self.assertFalse(events.attendance_id)
        self.assertEqual(result, {"type": "ir.actions.act_window_close"})

    def test_pending_popup_cannot_apply_an_interval_hidden_after_opening(self):
        events, line = self._pending_interval()
        events.action_hide()
        with self.assertRaisesRegex(UserError, "האירועים השתנו או הוסתרו"):
            line.action_apply()
        self.assertTrue(all(events.mapped("conflict_dismissed")))
        self.assertFalse(events.attendance_id)

    def test_card_operator_can_hide_only_their_popup_card_without_event_edit_access(self):
        operator = new_test_user(
            self.env, login="clock_exclusion_operator",
            groups="base.group_user,mdl_zkteco_attendance.group_attendance_device_user",
        )
        events, line = self._pending_interval(user=operator)
        self.assertFalse(operator.has_group(
            "mdl_zkteco_attendance.group_attendance_device_manager",
        ))
        with self.assertRaises(AccessError):
            events.with_user(operator).check_access("write")
        line.action_dismiss()
        events.invalidate_recordset()
        self.assertTrue(all(events.mapped("conflict_dismissed")))
        self.assertFalse(events.attendance_id)

    def test_pending_popup_rejects_an_event_injected_from_a_different_card(self):
        events, line = self._pending_interval()
        foreign = self._ingest("702\t2026-09-03 17:00:00\t255\t15\t0").event_ids
        line.check_out_event_id = foreign.id
        with self.assertRaisesRegex(UserError, "רק אירועים של הכרטיס"):
            line.action_dismiss()
        self.assertFalse(any((events | foreign).mapped("conflict_dismissed")))

    def test_pending_candidates_use_exit_corrected_to_entry(self):
        event = self._ingest("701\t2026-09-03 08:00:00\t255\t15\t0").event_ids
        event.action_flip()
        self.assertEqual(event.punch_state, "out")
        self.assertEqual(event.manual_punch_state, "in")
        self.assertFalse(event.attendance_id)
        candidates = self.card._get_valid_attendance_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], event)
        self.assertFalse(candidates[0][1])

    def test_pending_candidates_do_not_offer_an_entry_corrected_to_exit(self):
        event = self._ingest("701\t2026-09-03 08:00:00\t255\t1\t0").event_ids
        event.action_flip()
        self.assertEqual(event.punch_state, "in")
        self.assertEqual(event.manual_punch_state, "out")
        self.assertFalse(event.attendance_id)
        self.assertEqual(self.card._get_valid_attendance_candidates(), [])

    def test_pending_candidates_include_an_unknown_punch_corrected_to_entry(self):
        event = self._ingest("701\t2026-09-03 08:00:00\t255\t99\t0").event_ids
        event.write({"manual_punch_state": "in"})
        self.assertEqual(event.punch_state, "unknown")
        self.assertEqual(event.manual_punch_state, "in")
        candidates = self.card._get_valid_attendance_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], event)
        self.assertFalse(candidates[0][1])

    def test_repeated_waiting_card_keeps_original_available_for_linking(self):
        payload = "702\t2026-09-03 08:00:00\t255\t1\t0"
        original = self._ingest(payload).event_ids
        self.assertEqual(original.processing_state, "waiting_employee_link")
        replay = self._ingest(payload).event_ids
        self.assertEqual(replay.processing_state, "ignored")
        # This employee already has another card; unlink that card first so
        # the normal one-active-card-per-device constraint remains respected.
        self.card.write({"employee_id": False})
        original.device_employee_id.write({"employee_id": self.employee.id})
        original.action_process()
        self.assertEqual(original.processing_state, "processed")
        self.assertTrue(original.attendance_id)
        self.assertEqual(replay.processing_state, "ignored")

    def test_unknown_punch_replay_stays_one_unmapped_event(self):
        payload = "701\t2026-09-03 08:00:00\t255\t99\t0"
        original = self._ingest(payload).event_ids
        self.assertEqual(original.punch_state, "unknown")
        self.assertEqual(original.processing_state, "not_applied")
        replay = self._ingest(payload).event_ids
        self.assertEqual(replay.processing_state, "ignored")
        self.assertFalse(original.attendance_id | replay.attendance_id)

    def test_repeated_line_in_same_payload_is_ignored(self):
        line = "701\t2026-09-03 06:23:03\t255\t15\t0"
        log = self._ingest("\n".join([line] * 4))
        self.assertEqual(len(log.event_ids), 4)
        self.assertEqual(len(log.event_ids.filtered(
            lambda event: event.processing_state == "not_applied"
        )), 1)
        self.assertEqual(len(log.event_ids.filtered(
            lambda event: event.processing_state == "ignored"
        )), 3)

    def test_same_minute_different_seconds_are_not_retransmissions(self):
        log = self._ingest(
            "701\t2026-09-03 06:23:03\t255\t15\t0\n"
            "701\t2026-09-03 06:23:18\t255\t15\t0"
        )
        self.assertEqual(len(set(log.event_ids.mapped("event_fingerprint"))), 2)
        self.assertEqual(log.event_ids.mapped("processing_state"),
                         ["not_applied", "not_applied"])

    def test_same_second_opposite_punch_types_are_not_retransmissions(self):
        log = self._ingest(
            "701\t2026-09-03 08:00:00\t255\t1\t0\n"
            "701\t2026-09-03 08:00:00\t255\t15\t0"
        )
        self.assertEqual(len(set(log.event_ids.mapped("event_fingerprint"))), 2)
        self.assertFalse(log.event_ids.filtered(
            lambda event: event.processing_state == "ignored"
        ))

    def test_midnight_is_only_used_when_present_in_raw_punch(self):
        log = self._ingest(
            "701\t2026-09-03 16:21:45\t255\t1\t0\n"
            "701\t2026-09-04 06:23:03\t255\t15\t0"
        )
        events = log.event_ids.sorted("event_datetime")
        self.assertEqual(events.mapped("event_datetime"), [
            fields.Datetime.to_datetime("2026-09-03 13:21:45"),
            fields.Datetime.to_datetime("2026-09-04 03:23:03"),
        ])
        self.assertEqual(events[0].attendance_id, events[1].attendance_id)
        self.assertEqual(len(self.env["mdl.attendance.device.event"].search([
            ("employee_id", "=", self.employee.id),
            ("attendance_id", "=", events[0].attendance_id.id),
        ])), 2, "A cross-midnight shift must not invent midnight endpoints")

    def test_genuine_midnight_punch_is_preserved_with_timezone(self):
        log = self._ingest("701\t2026-09-03 00:00:00\t255\t15\t0")
        self.assertEqual(log.event_ids.event_datetime,
                         fields.Datetime.to_datetime("2026-09-02 21:00:00"))
        self.assertEqual(log.event_ids.punch_state, "out")

    def test_mixed_success_and_duplicate_has_successful_log_status(self):
        first_in = "701\t2026-09-03 08:00:00\t255\t1\t0"
        self._ingest(first_in)
        log = self._ingest(
            first_in + "\n701\t2026-09-03 17:00:00\t255\t15\t0"
        )
        self.assertEqual(set(log.event_ids.mapped("processing_state")),
                         {"processed", "ignored"})
        self.assertEqual(log.processing_state, "processed")

    def test_date_only_payload_is_rejected_instead_of_defaulting_to_midnight(self):
        log = self._ingest("701\t2026-09-03\t255\t15\t0")
        self.assertEqual(log.event_ids.processing_state, "error")
        self.assertFalse(log.event_ids.event_datetime)
        self.assertFalse(log.event_ids.attendance_id)

    def test_bad_line_does_not_discard_valid_sibling_punches(self):
        log = self._ingest(
            "701\t2026-09-03 08:00:00\t255\t1\t0\n"
            "invalid-clock-row\n"
            "701\t2026-09-03 17:00:00\t255\t15\t0"
        )
        self.assertEqual(len(log.event_ids), 3)
        valid = log.event_ids.filtered(lambda event: event.event_datetime)
        self.assertEqual(valid.mapped("processing_state"), ["processed", "processed"])
        self.assertEqual(len(valid.attendance_id), 1)
        self.assertEqual(log.processing_state, "error")

    @mute_logger("odoo.sql_db")
    def test_database_error_on_one_line_rolls_back_only_that_line(self):
        adapter_type = type(self.device._adapter())
        original_create = adapter_type._create_attlog_event

        def create_event(adapter, log, line):
            if line == "invalid-clock-row":
                # Reproduce a PostgreSQL exception from an ORM constraint.
                # Catching this without a savepoint poisons the whole batch.
                adapter.env.cr.execute("SELECT 1 / 0")
            return original_create(adapter, log, line)

        with patch.object(adapter_type, "_create_attlog_event", create_event):
            log = self._ingest(
                "701\t2026-09-03 08:00:00\t255\t1\t0\n"
                "invalid-clock-row\n"
                "701\t2026-09-03 17:00:00\t255\t15\t0"
            )
        self.assertEqual(len(log.event_ids), 3)
        self.assertEqual(len(log.event_ids.filtered(
            lambda event: event.processing_state == "processed"
        )), 2)
        failed = log.event_ids.filtered(lambda event: event.processing_state == "error")
        self.assertEqual(failed.raw_line, "invalid-clock-row")
        self.assertFalse(failed.event_datetime)

    def test_concurrent_update_requests_retry_instead_of_marking_bad_punch(self):
        adapter_type = type(self.device._adapter())
        with patch.object(adapter_type, "_create_attlog_event",
                          side_effect=SerializationFailure("Concurrent clock request")):
            with self.assertRaises(SerializationFailure):
                self._ingest("701\t2026-09-03 08:00:00\t255\t1\t0")

    def test_israel_summer_and_winter_keep_local_time_without_day_truncation(self):
        adapter = self.device._adapter()
        self.assertEqual(adapter._utc_datetime("2026-09-03 06:23:03"),
                         fields.Datetime.to_datetime("2026-09-03 03:23:03"))
        self.assertEqual(adapter._utc_datetime("2026-12-03 06:23:03"),
                         fields.Datetime.to_datetime("2026-12-03 04:23:03"))

    def test_hidden_pending_punch_is_not_proposed_again_by_card_wizard(self):
        log = self.env["mdl.attendance.device.log"].create({
            "device_id": self.device.id,
            "request_type": "MANUAL",
        })
        event = self.env["mdl.attendance.device.event"].create({
            "log_id": log.id,
            "device_id": self.device.id,
            "device_employee_id": self.card.id,
            "employee_id": self.employee.id,
            "device_user_id": self.card.device_user_id,
            "event_datetime": "2026-09-03 06:00:00",
            "punch_state": "in",
            "event_fingerprint": "hidden-pending-card-regression",
            "processing_state": "not_applied",
        })
        self.assertEqual(len(self.card._get_valid_attendance_candidates()), 1)
        event.action_dismiss_conflict()
        self.assertTrue(event.conflict_dismissed)
        self.assertEqual(self.card._get_valid_attendance_candidates(), [])

    def _legacy_wrong_company_card(self, active=True):
        other_company = self.env["res.company"].create({"name": "Legacy clock binding company"})
        values = {"name": "Legacy other-company employee", "company_id": other_company.id}
        if "mdl_wage_type" in self.env["hr.employee"]._fields:
            values["mdl_wage_type"] = "mdl_monthly"
        if "structure_type_id" in self.env["hr.employee"]._fields and self.employee.structure_type_id:
            values["structure_type_id"] = self.employee.structure_type_id.id
        other_employee = self.env["hr.employee"].with_company(other_company).create(values)
        card = self.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": self.device.id, "device_user_id": "703",
            "device_name": "Legacy invalid binding", "active": active,
        })
        # Reproduce records that predate the company constraint.  Native ORM
        # creation correctly rejects this mapping today.  Test-only SQL is
        # contained by TransactionCase and never used as a production repair.
        card.flush_recordset()
        self.env.cr.execute(
            "UPDATE mdl_attendance_device_employee SET employee_id = %s WHERE id = %s",
            (other_employee.id, card.id),
        )
        card.invalidate_recordset(["employee_id"])
        return card, other_employee

    def test_invalid_legacy_binding_preserves_parsed_punch_and_valid_siblings(self):
        card, other_employee = self._legacy_wrong_company_card()
        card_before = card.read(["employee_id", "device_id", "active", "write_date", "write_uid"])
        invalid_line = "703\t2026-09-03 08:00:05\t255\t1\t0"
        log = self._ingest(
            "701\t2026-09-03 08:00:00\t255\t1\t0\n" + invalid_line
            + "\n701\t2026-09-03 17:00:00\t255\t15\t0"
        )
        invalid = log.event_ids.filtered(lambda event: event.device_user_id == "703")
        valid = log.event_ids - invalid
        self.assertEqual(len(invalid), 1)
        self.assertEqual(invalid.processing_state, "waiting_employee_link")
        self.assertIn("מאותה חברה", invalid.processing_message)
        self.assertEqual(invalid.device_employee_id, card)
        self.assertFalse(invalid.employee_id)
        self.assertFalse(invalid.attendance_id)
        self.assertFalse(self.env["mdl.attendance.device.event"]._timeline_event_employee(invalid))
        self.assertEqual(invalid.raw_line, invalid_line)
        self.assertEqual(invalid.raw_punch_state, "1")
        self.assertEqual(invalid.punch_state, "in")
        self.assertEqual(invalid.event_datetime,
                         fields.Datetime.to_datetime("2026-09-03 05:00:05"))
        expected_hash = hashlib.sha256(
            f"{self.device.id}|703|2026-09-03T05:00:05|1".encode()
        ).hexdigest()
        self.assertEqual(invalid.event_fingerprint, expected_hash)
        self.assertEqual(set(valid.mapped("processing_state")), {"processed"})
        self.assertEqual(len(valid.attendance_id), 1)
        self.assertEqual(valid.employee_id, self.employee)
        self.assertEqual(log.processing_state, "waiting_employee_link")
        self.assertIn("0 parse error(s)", log.processing_message)
        self.assertEqual(card.read(["employee_id", "device_id", "active", "write_date", "write_uid"]),
                         card_before)
        self.assertFalse(self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", other_employee.id),
        ]))

    def test_invalid_legacy_binding_is_not_reactivated_or_reassigned(self):
        card, other_employee = self._legacy_wrong_company_card(active=False)
        log = self._ingest("703\t2026-09-03 08:00:05\t255\t1\t0")
        event = log.event_ids
        self.assertEqual(event.processing_state, "waiting_employee_link")
        self.assertEqual(event.device_employee_id, card)
        self.assertFalse(event.employee_id)
        self.assertTrue(event.event_datetime)
        self.assertFalse(card.active)
        self.assertEqual(card.employee_id, other_employee)

    def test_processor_rechecks_legacy_company_binding_before_assignment(self):
        card, other_employee = self._legacy_wrong_company_card()
        log = self.env["mdl.attendance.device.log"].create({
            "device_id": self.device.id, "request_type": "ATTLOG",
        })
        event = self.device._adapter()._create_attlog_event(
            log, "703\t2026-09-03 08:00:05\t255\t1\t0",
        )
        self.assertEqual(event.processing_state, "waiting_employee_link")
        event.action_process()
        self.assertEqual(event.processing_state, "waiting_employee_link")
        self.assertFalse(event.employee_id)
        self.assertFalse(event.attendance_id)
        self.assertEqual(card.employee_id, other_employee)
        self.assertTrue(event.event_datetime)

    def test_invalid_legacy_binding_replay_is_deduplicated(self):
        card, other_employee = self._legacy_wrong_company_card()
        payload = "703\t2026-09-03 08:00:05\t255\t1\t0"
        original = self._ingest(payload).event_ids
        replay = self._ingest(payload).event_ids
        self.assertEqual(original.processing_state, "waiting_employee_link")
        self.assertEqual(replay.processing_state, "ignored")
        self.assertEqual(original.event_fingerprint, replay.event_fingerprint)
        self.assertFalse(original.employee_id | replay.employee_id)
        self.assertEqual(card.employee_id, other_employee)
