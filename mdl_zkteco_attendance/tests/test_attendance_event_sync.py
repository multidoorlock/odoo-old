"""Source provenance and visibility tests for saved attendance endpoints."""

from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceEventSync(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.device = cls.env["mdl.attendance.device"].create({
            "name": "Attendance source regression",
            "manufacturer": "zkteco",
            "device_identifier": "ATTENDANCE-SOURCE-REGRESSION",
            "company_id": cls.env.company.id,
            "timezone": "Asia/Jerusalem",
            "punch_state_column": 3,
            "punch_in_values": "1",
            "punch_out_values": "15",
            "attendance_cooldown_minutes": 0,
        })
        employee_values = {
            "name": "Attendance source regression employee",
            "company_id": cls.env.company.id,
        }
        if "mdl_wage_type" in cls.env["hr.employee"]._fields:
            employee_values["mdl_wage_type"] = "mdl_monthly"
        if "structure_type_id" in cls.env["hr.employee"]._fields:
            structure = cls.env["hr.payroll.structure.type"].search([
                ("wage_type", "=", "monthly"),
            ], limit=1)
            if structure:
                employee_values["structure_type_id"] = structure.id
        cls.employee = cls.env["hr.employee"].create(employee_values)
        cls.card = cls.env["mdl.attendance.device.employee"].with_context(
            attendance_device_discovery=True,
        ).create({
            "device_id": cls.device.id,
            "device_user_id": "801",
            "device_name": cls.employee.name,
            "employee_id": cls.employee.id,
        })

    def _events(self, attendance):
        return self.env["mdl.attendance.device.event"].search([
            ("attendance_id", "=", attendance.id),
        ]).sorted("event_datetime")

    def _odoo_logs(self):
        return self.env["mdl.attendance.device.log"].search([
            ("device_id", "=", self.device.id),
            ("request_type", "=", "ODOO"),
        ])

    def _manual_attendance(self, **overrides):
        return self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": "2026-09-03 05:00:00",
            "check_out": "2026-09-03 14:00:00",
            **overrides,
        })

    def _raw_attendance(self):
        body = (
            "801\t2026-09-03 08:00:00\t255\t1\t0\n"
            "801\t2026-09-03 17:00:00\t255\t15\t0"
        )
        log = self.env["mdl.attendance.device.log"].create({
            "device_id": self.device.id,
            "request_type": "ATTLOG",
            "body": body,
        })
        self.device._adapter().process_payload(log, "ATTLOG", body.encode(), body)
        self.assertEqual(len(log.event_ids.attendance_id), 1)
        return log, log.event_ids.attendance_id

    def test_technical_absence_creates_no_endpoint_events_or_logs(self):
        logs_before = self._odoo_logs()
        attendance = self._manual_attendance(
            check_in="2026-09-02 21:00:00",
            check_out="2026-09-02 21:00:01",
            in_mode="technical",
            out_mode="technical",
        )
        self.assertTrue(attendance)
        self.assertFalse(attendance._is_attendance_event_source())
        self.assertFalse(self._events(attendance))
        self.assertEqual(self._odoo_logs(), logs_before)
        attendance._ensure_attendance_device_events()
        attendance.write({"check_out": "2026-09-02 21:00:02"})
        self.assertFalse(self._events(attendance))
        self.assertEqual(self._odoo_logs(), logs_before)

    def test_genuine_local_midnight_attendance_keeps_real_endpoints(self):
        attendance = self._manual_attendance(
            check_in="2026-09-02 21:00:00",
            check_out="2026-09-03 03:00:00",
            in_mode="manual",
            out_mode="manual",
        )
        events = self._events(attendance)
        self.assertEqual(len(events), 2)
        self.assertTrue(attendance._is_attendance_event_source())
        self.assertEqual(events.mapped("punch_state"), ["in", "out"])
        self.assertEqual(events.mapped("event_datetime"), [
            fields.Datetime.to_datetime("2026-09-02 21:00:00"),
            fields.Datetime.to_datetime("2026-09-03 03:00:00"),
        ])
        self.assertTrue(all(events.mapped("odoo_generated")))

    def test_endpoint_sync_keeps_hidden_saved_manual_event_hidden(self):
        attendance = self._manual_attendance()
        original_events = self._events(attendance)
        original_events[0].action_hide()
        self.assertTrue(original_events[0].conflict_dismissed)
        attendance.write({"check_out": attendance.check_out + timedelta(minutes=15)})
        attendance._ensure_attendance_device_events()
        self.assertEqual(self._events(attendance), original_events)
        self.assertTrue(original_events[0].conflict_dismissed)
        self.assertEqual(original_events[0].attendance_id, attendance)
        self.assertEqual(original_events[1].event_datetime, attendance.check_out)

    def test_endpoint_sync_keeps_hidden_raw_evidence_and_saved_attendance(self):
        log, attendance = self._raw_attendance()
        original_events = log.event_ids.sorted("event_datetime")
        original_raw_lines = original_events.mapped("raw_line")
        original_events[-1].action_hide()
        attendance.write({"check_out": attendance.check_out + timedelta(minutes=15)})
        self.env["mdl.attendance.device.event"]._timeline_reconcile_employee_ids([
            self.employee.id,
        ])
        self.assertTrue(attendance.exists())
        self.assertTrue(original_events[-1].conflict_dismissed)
        self.assertEqual(original_events.attendance_id, attendance)
        self.assertEqual(original_events.mapped("raw_line"), original_raw_lines)
        self.assertEqual(original_events[-1].event_datetime, attendance.check_out)

    def test_raw_endpoints_do_not_create_unused_odoo_logs(self):
        logs_before = self._odoo_logs()
        log, attendance = self._raw_attendance()
        self.assertEqual(self._odoo_logs(), logs_before)
        self.assertFalse(any(log.event_ids.mapped("odoo_generated")))
        for _iteration in range(3):
            attendance._ensure_attendance_device_events()
        attendance.write({"check_out": attendance.check_out + timedelta(minutes=5)})
        self.assertEqual(self._odoo_logs(), logs_before)
        self.assertEqual(len(self._events(attendance)), 2)

    def test_automatic_checkout_of_real_entry_remains_visible(self):
        attendance = self._manual_attendance(
            check_in="2026-09-03 13:21:00",
            check_out="2026-09-03 22:30:00",
            in_mode="manual",
            out_mode="technical",
        )
        events = self._events(attendance)
        self.assertTrue(attendance._is_attendance_event_source())
        self.assertEqual(len(events), 2)
        self.assertEqual(events.mapped("punch_state"), ["in", "out"])
        self.assertFalse(any(events.mapped("conflict_dismissed")))
        self.assertEqual(events[-1].event_datetime, attendance.check_out)

    def test_hide_saved_endpoint_does_not_delete_attendance_on_later_reconcile(self):
        _log, attendance = self._raw_attendance()
        events = self._events(attendance)
        attendance_snapshot = attendance.read(["check_in", "check_out", "employee_id"])
        events[0].action_hide()
        self.env["mdl.attendance.device.event"]._timeline_reconcile_employee_ids([
            self.employee.id,
        ])
        self.assertTrue(attendance.exists())
        self.assertEqual(attendance.read(["check_in", "check_out", "employee_id"]),
                         attendance_snapshot)
        self.assertEqual(events.attendance_id, attendance)
        self.assertTrue(events[0].conflict_dismissed)
