from datetime import date, datetime

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "mdl_attendance_segments")
class TestAttendanceSegments(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Segment Test Company"})
        cls.company.resource_calendar_id.tz = "UTC"
        cls.ruleset = cls.env["hr.attendance.segment.ruleset"].create({
            "name": "Night break",
            "company_id": cls.company.id,
            "rule_ids": [Command.create({
                "name": "Non-work night window",
                "sequence": 10,
                "base_off": "timing",
                "timing_type": "work_days",
                "timing_start": 1.5,
                "timing_stop": 6.5,
                "employer_tolerance": 0.5,
                "is_work": False,
            })],
        })
        cls.employee = cls.env["hr.employee"].with_company(cls.company).create({
            "name": "Segment Employee",
            "company_id": cls.company.id,
            "date_version": date(2025, 1, 1),
            "contract_date_start": date(2025, 1, 1),
            "resource_calendar_id": cls.company.resource_calendar_id.id,
            "segment_ruleset_id": cls.ruleset.id,
        })

    def test_night_window_splits_attendance(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 16, 0),
            "check_out": datetime(2026, 1, 6, 6, 30),
        })
        self.assertEqual(len(attendance.segment_ids), 2)
        self.assertEqual(attendance.segment_ids.mapped("is_work"), [True, False])
        self.assertAlmostEqual(attendance.presence_hours, 14.5)
        self.assertAlmostEqual(attendance.worked_hours, 9.5)

    def test_short_sleep_window_overlap_is_ignored(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 16, 0),
            "check_out": datetime(2026, 1, 6, 1, 45),
        })
        self.assertEqual(len(attendance.segment_ids), 1)
        self.assertTrue(attendance.segment_ids.is_work)
        self.assertAlmostEqual(attendance.worked_hours, 9.75)

    def test_morning_shift_is_fully_worked(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 6, 30),
            "check_out": datetime(2026, 1, 5, 16, 0),
        })
        self.assertEqual(len(attendance.segment_ids), 1)
        self.assertTrue(attendance.segment_ids.is_work)
        self.assertAlmostEqual(attendance.worked_hours, 9.5)

    def test_timing_tolerance_keeps_six_oclock_entry_as_work(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 6, 0),
            "check_out": datetime(2026, 1, 5, 7, 0),
        })
        self.assertEqual(len(attendance.segment_ids), 1)
        self.assertTrue(attendance.segment_ids.is_work)
        self.assertAlmostEqual(attendance.worked_hours, 1.0)

    def test_timing_employee_tolerance_keeps_initial_overlap_as_work(self):
        self.ruleset.rule_ids.write({
            "employer_tolerance": 0.0,
            "employee_tolerance": 0.25,
        })
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 16, 0),
            "check_out": datetime(2026, 1, 6, 6, 30),
        })
        segments = attendance.segment_ids.sorted("time_start")
        self.assertEqual(segments.mapped("is_work"), [True, False])
        self.assertEqual(segments[0].time_stop, datetime(2026, 1, 6, 1, 45))
        self.assertAlmostEqual(attendance.worked_hours, 9.75)

    def test_no_matching_rule_defaults_to_work(self):
        self.employee.segment_ruleset_id = False
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 8, 0),
            "check_out": datetime(2026, 1, 5, 16, 0),
        })
        self.assertEqual(len(attendance.segment_ids), 1)
        self.assertTrue(attendance.segment_ids.is_work)
        self.assertAlmostEqual(attendance.worked_hours, 8.0)

    def test_overlapping_timing_rules_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["hr.attendance.segment.rule"].create({
                "name": "Conflicting break",
                "ruleset_id": self.ruleset.id,
                "base_off": "timing",
                "timing_type": "work_days",
                "timing_start": 5.0,
                "timing_stop": 7.0,
                "is_work": False,
            })

    def test_manual_boundary_updates_neighbor(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 16, 0),
            "check_out": datetime(2026, 1, 6, 6, 30),
        })
        _first, second = attendance.segment_ids.sorted("time_start")
        with self.assertRaises(ValidationError):
            second.write({"time_start": datetime(2026, 1, 6, 1, 45)})
        attendance._validate_segment_coverage()

    def test_adjacent_same_type_segments_are_merged(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 16, 0),
            "check_out": datetime(2026, 1, 6, 6, 30),
        })
        _first, second = attendance.segment_ids.sorted("time_start")
        with self.assertRaises(ValidationError):
            second.write({"is_work": True})
        self.assertEqual(len(attendance.segment_ids), 2)
        attendance._validate_segment_coverage()

    def test_delete_segment_fills_from_right(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 16, 0),
            "check_out": datetime(2026, 1, 6, 6, 30),
        })
        _first, second = attendance.segment_ids.sorted("time_start")
        with self.assertRaises(ValidationError):
            second.unlink()
        self.assertEqual(len(attendance.segment_ids), 2)
        attendance._validate_segment_coverage()

    def test_boundary_can_swallow_following_segment(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 16, 0),
            "check_out": datetime(2026, 1, 6, 6, 30),
        })
        first, second = attendance.segment_ids.sorted("time_start")
        with self.assertRaises(ValidationError):
            first.write({"time_stop": second.time_stop})
        self.assertEqual(len(attendance.segment_ids), 2)
        attendance._validate_segment_coverage()

    def test_boundary_can_swallow_previous_segment(self):
        attendance = self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": datetime(2026, 1, 5, 16, 0),
            "check_out": datetime(2026, 1, 6, 6, 30),
        })
        first, second = attendance.segment_ids.sorted("time_start")
        with self.assertRaises(ValidationError):
            second.write({"time_start": first.time_start})
        self.assertEqual(len(attendance.segment_ids), 2)
        attendance._validate_segment_coverage()
