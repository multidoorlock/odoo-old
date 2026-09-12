from datetime import date, datetime, time, timedelta

import pytz
from lxml import etree

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'mdl_attendance_shift_quantity')
class TestOvertimeShiftQuantity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Whole-shift regression company',
            'attendance_overtime_validation': 'by_manager',
            'absence_management': True,
        })
        calendar_vals = {
            'name': 'Whole-shift nine-hour calendar',
            'company_id': cls.company.id, 'tz': 'Asia/Jerusalem',
            'attendance_ids': [Command.create({
                'name': 'Scheduled workday', 'dayofweek': weekday,
                'day_period': 'morning', 'hour_from': 7.5, 'hour_to': 16.5,
            }) for weekday in ('6', '0', '1', '2', '3')],
        }
        if 'mdl_schedule_type' in cls.env['resource.calendar']._fields:
            calendar_vals.update(mdl_schedule_type='attendance', mdl_schedule_frequency='fixed_intervals')
        cls.calendar = cls.env['resource.calendar'].create(calendar_vals)
        cls.company.resource_calendar_id = cls.calendar
        cls.ruleset = cls.env['hr.attendance.overtime.ruleset'].create({
            'name': 'Whole-shift effective work', 'company_id': cls.company.id,
        })
        rule_vals = {
            'name': 'Nine effective hours', 'ruleset_id': cls.ruleset.id,
            'base_off': 'quantity', 'quantity_period': 'shift',
            'expected_hours_from_contract': False, 'expected_hours': 9.0,
            'employee_tolerance': 9.0, 'employer_tolerance': 0.0, 'paid': True,
        }
        if 'work_entry_type_id' in cls.env['hr.attendance.overtime.rule']._fields:
            rule_vals['work_entry_type_id'] = cls.env.ref('hr_work_entry.work_entry_type_overtime').id
        cls.rule = cls.env['hr.attendance.overtime.rule'].create(rule_vals)
        cls.day = date(2026, 7, 6)
        cls.tz = pytz.timezone('Asia/Jerusalem')

    def _utc(self, day, hour):
        local = datetime.combine(day, time.min) + timedelta(hours=hour)
        return self.tz.localize(local).astimezone(pytz.utc).replace(tzinfo=None)

    def _employee(self, breaks=(), calendar=None):
        values = {
            'name': 'Whole-shift fixture employee', 'company_id': self.company.id,
            'date_version': date(2025, 1, 1), 'contract_date_start': date(2025, 1, 1),
            'resource_calendar_id': (calendar or self.calendar).id,
            'ruleset_id': self.ruleset.id, 'segment_ruleset_id': False,
        }
        if breaks:
            segment_ruleset = self.env['hr.attendance.segment.ruleset'].create({
                'name': 'Whole-shift non-work intervals', 'company_id': self.company.id,
                'rule_ids': [Command.create({
                    'name': 'Non-work interval', 'base_off': 'timing',
                    'timing_type': 'work_days', 'timing_start': start, 'timing_stop': stop,
                    'is_work': False, 'employer_tolerance': 0.0, 'employee_tolerance': 0.0,
                }) for start, stop in breaks],
            })
            values['segment_ruleset_id'] = segment_ruleset.id
        return self.env['hr.employee'].with_company(self.company).create(values)

    def _attendances(self, spans, breaks=(), day=None, employee=None):
        employee = employee or self._employee(breaks)
        day = day or self.day
        return self.env['hr.attendance'].create([{
            'employee_id': employee.id, 'check_in': self._utc(day, start),
            'check_out': self._utc(day, stop),
        } for start, stop in spans])

    def _assert_hours(self, attendances, effective, raw, approval=None):
        lines = attendances.linked_overtime_ids
        self.assertAlmostEqual(sum(attendances.mapped('worked_hours')), effective, places=4)
        self.assertAlmostEqual(sum(lines.mapped('duration')), raw, places=4)
        self.assertAlmostEqual(sum(lines.mapped('manual_duration')),
                               raw if approval is None else approval, places=4)
        return lines

    def test_quantity_uses_effective_work_independent_of_clock(self):
        for start in (4, 7, 12):
            with self.subTest(start=start):
                attendances = self._attendances([(start, start + 11)])
                self._assert_hours(attendances, 11, 2)
                attendances._update_overtime()
                attendances._update_overtime()
                self._assert_hours(attendances, 11, 2)

    def test_non_work_segments_and_repeated_generation(self):
        for breaks, effective, overtime in [([(9, 12)], 9, 0), ([(9, 10)], 11, 2), ([(12, 13)], 11, 2)]:
            with self.subTest(breaks=breaks):
                attendances = self._attendances([(6, 18)], breaks)
                self._assert_hours(attendances, effective, overtime)
                for _ in range(2):
                    attendances._update_overtime()
                    self._assert_hours(attendances, effective, overtime)
                marked = attendances.segment_ids.filtered(lambda segment: segment.is_work and segment.is_overtime)
                self.assertAlmostEqual(sum(marked.mapped('duration')), overtime, places=4)

    def test_overtime_refresh_preserves_manual_non_work_boundaries(self):
        attendance = self._attendances([(6, 18)], [(9, 10)])
        non_work = attendance.segment_ids.filtered(lambda segment: not segment.is_work)
        following = attendance.segment_ids.filtered(lambda segment: segment.time_start == non_work.time_stop)
        self.assertEqual(len(non_work), 1)
        self.assertEqual(len(following), 1)
        # Simulate an existing accepted manual source definition: extend the
        # break to 10:30, keeping a complete partition. Regeneration of rules
        # would incorrectly replace this with the configured 09:00-10:00.
        boundary = self._utc(self.day, 10.5)
        non_work.with_context(segment_boundary_sync=True).write({
            'time_stop': boundary, 'manual_override': True,
        })
        following.with_context(segment_boundary_sync=True).write({
            'time_start': boundary, 'manual_override': True,
        })
        protected = non_work.read(['id', 'time_start', 'time_stop', 'is_work', 'rule_id', 'manual_override'])
        attendance._segments_changed()
        self._assert_hours(attendance, 10.5, 1.5)
        self.assertEqual(non_work.read(list(protected[0])), protected)
        marked = attendance.segment_ids.filtered('is_overtime')
        self.assertAlmostEqual(sum(marked.mapped('duration')), 1.5)
        self.assertTrue(all(marked.mapped('is_work')))
        self.assertEqual(min(marked.mapped('time_start')), self._utc(self.day, 16.5))
        snapshot = attendance.segment_ids.sorted('id').read([
            'id', 'time_start', 'time_stop', 'is_work', 'is_overtime', 'rule_id', 'manual_override'])
        attendance._update_overtime()
        self.assertEqual(attendance.segment_ids.sorted('id').read(list(snapshot[0])), snapshot)
        # The historical repair API remains decoupled from timeline mutations.
        attendance.linked_overtime_ids.unlink()
        self.assertEqual(attendance.segment_ids.sorted('id').read(list(snapshot[0])), snapshot)

    def test_multiple_attendances_share_one_workday(self):
        attendances = self._attendances([(6, 10), (11, 19)], [(7, 8)])
        self._assert_hours(attendances, 11, 2)
        attendances[-1]._update_overtime()
        self._assert_hours(attendances, 11, 2)
        self.assertEqual(attendances.linked_overtime_ids.mapped('date'), [self.day])

    def test_overnight_non_work_and_previous_workday_regeneration(self):
        attendances = self._attendances([(16, 31)], [(1.5, 6.5)])
        self._assert_hours(attendances, 10, 1)
        self.assertEqual(attendances.linked_overtime_ids.date, self.day)
        # The next workday update overlaps only the overnight punch. The full
        # previous business day must still include its earlier separate punch.
        worker = self._employee()
        previous = self._attendances([(6, 10), (22, 29)], employee=worker)
        self._assert_hours(previous, 11, 2)
        following = self._attendances([(7, 16)], day=self.day + timedelta(days=1), employee=worker)
        following._update_overtime()
        self._assert_hours(previous, 11, 2)
        self._assert_hours(following, 9, 0)

    def test_dst_measures_elapsed_work_not_wall_clock(self):
        seven_day = self.calendar.copy({
            'name': 'DST seven-day fixture',
            'attendance_ids': [Command.clear()] + [Command.create({
                'name': 'DST scheduled day', 'dayofweek': str(weekday),
                'day_period': 'morning', 'hour_from': 7.5, 'hour_to': 16.5,
            }) for weekday in range(7)],
        })
        for start in (datetime(2026, 3, 26, 19), datetime(2026, 10, 24, 19)):
            with self.subTest(start=start):
                worker = self._employee(calendar=seven_day)
                attendance = self.env['hr.attendance'].create({
                    'employee_id': worker.id, 'check_in': start,
                    'check_out': start + timedelta(hours=11),
                })
                self._assert_hours(attendance, 11, 2)
                local_start, local_stop = attendance._get_localized_times()
                self.assertNotEqual((local_stop - local_start).total_seconds() / 3600, 11)
                self.assertEqual(attendance.linked_overtime_ids.date, local_start.date())

    def test_rounding_boundaries_preserve_raw_work_and_manual_baseline(self):
        self.rule.mdl_shift_rounding_threshold_minutes = 40
        for seconds, expected in [(2399, 0), (2400, 1), (5999, 1), (6000, 2)]:
            with self.subTest(seconds=seconds):
                attendance = self._attendances([(7, 16 + seconds / 3600)])
                raw = round(seconds / 3600, 4) if expected else 0
                lines = self._assert_hours(attendance, 9 + seconds / 3600, raw, expected)
                if expected:
                    self.assertEqual(lines.status, 'to_approve')
                    self.assertAlmostEqual(lines.mdl_auto_approval_hours, expected)
                    self.assertFalse(lines._mdl_has_manual_duration_override())
                    lines.write({'status': 'approved'})
                    self.assertAlmostEqual(attendance.validated_overtime_hours, expected)
                    self.assertAlmostEqual(attendance.overtime_hours, raw, places=4)
                    self.assertAlmostEqual(sum(attendance.segment_ids.filtered('is_overtime').mapped('duration')), raw, places=3)
                attendance._update_overtime()
                self._assert_hours(attendance, 9 + seconds / 3600, raw, expected)
                self.assertTrue(all(line.status == 'to_approve' for line in attendance.linked_overtime_ids))

    def test_round_once_across_multiple_source_punches(self):
        self.rule.mdl_shift_rounding_threshold_minutes = 40
        attendance = self._attendances([(6, 16), (18, 18.75)])
        lines = self._assert_hours(attendance, 10.75, 1.75, 2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.manual_duration > 0 and line.mdl_auto_approval_hours > 0 for line in lines))
        self.assertTrue(all(not line._mdl_has_manual_duration_override() for line in lines))
        attendance._update_overtime()
        self._assert_hours(attendance, 10.75, 1.75, 2)

    def test_automatic_rounding_is_not_a_human_edit(self):
        self.company.attendance_overtime_validation = 'no_validation'
        self.rule.mdl_shift_rounding_threshold_minutes = 40
        attendance = self._attendances([(7, 16 + 40 / 60)])
        self.assertEqual(attendance.linked_overtime_ids.status, 'approved')
        attendance._update_overtime()
        lines = self._assert_hours(attendance, 9 + 40 / 60, 0.6667, 1)
        self.assertEqual(lines.status, 'approved')
        lines.manual_duration = 1.25
        self.assertTrue(lines._mdl_has_manual_duration_override())
        attendance._update_overtime()
        lines = self._assert_hours(attendance, 9 + 40 / 60, 0.6667, 1)
        self.assertEqual(lines.status, 'to_approve')
        self.assertFalse(lines._mdl_has_manual_duration_override())

    def test_additional_day_remains_separate(self):
        additional_type = self.env.ref('l10n_il_hr_payroll.work_entry_type_additional_day', raise_if_not_found=False)
        if not additional_type:
            self.skipTest('Additional-day payroll classification is not installed')
        day = date(2026, 7, 10)
        attendance = self._attendances([(7, 18)], day=day)
        self._assert_hours(attendance, 11, 0)
        self.assertFalse(attendance.segment_ids.filtered('is_overtime'))
        attendance._update_overtime()
        self._assert_hours(attendance, 11, 0)
        self.assertFalse(attendance.segment_ids.filtered('is_overtime'))
        values = attendance.employee_id.version_id._mdl_get_normalized_work_entry_vals(
            self._utc(day, 0), self._utc(day + timedelta(days=1), 0) - timedelta(microseconds=1))
        self.assertAlmostEqual(sum(value['duration'] for value in values
                                   if value.get('work_entry_type_id') == additional_type.id), 9)

    def test_neighboring_additional_day_stays_separate_after_overnight_update(self):
        additional_type = self.env.ref('l10n_il_hr_payroll.work_entry_type_additional_day', raise_if_not_found=False)
        if not additional_type:
            self.skipTest('Additional-day payroll classification is not installed')
        worker = self._employee()
        thursday = self._attendances([(16, 30)], day=date(2026, 7, 9), employee=worker)
        friday = self._attendances([(7, 18)], day=date(2026, 7, 10), employee=worker)
        self._assert_hours(friday, 11, 0)
        for _ in range(2):
            thursday._update_overtime()
            self._assert_hours(thursday, 14, 5)
            self._assert_hours(friday, 11, 0)
            self.assertFalse(friday.segment_ids.filtered('is_overtime'))
            values = worker.version_id._mdl_get_normalized_work_entry_vals(
                self._utc(date(2026, 7, 10), 0), self._utc(date(2026, 7, 11), 0) - timedelta(microseconds=1))
            self.assertAlmostEqual(sum(value['duration'] for value in values
                                       if value.get('work_entry_type_id') == additional_type.id), 9)

    def test_configuration_rejects_ambiguous_periods_and_rounding_rates(self):
        for values in ({'expected_hours_from_contract': True},
                       {'mdl_shift_rounding_threshold_minutes': 60},
                       {'mdl_shift_rounding_threshold_minutes': -1}):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.rule.write(values)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.rule.copy({'quantity_period': 'day'})
        self.rule.mdl_shift_rounding_threshold_minutes = 40
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.rule.copy({'name': 'Ambiguous second rounded rate'})

    def test_management_shows_pending_rounded_hours_then_approved_hours(self):
        self.rule.mdl_shift_rounding_threshold_minutes = 40
        attendance = self._attendances([(7, 17 + 40 / 60)])
        lines = self._assert_hours(attendance, 10 + 40 / 60, 1.6667, 2)
        self.assertEqual(attendance.mdl_pending_overtime_hours, 2)
        self.assertEqual(attendance.validated_overtime_hours, 0)
        self.assertEqual(self.env['hr.attendance']._read_group(
            [('id', '=', attendance.id)], [], ['mdl_pending_overtime_hours:sum']), [(2.0,)])
        lines.manual_duration = 1.5
        self.assertEqual(attendance.mdl_pending_overtime_hours, 1.5)
        lines.manual_duration = 2
        attendance.action_approve_overtime()
        self.assertEqual(attendance.mdl_pending_overtime_hours, 0)
        self.assertEqual(attendance.validated_overtime_hours, 2)
        self.assertAlmostEqual(attendance.overtime_hours, 1.6667, places=4)
        attendance._update_overtime()
        self.assertEqual(attendance.mdl_pending_overtime_hours, 2)
        attendance.linked_overtime_ids.unlink()
        self.assertEqual(attendance.mdl_pending_overtime_hours, 0)

        field = attendance._fields['mdl_pending_overtime_hours']
        self.assertTrue(field.store and field.readonly)
        self.assertEqual(field.aggregator, 'sum')
        model = self.env['hr.attendance'].with_context(lang='en_US')
        arch = etree.fromstring(model.get_view(
            view_id=self.env.ref('hr_attendance.view_attendance_tree_management').id,
            view_type='list')['arch'])
        pending = arch.xpath("//field[@name='mdl_pending_overtime_hours']")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].get('sum'), 'Total Hours to Approve')
        self.assertEqual(pending[0].get('widget'), 'float_time')
        self.assertEqual(arch.xpath("//field[@name='overtime_hours']")[0].get('string'), 'Actual Overtime Hours')
        form = etree.fromstring(model.get_view(
            view_id=self.env.ref('hr_attendance.hr_attendance_view_form').id,
            view_type='form')['arch'])
        manual = form.xpath("//field[@name='linked_overtime_ids']/list/field[@name='manual_duration']")[0]
        self.assertEqual(manual.get('string'), 'Hours for Approval / Payment')
        self.assertIn(manual.get('column_invisible'), ('0', 'False', None))
