"""Exercise the saved-event actions through their native ORM/RPC interfaces."""

import uuid

from lxml import etree

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestSavedEventActions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        vals = {"name": "Saved event employee", "company_id": cls.env.company.id}
        if "mdl_wage_type" in cls.env["hr.employee"]._fields:
            vals["mdl_wage_type"] = "mdl_monthly"
        structure_type = cls.env["hr.payroll.structure.type"].search([
            ("wage_type", "=", "monthly"),
        ], limit=1)
        if structure_type:
            vals["structure_type_id"] = structure_type.id
        cls.employee = cls.env["hr.employee"].create(vals)
        cls.device = cls.env["mdl.attendance.device"].create({
            "name": "Saved event clock", "manufacturer": "zkteco",
            "device_identifier": "TEST-SAVED-EVENTS", "company_id": cls.env.company.id,
            "timezone": "UTC", "punch_state_column": 3,
            "punch_in_values": "1", "punch_out_values": "15",
        })
        cls.card = cls.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": cls.device.id, "device_user_id": "saved-event-1",
            "employee_id": cls.employee.id,
        })
        cls.log = cls.env["mdl.attendance.device.log"].create({
            "device_id": cls.device.id,
            "device_identifier": cls.device.device_identifier,
            "request_type": "ATTLOG", "http_method": "POST", "endpoint": "/iclock/cdata",
        })
        cls.Event = cls.env["mdl.attendance.device.event"]
        cls.Attendance = cls.env["hr.attendance"]

    def _event(self, hour, kind):
        return self.Event.create({
            "log_id": self.log.id, "device_id": self.device.id,
            "device_employee_id": self.card.id, "employee_id": self.employee.id,
            "device_user_id": self.card.device_user_id,
            "event_datetime": "2026-08-24 %02d:00:00" % hour,
            "raw_line": "Saved-event source %s %s" % (hour, kind),
            "raw_punch_state": kind, "punch_state": kind,
            "event_fingerprint": "saved-event:%s" % uuid.uuid4().hex,
            "processing_state": "not_applied",
        })

    def _pair(self):
        in_event = self._event(8, "in")
        out_event = self._event(17, "out")
        self.Event._timeline_reconcile_employee_ids([self.employee.id])
        self.assertTrue(in_event.attendance_id)
        self.assertEqual(in_event.attendance_id, out_event.attendance_id)
        return in_event, out_event, in_event.attendance_id

    def _row(self):
        data = self.Event.get_conflict_timeline(
            "2026-08-24 00:00:00", "2026-08-25 00:00:00",
            [("employee_id", "=", self.employee.id)],
        )
        return next(row for row in data["rows"] if row["employee_id"] == self.employee.id)

    def _search_action_filters(self, *filter_names):
        """Use the actual installed action/search chips, not a simplified domain."""
        action = self.env.ref("mdl_zkteco_attendance.action_attendance_conflicts")
        arch = etree.fromstring(action.search_view_id.arch_db.encode())
        domain = safe_eval(action.domain) + [("employee_id", "=", self.employee.id)]
        for name in filter_names:
            nodes = arch.xpath("//filter[@name='%s']" % name)
            self.assertEqual(len(nodes), 1)
            domain += safe_eval(nodes[0].get("domain"))
        return self.Event.get_conflict_timeline(
            "2026-08-24 00:00:00", "2026-08-25 00:00:00", domain,
        )

    def test_visible_chip_does_not_force_conflicts_only(self):
        in_event, out_event, _attendance = self._pair()
        data = self._search_action_filters("visible")
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        self.assertEqual({item["event_id"] for item in row["items"]}, {in_event.id, out_event.id})
        self.assertEqual(self._search_action_filters("visible", "only_conflicts")["rows"], [])

    def test_hidden_chip_shows_saved_and_pending_source_events_without_repair(self):
        in_event, out_event, attendance = self._pair()
        pending = self._event(20, "out")
        self.Event.timeline_hide_items([in_event.id, pending.id])
        before_attendance = attendance.read(["check_in", "check_out", "write_date"])
        before_events = (in_event | out_event | pending).read([
            "processing_state", "attendance_id", "conflict_dismissed", "write_date",
        ])
        data = self._search_action_filters("hidden")
        row = next(row for row in data["rows"] if row["employee_id"] == self.employee.id)
        self.assertEqual({item["event_id"] for item in row["items"]}, {in_event.id, pending.id})
        self.assertTrue(all(item["hidden"] for item in row["items"]))
        self.assertEqual(row["connections"], [])
        conflicts = self._search_action_filters("hidden", "only_conflicts")
        self.assertEqual(
            [item["event_id"] for row in conflicts["rows"] for item in row["items"]],
            [pending.id],
        )
        self.assertEqual(attendance.read(["check_in", "check_out", "write_date"]), before_attendance)
        self.assertEqual((in_event | out_event | pending).read([
            "processing_state", "attendance_id", "conflict_dismissed", "write_date",
        ]), before_events)

    def test_hide_saved_endpoint_retains_attendance_and_raw_source(self):
        in_event, out_event, attendance = self._pair()
        original_source = in_event.read([
            "raw_line", "event_fingerprint", "event_datetime", "punch_state",
            "attendance_id", "processing_state",
        ])
        original_attendance = attendance.read(["employee_id", "check_in", "check_out"])
        in_event.action_hide()
        self.Event._timeline_reconcile_employee_ids([self.employee.id])
        attendance._ensure_attendance_device_events()
        self.assertTrue(in_event.conflict_dismissed)
        self.assertEqual(in_event.read([
            "raw_line", "event_fingerprint", "event_datetime", "punch_state",
            "attendance_id", "processing_state",
        ]), original_source)
        self.assertEqual(attendance.read(["employee_id", "check_in", "check_out"]), original_attendance)
        row = self._row()
        self.assertEqual([item["event_id"] for item in row["items"]], [out_event.id])
        self.assertEqual(row["connections"], [])

    def test_hide_saved_pair_keeps_both_events_and_attendance(self):
        in_event, out_event, attendance = self._pair()
        self.Event.timeline_dismiss_pair([in_event.id, out_event.id])
        self.Event._timeline_reconcile_employee_ids([self.employee.id])
        self.assertTrue(attendance.exists())
        self.assertEqual((in_event | out_event).mapped("attendance_id"), attendance)
        self.assertEqual(len((in_event | out_event).exists()), 2)
        self.assertEqual(self._row()["items"], [])

    def test_legacy_delete_action_is_visibility_only(self):
        in_event, out_event, attendance = self._pair()
        self.Event.timeline_delete_items([], [attendance.id])
        self.assertTrue(attendance.exists())
        self.assertTrue(all((in_event | out_event).mapped("conflict_dismissed")))
        self.assertEqual(len((in_event | out_event).exists()), 2)
        self.assertEqual(self._row()["items"], [])

    def test_hide_native_attendance_only_adds_missing_visibility_endpoints(self):
        attendance = self.Attendance.with_context(skip_attendance_event_sync=True).create({
            "employee_id": self.employee.id,
            "check_in": "2026-08-24 08:00:00", "check_out": "2026-08-24 17:00:00",
        })
        before = attendance.read(["employee_id", "check_in", "check_out", "write_date"])
        self.assertFalse(self.Event.search([("attendance_id", "=", attendance.id)]))
        self.Event.timeline_hide_items([], [attendance.id])
        events = self.Event.search([("attendance_id", "=", attendance.id)])
        self.assertEqual(len(events), 2)
        self.assertTrue(all(events.mapped("conflict_dismissed")))
        self.Event.timeline_hide_items([], [attendance.id])
        self.assertEqual(self.Event.search([("attendance_id", "=", attendance.id)]), events)
        self.assertEqual(attendance.read(["employee_id", "check_in", "check_out", "write_date"]), before)
        self.assertEqual(self._row()["items"], [])

    def test_saved_in_flip_relinks_neighbour_then_can_be_reversed(self):
        earlier_in = self._event(6, "in")
        in_event, out_event, old_attendance = self._pair()
        original_ids = (earlier_in | in_event | out_event).ids
        self.Event.timeline_flip_event(in_event.id)
        self.assertFalse(old_attendance.exists())
        self.assertEqual(in_event.effective_punch_state, "out")
        self.assertEqual(in_event.attendance_id, earlier_in.attendance_id)
        self.assertTrue(in_event.attendance_id)
        self.assertEqual(in_event.attendance_id.check_out, in_event.event_datetime)
        self.assertFalse(out_event.attendance_id)
        self.Event.timeline_flip_event(in_event.id)
        self.assertEqual(in_event.effective_punch_state, "in")
        self.assertEqual(in_event.attendance_id, out_event.attendance_id)
        self.assertTrue(in_event.attendance_id)
        self.assertFalse(earlier_in.attendance_id)
        self.assertEqual(self.Event.browse(original_ids).exists().ids, original_ids)

    def test_saved_out_flip_can_pair_with_later_out(self):
        in_event, out_event, old_attendance = self._pair()
        later_out = self._event(20, "out")
        out_event.action_flip()
        self.assertFalse(old_attendance.exists())
        self.assertEqual(out_event.effective_punch_state, "in")
        self.assertEqual(out_event.attendance_id, later_out.attendance_id)
        self.assertTrue(out_event.attendance_id)
        self.assertFalse(in_event.attendance_id)
        self.assertEqual(out_event.punch_state, "out")

    def test_generated_saved_endpoints_survive_type_correction(self):
        attendance = self.Attendance.create({
            "employee_id": self.employee.id,
            "check_in": "2026-08-24 08:00:00",
            "check_out": "2026-08-24 17:00:00",
        })
        events = self.Event.search([("attendance_id", "=", attendance.id)]).sorted("event_datetime")
        self.assertEqual(len(events), 2)
        self.assertTrue(all(events.mapped("odoo_generated")))
        # This is the field used in the native event form, not a special test API.
        events[-1].write({"effective_punch_state": "in"})
        self.assertEqual(len(events.exists()), 2)
        self.assertFalse(attendance.exists())
        self.assertFalse(any(events.mapped("odoo_generated")))
        self.assertFalse(events.mapped("attendance_id"))
        events[-1].write({"effective_punch_state": "out"})
        self.assertEqual(events[0].attendance_id, events[-1].attendance_id)
        self.assertTrue(events[0].attendance_id)
        self.assertEqual(len(events.exists()), 2)

    def test_saved_endpoint_actions_include_flip_and_hide(self):
        self._pair()
        for item in self._row()["items"]:
            self.assertEqual(
                [action["key"] for action in item["actions"]],
                ["open_attendance", "flip_event", "dismiss_event"],
            )

    def test_manual_event_double_submit_reuses_existing_punch(self):
        event = self._event(8, "in")
        wizard = self.env["mdl.attendance.conflict.event.wizard"].create({
            "employee_id": self.employee.id, "device_id": self.device.id,
            "punch_state": "in", "event_datetime": event.event_datetime,
        })
        event_count = self.Event.search_count([("employee_id", "=", self.employee.id)])
        wizard.action_create_event()
        wizard.action_create_event()
        self.assertEqual(
            self.Event.search_count([("employee_id", "=", self.employee.id)]), event_count,
        )
        self.assertTrue(event.exists())

    def test_opening_timeline_does_not_reconcile_or_create_attendance(self):
        in_event = self._event(8, "in")
        out_event = self._event(17, "out")
        before = (in_event | out_event).read(["write_date", "processing_state", "attendance_id"])
        row = self._row()
        self.assertEqual(len(row["items"]), 2)
        self.assertFalse(self.Attendance.search([("employee_id", "=", self.employee.id)]))
        self.assertEqual(
            (in_event | out_event).read(["write_date", "processing_state", "attendance_id"]), before,
        )

    def test_validated_native_work_entry_blocks_flip_but_not_hide(self):
        in_event, out_event, attendance = self._pair()
        Entry = self.env["hr.work.entry"]
        if "attendance_id" not in Entry._fields:
            self.skipTest("Native attendance work-entry integration is not installed")
        entry = Entry.create({
            "name": "Validated saved-event work",
            "employee_id": self.employee.id,
            "date": fields.Date.to_date("2026-08-24"),
            "duration": 9,
            "work_entry_type_id": self.env.ref("hr_work_entry.work_entry_type_attendance").id,
            "attendance_id": attendance.id,
            "state": "validated",
        })
        with self.assertRaises(UserError), self.cr.savepoint():
            in_event.action_flip()
        self.assertEqual(in_event.effective_punch_state, "in")
        self.assertEqual(in_event.attendance_id, attendance)
        self.assertEqual(entry.state, "validated")
        in_event.action_hide()
        self.assertTrue(in_event.conflict_dismissed)
        self.assertEqual(entry.attendance_id, attendance)
        self.assertEqual(out_event.attendance_id, attendance)

    def test_validated_normalized_work_entry_blocks_flip(self):
        in_event, _out_event, attendance = self._pair()
        Entry = self.env["hr.work.entry"]
        if "mdl_source_attendance_ids" not in Entry._fields:
            self.skipTest("Israeli normalized work-entry integration is not installed")
        entry = Entry.create({
            "name": "Normalized validated saved-event work",
            "employee_id": self.employee.id,
            "date": fields.Date.to_date("2026-08-24"), "duration": 9,
            "work_entry_type_id": self.env.ref("hr_work_entry.work_entry_type_attendance").id,
            "mdl_source_attendance_ids": [(6, 0, attendance.ids)],
            "state": "validated",
        })
        with self.assertRaises(UserError), self.cr.savepoint():
            in_event.action_flip()
        self.assertEqual(entry.mdl_source_attendance_ids, attendance)
        self.assertEqual(in_event.attendance_id, attendance)
        self.assertEqual(in_event.effective_punch_state, "in")

    def test_finalized_payslip_period_blocks_correction_but_allows_hide(self):
        in_event, _out_event, attendance = self._pair()
        structure = self.env["hr.payroll.structure"].search([
            ("type_id", "=", self.employee.structure_type_id.id),
        ], limit=1)
        if not structure:
            structure = self.env["hr.payroll.structure"].create({
                "name": "Saved event payroll structure",
                "type_id": self.employee.structure_type_id.id,
            })
        slip = self.env["hr.payslip"].create({
            "name": "Finalized saved-event payroll period",
            "employee_id": self.employee.id, "struct_id": structure.id,
            "date_from": "2026-08-01", "date_to": "2026-08-31",
            "state": "validated",
        })
        # Prove the payslip guard itself protects the period, independently
        # from the separate validated-work-entry protection tested above.
        self.assertFalse(self.env["hr.work.entry"].search([
            ("employee_id", "=", self.employee.id),
            ("date", "=", fields.Date.to_date("2026-08-24")),
            ("state", "=", "validated"),
        ]))
        with self.assertRaises(UserError), self.cr.savepoint():
            in_event.action_flip()
        self.assertEqual(in_event.effective_punch_state, "in")
        self.assertEqual(in_event.attendance_id, attendance)
        self.assertEqual(slip.state, "validated")
        in_event.action_hide()
        self.assertTrue(in_event.conflict_dismissed)
        self.assertTrue(attendance.exists())
        self.assertEqual(slip.state, "validated")
