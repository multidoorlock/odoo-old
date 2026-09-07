from datetime import date, datetime

import pytz

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "l10n_il_hr_payroll_work_entries")
class TestWorkEntryNormalization(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({
            "name": "Work Entry Normalization Company",
            "mdl_shift_morning_hours": 9.5,
            "mdl_shift_evening_hours": 9.5,
            "mdl_shift_cutoff": 12.0,
        })
        cls.calendar = cls.env["resource.calendar"].with_company(cls.company).create({
            "name": "9.5 Hour Fixed Calendar",
            "company_id": cls.company.id,
            "tz": "UTC",
            "mdl_schedule_type": "attendance",
            "mdl_schedule_frequency": "fixed_intervals",
            "attendance_ids": [Command.create({
                "name": "Monday",
                "dayofweek": "0",
                "day_period": "morning",
                "hour_from": 6.5,
                "hour_to": 16.0,
            })],
        })
        cls.employee = cls.env["hr.employee"].with_company(cls.company).create({
            "name": "Normalization Employee",
            "company_id": cls.company.id,
            "date_version": date(2025, 1, 1),
            "contract_date_start": date(2025, 1, 1),
            "resource_calendar_id": cls.calendar.id,
        })
        cls.version = cls.employee.version_id
        cls.version.write({
            "work_entry_source": "attendance",
            "mdl_wage_type": "mdl_monthly",
            "ruleset_id": False,
        })

    def _attendance(self, start, stop):
        return self.env["hr.attendance"].create({
            "employee_id": self.employee.id,
            "check_in": start,
            "check_out": stop,
        })

    def _values(self, start_day, stop_day):
        values = self.version._mdl_get_normalized_work_entry_vals(
            datetime.combine(start_day, datetime.min.time()),
            datetime.combine(stop_day, datetime.min.time()),
        )
        types = self.env["hr.work.entry.type"].browse(
            [value["work_entry_type_id"] for value in values])
        codes = dict(zip(types.ids, types.mapped("code")))
        return [(codes[value["work_entry_type_id"]], value) for value in values]

    def test_native_schedule_mapping_stays_on_odoo_fields(self):
        self.assertEqual(self.calendar._mdl_native_schedule_values("fixed_intervals"), {
            "schedule_type": "fully_fixed", "duration_based": False,
        })
        self.assertEqual(self.calendar._mdl_native_schedule_values("daily_duration"), {
            "schedule_type": "fully_fixed", "duration_based": True,
        })
        self.assertEqual(self.calendar._mdl_native_schedule_values("weekly_quota"), {
            "schedule_type": "flexible", "duration_based": False,
        })

    def test_work_entry_values_accept_timezone_aware_gantt_window(self):
        date_from = pytz.utc.localize(datetime(2026, 1, 5, 0, 0))
        date_to = pytz.utc.localize(datetime(2026, 1, 6, 0, 0))
        values = self.version._get_work_entries_values(date_from, date_to)
        self.assertIsInstance(values, list)

    def test_removed_company_and_employee_fields_are_not_registered(self):
        company_fields = self.env["res.company"]._fields
        version_fields = self.env["hr.version"]._fields
        for field_name in (
            "mdl_weekend_sunday", "mdl_weekend_friday", "mdl_weekend_saturday",
            "mdl_shift_morning_start", "mdl_shift_morning_end",
            "mdl_shift_evening_start", "mdl_shift_evening_end",
            "mdl_shift_sleep_start", "mdl_shift_sleep_end",
            "mdl_shift_paid_hours", "mdl_shift_sleep_hours",
        ):
            self.assertNotIn(field_name, company_fields)
        for field_name in (
            "mdl_weekend_wage", "mdl_weekend_rate_type",
            "mdl_weekend_hourly_wage", "mdl_additional_day_rate_type",
        ):
            self.assertNotIn(field_name, version_fields)

    def test_monthly_computed_rates_cannot_be_overwritten_by_stale_form_values(self):
        self.version.write({
            "wage": 10000.0,
            "mdl_daily_wage": 0.0,
            "hourly_wage": 0.0,
            "mdl_hourly_wage_exact": 0.0,
        })
        average_monthly_hours = self.calendar.hours_per_week * 52 / 12
        self.assertAlmostEqual(
            self.version.mdl_daily_wage,
            10000.0 * self.calendar.hours_per_day / average_monthly_hours,
            places=2,
        )
        self.assertAlmostEqual(
            self.version.hourly_wage,
            10000.0 / average_monthly_hours,
            places=2,
        )

    def test_monthly_rates_have_a_weekly_basis_in_all_schedule_modes(self):
        modes = (
            ('attendance', 'fixed_intervals'),
            ('attendance', 'daily_duration'),
            ('attendance', 'weekly_quota'),
            ('shifts', 'daily_duration'),
            ('shifts', 'weekly_quota'),
        )
        for schedule_type, frequency in modes:
            values = {
                'name': '%s %s payroll basis' % (schedule_type, frequency),
                'company_id': self.company.id,
                'tz': 'Asia/Jerusalem',
                'mdl_schedule_type': schedule_type,
                'mdl_schedule_frequency': frequency,
                'mdl_hours_per_day': 8.0,
                'mdl_shifts_per_week': 5,
            }
            if frequency == 'weekly_quota':
                values['hours_per_week'] = 40.0
            calendar = self.env['resource.calendar'].create(values)
            self.assertGreater(
                calendar.hours_per_week,
                0.0,
                '%s/%s must expose payroll weekly hours' % (
                    schedule_type, frequency),
            )
            self.version.write({
                'resource_calendar_id': calendar.id,
                'mdl_wage_type': 'mdl_monthly',
                'wage': 10000.0,
            })
            self.assertGreater(self.version.mdl_daily_wage, 0.0)
            self.assertGreater(self.version.hourly_wage, 0.0)
        self.assertGreater(self.version.mdl_hourly_wage_exact, 0.0)

    def test_morning_shift_is_one_full_regular_day(self):
        self._attendance(datetime(2026, 1, 5, 6, 30), datetime(2026, 1, 5, 16, 0))
        values = self._values(date(2026, 1, 5), date(2026, 1, 6))
        regular = [value for code, value in values if code == "WORK100"]
        overtime = [value for code, value in values if code == "OVERTIME"]
        self.assertEqual(len(regular), 1)
        self.assertAlmostEqual(regular[0]["duration"], 9.5)
        self.assertAlmostEqual(regular[0]["mdl_actual_hours"], 9.5)
        self.assertFalse(overtime)

    def test_overtime_rounding_threshold_is_forty_minutes(self):
        self._attendance(datetime(2026, 1, 5, 6, 30), datetime(2026, 1, 5, 16, 39))
        values = self._values(date(2026, 1, 5), date(2026, 1, 6))
        self.assertFalse([value for code, value in values if code == "OVERTIME"])

        self.env["hr.attendance"].search([
            ("employee_id", "=", self.employee.id),
        ]).unlink()
        self._attendance(datetime(2026, 1, 5, 6, 30), datetime(2026, 1, 5, 16, 40))
        values = self._values(date(2026, 1, 5), date(2026, 1, 6))
        overtime = [value for code, value in values if code == "OVERTIME"]
        self.assertEqual(len(overtime), 1)
        self.assertAlmostEqual(overtime[0]["duration"], 1.0)

    def test_short_attendance_normalizes_to_half_day(self):
        self._attendance(datetime(2026, 1, 5, 6, 30), datetime(2026, 1, 5, 10, 30))
        values = self._values(date(2026, 1, 5), date(2026, 1, 6))
        regular = [value for code, value in values if code == "WORK100"]
        absence = [value for code, value in values if code == "UNPAID_ABSENCE"]
        self.assertEqual(len(regular), 1)
        self.assertAlmostEqual(regular[0]["duration"], 4.75)
        self.assertEqual(regular[0]["mdl_rounding_reason"], "half_day")
        self.assertFalse(absence)

    def test_weekly_quota_moves_third_day_to_additional_day(self):
        weekly_calendar = self.env["resource.calendar"].with_company(self.company).create({
            "name": "Two Day Weekly Quota",
            "company_id": self.company.id,
            "tz": "UTC",
            "mdl_schedule_type": "attendance",
            "mdl_schedule_frequency": "weekly_quota",
            "mdl_hours_per_day": 9.5,
            "hours_per_week": 19.0,
        })
        self.version.resource_calendar_id = weekly_calendar
        for day in (5, 6, 7):
            self._attendance(
                datetime(2026, 1, day, 6, 30),
                datetime(2026, 1, day, 16, 0),
            )

        values = self._values(date(2026, 1, 5), date(2026, 1, 8))
        regular = [value for code, value in values if code == "WORK100"]
        additional = [value for code, value in values if code == "ADDITIONAL_DAY"]
        self.assertEqual(len(regular), 2)
        self.assertEqual(len(additional), 1)
        self.assertAlmostEqual(sum(value["duration"] for value in regular), 19.0)
        self.assertAlmostEqual(additional[0]["duration"], 9.5)

    def test_daily_off_schedule_day_replaces_regular_work(self):
        # This suite exercises work-entry normalization rather than salary
        # category selection. Keep the existing category compatible with the
        # daily worker type, as the UI and server now require.
        self.version.structure_type_id.wage_type = "hourly"
        self.version.write({
            "mdl_wage_type": "mdl_daily",
            "mdl_daily_wage": 400.0,
        })
        self._attendance(
            datetime(2026, 1, 10, 6, 30),
            datetime(2026, 1, 10, 16, 0),
        )

        values = self._values(date(2026, 1, 10), date(2026, 1, 11))
        codes = [code for code, _value in values]
        self.assertEqual(codes, ["ADDITIONAL_DAY"])

    def test_daily_weekly_quota_has_one_row_for_the_extra_day(self):
        weekly_calendar = self.env["resource.calendar"].with_company(
            self.company).create({
                "name": "Daily Two Day Weekly Quota",
                "company_id": self.company.id,
                "tz": "UTC",
                "mdl_schedule_type": "attendance",
                "mdl_schedule_frequency": "weekly_quota",
                "mdl_hours_per_day": 9.5,
                "hours_per_week": 19.0,
            })
        self.version.structure_type_id.wage_type = "hourly"
        self.version.write({
            "resource_calendar_id": weekly_calendar.id,
            "mdl_wage_type": "mdl_daily",
            "mdl_daily_wage": 400.0,
        })
        for day in (5, 6, 7):
            self._attendance(
                datetime(2026, 1, day, 6, 30),
                datetime(2026, 1, day, 16, 0),
            )

        values = self._values(date(2026, 1, 5), date(2026, 1, 8))
        codes = [code for code, _value in values]
        self.assertEqual(codes.count("WORK100"), 2)
        self.assertEqual(codes.count("ADDITIONAL_DAY"), 1)
        self.assertEqual(len(codes), 3)

    def test_calendar_weekday_is_not_a_separate_weekend_rate(self):
        self._attendance(
            datetime(2026, 1, 10, 6, 30), datetime(2026, 1, 10, 16, 0))
        values = self._values(date(2026, 1, 10), date(2026, 1, 11))
        self.assertFalse([value for code, value in values if code == "WEEKEND"])
        self.assertEqual(
            len([value for code, value in values if code == "ADDITIONAL_DAY"]), 1)

    def test_additional_day_wins_over_zero_expected_odoo_overtime(self):
        ruleset = self.env["hr.attendance.overtime.ruleset"].create({
            "name": "Weekend Through Odoo Overtime",
            "company_id": self.company.id,
        })
        self.version.ruleset_id = ruleset
        attendance = self._attendance(
            datetime(2026, 1, 10, 6, 30), datetime(2026, 1, 10, 16, 0))
        overtime_type = self.env.ref("hr_work_entry.work_entry_type_overtime")
        self.env["hr.attendance.overtime.line"].create({
            "employee_id": self.employee.id,
            "date": date(2026, 1, 10),
            "status": "approved",
            "duration": 9.5,
            "manual_duration": 9.5,
            "time_start": attendance.check_in,
            "time_stop": attendance.check_out,
            "work_entry_type_overtime_id": overtime_type.id,
        })
        values = self._values(date(2026, 1, 10), date(2026, 1, 11))
        overtime = [value for code, value in values if code == "OVERTIME"]
        additional = [
            value for code, value in values if code == "ADDITIONAL_DAY"]
        self.assertFalse(overtime)
        self.assertEqual(len(additional), 1)
        self.assertAlmostEqual(additional[0]["duration"], 9.5)
        self.assertEqual(additional[0]["mdl_rounding_reason"], "full_day")

    def test_additional_day_removes_native_overtime_rows_from_attendance(self):
        self.version.ruleset_id = self.env[
            "hr.attendance.overtime.ruleset"].create({
                "name": "Off Schedule Overtime",
                "company_id": self.company.id,
            })
        attendance = self._attendance(
            datetime(2026, 1, 10, 6, 30), datetime(2026, 1, 10, 15, 30))
        overtime_type = self.env.ref("hr_work_entry.work_entry_type_overtime")
        lines = self.env["hr.attendance.overtime.line"].create([{
            "employee_id": self.employee.id,
            "date": date(2026, 1, 10),
            "status": "approved",
            "duration": duration,
            "manual_duration": duration,
            "time_start": attendance.check_in,
            "time_stop": attendance.check_out,
            "work_entry_type_overtime_id": overtime_type.id,
        } for duration in (6.0, 3.0)])
        self.assertTrue(lines.exists())

        attendance._mdl_remove_additional_day_overtimes()

        self.assertFalse(lines.exists())
        self.assertFalse(attendance.linked_overtime_ids)

    def test_real_generation_replaces_two_overtime_lines_with_one_additional_day(self):
        ruleset = self.env["hr.attendance.overtime.ruleset"].create({
            "name": "Friday Overtime Split",
            "company_id": self.company.id,
        })
        self.version.ruleset_id = ruleset
        self.version.mdl_additional_day_wage = 400.0
        attendance = self._attendance(
            datetime(2026, 1, 10, 6, 30), datetime(2026, 1, 10, 15, 30))
        overtime_type = self.env.ref("hr_work_entry.work_entry_type_overtime")
        for duration in (6.0, 3.0):
            self.env["hr.attendance.overtime.line"].create({
                "employee_id": self.employee.id,
                "date": date(2026, 1, 10),
                "status": "approved",
                "duration": duration,
                "manual_duration": duration,
                "time_start": attendance.check_in,
                "time_stop": attendance.check_out,
                "work_entry_type_overtime_id": overtime_type.id,
            })

        entries = self.version.generate_work_entries(
            date(2026, 1, 10), date(2026, 1, 10), force=True)
        additional = entries.filtered(
            lambda entry: entry.work_entry_type_id.code == "ADDITIONAL_DAY")
        overtime = entries.filtered(
            lambda entry: entry.work_entry_type_id.code == "OVERTIME")

        self.assertEqual(len(additional), 1)
        self.assertFalse(overtime)
        self.assertAlmostEqual(additional.duration, 9.5)
        self.assertAlmostEqual(additional.mdl_actual_hours, 9.0)
        self.assertEqual(additional.mdl_rate_category, "additional_day")

    def test_calendar_source_clocking_regenerates_an_already_generated_extra_day(self):
        """A late clocking must update a static calendar payroll period.

        Odoo keeps generating the planned WORK100 rows from the calendar.  If
        an attendance is entered afterwards on an off-schedule day, our hybrid
        layer regenerates that day and adds one separate ADDITIONAL_DAY row.
        """
        self.version.write({
            "work_entry_source": "calendar",
            "mdl_wage_type": "mdl_monthly",
            "mdl_additional_day_wage": 400.0,
        })
        self.version.generate_work_entries(
            date(2026, 1, 5), date(2026, 1, 10), force=True)
        attendance = self._attendance(
            datetime(2026, 1, 10, 6, 30),
            datetime(2026, 1, 10, 16, 0),
        )

        active_entries = self.env["hr.work.entry"].search([
            ("version_id", "=", self.version.id),
            ("date", "=", date(2026, 1, 10)),
            ("state", "!=", "cancelled"),
        ])
        additional = active_entries.filtered(
            lambda entry: entry.work_entry_type_id.code == "ADDITIONAL_DAY")
        overtime = active_entries.filtered(
            lambda entry: entry.work_entry_type_id.code == "OVERTIME")
        self.assertEqual(len(additional), 1)
        self.assertEqual(additional.attendance_id, attendance)
        self.assertFalse(overtime)

    def test_morning_shift_uses_its_own_company_duration(self):
        self.company.mdl_shift_morning_hours = 8.0
        shift_calendar = self.env["resource.calendar"].with_company(self.company).create({
            "name": "Eight Hour Morning Shift Calendar",
            "company_id": self.company.id,
            "tz": "UTC",
            "mdl_schedule_type": "shifts",
            "mdl_schedule_frequency": "daily_duration",
            "mdl_shift_day_monday": True,
        })
        self.version.resource_calendar_id = shift_calendar
        self._attendance(
            datetime(2026, 1, 5, 6, 30), datetime(2026, 1, 5, 14, 30))
        values = self._values(date(2026, 1, 5), date(2026, 1, 6))
        regular = [value for code, value in values if code == "WORK100"]
        self.assertEqual(len(regular), 1)
        self.assertAlmostEqual(regular[0]["duration"], 8.0)
        self.assertFalse([value for code, value in values if code == "OVERTIME"])

    def test_segmented_night_shift_is_paid_9_5_hours_plus_5_sleep(self):
        if not self.env.registry.get("hr.attendance.segment.ruleset"):
            self.skipTest("Attendance segmentation is not installed")
        shift_calendar = self.env["resource.calendar"].with_company(self.company).create({
            "name": "Night Shift Calendar",
            "company_id": self.company.id,
            "tz": "UTC",
            "mdl_schedule_type": "shifts",
            "mdl_schedule_frequency": "daily_duration",
            "mdl_shift_day_monday": True,
        })
        ruleset = self.env["hr.attendance.segment.ruleset"].create({
            "name": "Night Sleep 01:30-06:30",
            "company_id": self.company.id,
            "rule_ids": [Command.create({
                "name": "Night Sleep",
                "sequence": 10,
                "base_off": "timing",
                "timing_type": "work_days",
                "timing_start": 1.5,
                "timing_stop": 6.5,
                "employer_tolerance": 0.5,
                "is_work": False,
            })],
        })
        self.version.write({
            "resource_calendar_id": shift_calendar.id,
            "segment_ruleset_id": ruleset.id,
        })
        attendance = self._attendance(
            datetime(2026, 1, 5, 16, 0), datetime(2026, 1, 6, 6, 30))
        self.assertAlmostEqual(attendance.presence_hours, 14.5)
        self.assertAlmostEqual(attendance.worked_hours, 9.5)

        values = self._values(date(2026, 1, 5), date(2026, 1, 6))
        regular = [value for code, value in values if code == "WORK100"]
        sleep = [value for code, value in values if code == "SLEEP"]
        overtime = [value for code, value in values if code == "OVERTIME"]
        self.assertEqual(len(regular), 1)
        self.assertAlmostEqual(regular[0]["duration"], 9.5)
        self.assertEqual(len(sleep), 1)
        self.assertAlmostEqual(sleep[0]["duration"], 5.0)
        self.assertFalse(overtime)
