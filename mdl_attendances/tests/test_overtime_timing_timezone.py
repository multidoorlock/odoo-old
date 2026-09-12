from datetime import date, datetime, time, timedelta

import pytz

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "mdl_attendance_overtime_timezone")
class TestOvertimeTimingTimezone(TransactionCase):
    """Exercise native interval generation with real, segmented attendances."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({
            "name": "Overtime Timezone Test Company",
            "attendance_overtime_validation": "by_manager",
            "absence_management": False,
        })
        calendar_vals = {
            "name": "Sunday to Thursday, Jerusalem",
            "company_id": cls.company.id,
            "tz": "Asia/Jerusalem",
            "attendance_ids": [Command.create({
                "name": "Scheduled work",
                "dayofweek": weekday,
                "day_period": "morning",
                "hour_from": 7.5,
                "hour_to": 16.5,
            }) for weekday in ("6", "0", "1", "2", "3")],
        }
        # This addon is also tested when the optional payroll localization is
        # installed. Keep the fixture's explicit clock-based calendar in both.
        if "mdl_schedule_frequency" in cls.env["resource.calendar"]._fields:
            calendar_vals.update({
                "mdl_schedule_type": "attendance",
                "mdl_schedule_frequency": "fixed_intervals",
            })
        cls.calendar = cls.env["resource.calendar"].create(calendar_vals)
        cls.company.resource_calendar_id = cls.calendar
        cls.ruleset = cls.env["hr.attendance.overtime.ruleset"].create({
            "name": "After 16 on scheduled days",
            "company_id": cls.company.id,
        })
        cls.rule = cls.env["hr.attendance.overtime.rule"].create({
            "name": "Scheduled day after 16",
            "ruleset_id": cls.ruleset.id,
            "base_off": "timing",
            "timing_type": "work_days",
            "timing_start": 16.0,
            "timing_stop": 24.0,
            "employer_tolerance": 0.0,
            "paid": False,
        })
        cls.employee = cls.env["hr.employee"].with_company(cls.company).create({
            "name": "Overtime Timezone Test Employee",
            "company_id": cls.company.id,
            "date_version": date(2025, 1, 1),
            "contract_date_start": date(2025, 1, 1),
            "resource_calendar_id": cls.calendar.id,
            "ruleset_id": cls.ruleset.id,
            "segment_ruleset_id": False,
        })

    def _attendance(self, day, start_hour=7.5, stop_hour=18.0):
        timezone = pytz.timezone(self.calendar.tz)

        def to_utc(hour):
            local = datetime.combine(day, time.min) + timedelta(hours=hour)
            return timezone.localize(local).astimezone(pytz.utc).replace(tzinfo=None)

        return self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": to_utc(start_hour),
            "check_out": to_utc(stop_hour),
        })

    def _native_timing_values(self, attendance):
        # Reuse the same real native schedule and generator as _update_overtime.
        # Calling the value builder lets this test assert raw timing intervals
        # even when a payroll localization removes off-day OT in its later hook.
        first_day = attendance.check_in.date() - timedelta(days=1)
        last_day = attendance.check_out.date() + timedelta(days=1)
        start = pytz.utc.localize(datetime.combine(first_day, time.min))
        stop = pytz.utc.localize(datetime.combine(last_day, time.max))
        employees = attendance.employee_id
        versions = employees._get_version_periods(start, stop)
        schedules = employees._get_schedules_by_employee_by_work_type(
            start, stop, versions)
        dates = [value for values in attendance._get_dates().values() for value in values]
        return self.rule._generate_overtime_vals_v2(
            min(dates), max(dates), attendance, schedules)

    def _assert_timing_hours(self, attendance, expected):
        boundaries = (attendance.check_in, attendance.check_out)
        values = self._native_timing_values(attendance)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["employee_id"], self.employee.id)
        self.assertEqual(values[0]["rule_ids"], self.rule.ids)
        self.assertAlmostEqual(values[0]["duration"], expected, places=4)
        self.assertEqual((attendance.check_in, attendance.check_out), boundaries)
        attendance._validate_segment_coverage()

    def test_after_sixteen_keeps_two_hours_in_summer_and_winter(self):
        for day in (date(2026, 1, 5), date(2026, 7, 6)):
            with self.subTest(day=day):
                attendance = self._attendance(day)
                self._assert_timing_hours(attendance, 2.0)
                self.assertAlmostEqual(attendance.overtime_hours, 2.0)
                self.assertEqual(attendance.overtime_status, "to_approve")
                self.assertEqual(attendance.validated_overtime_hours, 0.0)

    def test_non_working_day_is_not_shortened_by_timezone_offset(self):
        self.rule.write({
            "timing_type": "non_work_days",
            "timing_start": 0.0,
            "timing_stop": 24.0,
        })
        for day in (date(2026, 1, 9), date(2026, 7, 10)):
            with self.subTest(day=day):
                self._assert_timing_hours(self._attendance(day, stop_hour=16.5), 9.0)

    def test_non_work_segment_is_excluded_after_localizing(self):
        break_ruleset = self.env["hr.attendance.segment.ruleset"].create({
            "name": "Break inside overtime window",
            "company_id": self.company.id,
            "rule_ids": [Command.create({
                "name": "Unpaid break 16:30 to 17:00",
                "base_off": "timing",
                "timing_type": "work_days",
                "timing_start": 16.5,
                "timing_stop": 17.0,
                "employee_tolerance": 0.0,
                "employer_tolerance": 0.0,
                "is_work": False,
            })],
        })
        self.employee.segment_ruleset_id = break_ruleset
        for day in (date(2026, 1, 5), date(2026, 7, 6)):
            with self.subTest(day=day):
                attendance = self._attendance(day)
                self.assertAlmostEqual(
                    sum(attendance.segment_ids.filtered(lambda row: not row.is_work).mapped("duration")),
                    0.5,
                )
                self._assert_timing_hours(attendance, 1.5)
                self.assertAlmostEqual(attendance.worked_hours, 10.0)

    def test_utc_employee_is_not_shifted(self):
        self.calendar.tz = "UTC"
        self._assert_timing_hours(self._attendance(date(2026, 7, 6)), 2.0)
