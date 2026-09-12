from datetime import date, datetime, time, timedelta

import pytz

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_il_morning_overtime')
class TestMorningOvertime(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Morning Overtime Test Company',
            'mdl_shift_cutoff': 13.0,
            'attendance_overtime_validation': 'by_manager',
            'absence_management': False,
        })
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Sunday to Thursday morning work',
            'company_id': cls.company.id,
            'tz': 'Asia/Jerusalem',
            'mdl_schedule_type': 'attendance',
            'mdl_schedule_frequency': 'fixed_intervals',
            'attendance_ids': [Command.create({
                'name': 'Scheduled day', 'dayofweek': weekday,
                'day_period': 'morning', 'hour_from': 7.5, 'hour_to': 16.5,
            }) for weekday in ('6', '0', '1', '2', '3')],
        })
        cls.company.resource_calendar_id = cls.calendar
        cls.ruleset = cls.env['hr.attendance.overtime.ruleset'].create({
            'name': 'Morning overtime after 16', 'company_id': cls.company.id,
        })
        cls.rule = cls.env['hr.attendance.overtime.rule'].create({
            'name': 'Morning only after 16',
            'ruleset_id': cls.ruleset.id,
            'base_off': 'timing', 'timing_type': 'work_days',
            'timing_start': 16.0, 'timing_stop': 24.0,
            'mdl_morning_shift_only': True,
            'employer_tolerance': 0.0, 'paid': True,
            'work_entry_type_id': cls.env.ref('hr_work_entry.work_entry_type_overtime').id,
        })
        cls.employee = cls.env['hr.employee'].with_company(cls.company).create({
            'name': 'Morning Overtime Test Employee',
            'company_id': cls.company.id,
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'resource_calendar_id': cls.calendar.id,
            'ruleset_id': cls.ruleset.id,
        })
        cls.version = cls.employee.version_id
        cls.version.work_entry_source = 'attendance'

    def _attendance(self, day, start=7.5, stop=18.0):
        tz = pytz.timezone(self.calendar.tz)

        def utc(hour):
            local = datetime.combine(day, time.min) + timedelta(hours=hour)
            return tz.localize(local).astimezone(pytz.utc).replace(tzinfo=None)

        return self.env['hr.attendance'].create({
            'employee_id': self.employee.id,
            'check_in': utc(start), 'check_out': utc(stop),
        })

    def _day_values(self, day):
        tz = pytz.timezone(self.calendar.tz)
        start = tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        stop = tz.localize(datetime.combine(day, time.max)).astimezone(pytz.utc).replace(tzinfo=None)
        return self.version._mdl_get_normalized_work_entry_vals(start, stop)

    def test_morning_after_sixteen_is_two_pending_hours(self):
        for day in (date(2026, 1, 5), date(2026, 7, 6)):
            with self.subTest(day=day):
                attendance = self._attendance(day)
                self.assertAlmostEqual(attendance.overtime_hours, 2.0)
                self.assertEqual(attendance.overtime_status, 'to_approve')
                self.assertEqual(attendance.linked_overtime_ids.rule_ids, self.rule)
                self.assertEqual(attendance.validated_overtime_hours, 0.0)

    def test_evening_shift_and_exact_cutoff_do_not_get_morning_overtime(self):
        for day, start, stop in [
                (date(2026, 7, 6), 16.0, 31.0),
                (date(2026, 7, 8), 13.0, 18.0)]:
            with self.subTest(start=start):
                attendance = self._attendance(day, start=start, stop=stop)
                self.assertFalse(attendance.linked_overtime_ids)
                self.assertEqual(attendance.overtime_hours, 0.0)
                self.assertFalse(attendance.overtime_status)

    def test_checkout_before_sixteen_does_not_create_overtime(self):
        attendance = self._attendance(date(2026, 7, 6), stop=15.5)
        self.assertFalse(attendance.linked_overtime_ids)
        self.assertEqual(attendance.overtime_hours, 0.0)

    def test_off_schedule_friday_stays_additional_day_without_overtime(self):
        # A legacy off-day rule must not add a second payment category.
        self.rule.copy({
            'name': 'Legacy off-day overtime',
            'timing_type': 'non_work_days', 'timing_start': 0.0,
            'mdl_morning_shift_only': False,
        })
        day = date(2026, 7, 10)
        attendance = self._attendance(day)
        self.assertFalse(attendance.linked_overtime_ids)
        values = self._day_values(day)
        additional = self.env.ref('l10n_il_hr_payroll.work_entry_type_additional_day')
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]['work_entry_type_id'], additional.id)
        self.assertAlmostEqual(values[0]['duration'], 9.0)
        self.assertEqual(values[0]['mdl_rate_category'], 'additional_day')

    def test_employee_with_friday_schedule_gets_regular_day_overtime(self):
        self.calendar.attendance_ids = [Command.create({
            'name': 'Friday morning', 'dayofweek': '4',
            'day_period': 'morning', 'hour_from': 7.5, 'hour_to': 16.5,
        })]
        day = date(2026, 7, 10)
        attendance = self._attendance(day)
        self.assertAlmostEqual(attendance.overtime_hours, 2.0)
        values = self._day_values(day)
        additional = self.env.ref('l10n_il_hr_payroll.work_entry_type_additional_day')
        self.assertFalse([row for row in values if row['work_entry_type_id'] == additional.id])

    def test_unrestricted_rules_still_apply_to_evening(self):
        unrestricted = self.rule.copy({
            'name': 'Unrestricted timing control',
            'mdl_morning_shift_only': False,
        })
        attendance = self._attendance(date(2026, 7, 6), start=16.0, stop=18.0)
        self.assertAlmostEqual(attendance.overtime_hours, 2.0)
        self.assertEqual(attendance.linked_overtime_ids.rule_ids, unrestricted)
