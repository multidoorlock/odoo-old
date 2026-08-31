from datetime import date
from decimal import Decimal

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_wage_precision')
class TestWagePrecision(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.country_id = cls.env.ref('base.il')
        cls.calendar = cls.env['resource.calendar'].create({
            'name': '9.5 Hour Daily Wage Calendar',
            'company_id': cls.company.id,
            'tz': 'Asia/Jerusalem',
            'mdl_schedule_type': 'attendance',
            'mdl_schedule_frequency': 'daily_duration',
            'mdl_hours_per_day': 9.5,
        })
        daily_type = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il_daily')
        daily_structure = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_isr_daily')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Daily Wage Precision Employee',
            'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': cls.calendar.id,
            'structure_type_id': daily_type.id,
            'il_salary_structure_id': daily_structure.id,
            'mdl_wage_type': 'mdl_daily',
            'mdl_daily_wage': 250.0,
        })
        cls.version = cls.employee.version_id
        cls.version.date_version = date(2026, 1, 1)
        # Keep this test focused on the arithmetic.  Let Odoo settle the
        # computed payslip fields first, then replace worked days with one
        # explicit WORK100 line.
        cls.payslip = cls.env['hr.payslip'].create({
            'name': 'Daily Wage Precision Payslip',
            'employee_id': cls.employee.id,
            'company_id': cls.company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': cls.version.id,
            'struct_id': daily_structure.id,
            'edited': True,
        })
        cls.payslip.write({
            'version_id': cls.version.id,
            'struct_id': daily_structure.id,
            'worked_days_line_ids': [
                Command.clear(),
                Command.create({
                    'work_entry_type_id': cls.env.ref(
                        'hr_work_entry.work_entry_type_attendance').id,
                    'number_of_hours': 190.0,
                    # Deliberately unrelated to the hours: wage precision must
                    # never use number_of_days as an input.
                    'number_of_days': 999.0,
                }),
            ],
        })
        cls.worked_days = cls.payslip.worked_days_line_ids

    def test_exact_hourly_rate_is_numeric_with_ten_decimals(self):
        self.assertEqual(self.version.mdl_wage_rate_type, 'gross')
        field = self.env['hr.version']._fields['mdl_hourly_wage_exact']
        self.assertEqual(field.column_type[0], 'numeric')
        self.assertEqual(
            Decimal(str(self.version.mdl_hourly_wage_exact)),
            Decimal('26.3157894737'),
        )
        self.assertEqual(self.version.hourly_wage, 26.32)

    def test_hour_only_display_and_rounding_adjustment(self):
        self.assertEqual(self.payslip.version_id.mdl_wage_type, 'mdl_daily')
        self.assertEqual(self.payslip._il_basic_line_name(), 'שכר שעות')
        self.assertAlmostEqual(self.payslip._il_basic_amount(), 5000.80, places=2)
        self.assertEqual(
            self.payslip._il_currency_round_decimal(
                Decimal(str(self.payslip._il_wage_rounding_amount()))),
            Decimal('-0.80'),
        )
        self.assertTrue(self.payslip._il_has_wage_rounding())

        before = (
            self.payslip._il_basic_amount(),
            self.payslip._il_wage_rounding_amount(),
        )
        self.worked_days.number_of_days = 1.0
        after = (
            self.payslip._il_basic_amount(),
            self.payslip._il_wage_rounding_amount(),
        )
        self.assertEqual(before, after)

    def test_rounding_rule_is_present_in_all_israeli_structures(self):
        structures = self.env['hr.payroll.structure'].search([
            ('code', 'in', [
                'IL_ISR_MONTHLY', 'IL_PAL_MONTHLY',
                'IL_ISR_DAILY', 'IL_PAL_DAILY',
            ]),
        ])
        self.assertEqual(len(structures), 4)
        for structure in structures:
            rules = structure.rule_ids.filtered(
                lambda rule: rule.code == 'IL_WAGE_ROUNDING' and rule.active)
            self.assertEqual(len(rules), 1)


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_net_wage')
class TestNetDailyWageGrossUp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.country_id = cls.env.ref('base.il')
        cls.calendar = cls.env['resource.calendar'].create({
            'name': '9.5 Hour Net Daily Wage Calendar',
            'company_id': cls.company.id,
            'tz': 'Asia/Jerusalem',
            'mdl_schedule_type': 'attendance',
            'mdl_schedule_frequency': 'daily_duration',
            'mdl_hours_per_day': 9.5,
        })
        cls.daily_type = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il_daily')
        cls.daily_structure = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_isr_daily')
        # Exercise Odoo's ordinary percentage-based overtime path.  The copied
        # production database currently uses a fixed-rate rule and therefore
        # keeps the generic overtime work-entry type at a zero percentage.
        cls.env.ref(
            'hr_work_entry.work_entry_type_overtime').amount_rate = 1.5
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Net Daily Wage Employee',
            'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': cls.calendar.id,
            'structure_type_id': cls.daily_type.id,
            'il_salary_structure_id': cls.daily_structure.id,
            'mdl_wage_type': 'mdl_daily',
            'mdl_wage_rate_type': 'net',
            'mdl_daily_wage': 250.0,
            'il_tax_credit_points': 0.0,
            'il_pension_enabled': True,
            'il_pension_start_date': date(2026, 1, 1),
            'il_employee_pension_rate': 6.0,
            'il_employer_pension_rate': 6.5,
            'il_severance_rate': 8.33,
        })
        cls.version = cls.employee.version_id
        cls.version.date_version = date(2026, 1, 1)

    def _create_payslip(self, overtime_hours=0.0, structure=None):
        structure = structure or self.daily_structure
        if self.version.il_salary_structure_id != structure:
            self.version.il_salary_structure_id = structure
        payslip = self.env['hr.payslip'].create({
            'name': 'Net Daily Wage Payslip',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': self.version.id,
            'struct_id': structure.id,
            'edited': True,
        })
        commands = [
            Command.clear(),
            Command.create({
                'work_entry_type_id': self.env.ref(
                    'hr_work_entry.work_entry_type_attendance').id,
                'number_of_hours': 190.0,
                'number_of_days': 999.0,
            }),
        ]
        if overtime_hours:
            commands.append(Command.create({
                'work_entry_type_id': self.env.ref(
                    'hr_work_entry.work_entry_type_overtime').id,
                'number_of_hours': overtime_hours,
                'number_of_days': 123.0,
            }))
        payslip.write({
            'version_id': self.version.id,
            'struct_id': structure.id,
            'worked_days_line_ids': commands,
        })
        # The test creates all worked-day rows in the same transaction.  Odoo's
        # own payroll tests explicitly recompute this stored flag in that case;
        # normal payslip generation does it through the regular compute cycle.
        payslip.worked_days_line_ids._compute_is_paid()
        payslip._compute_input_line_ids()
        return payslip

    def test_daily_and_hourly_fields_are_shared_by_gross_and_net(self):
        exact_field = self.env['hr.version']._fields['mdl_hourly_wage_exact']
        self.assertEqual(exact_field.column_type[0], 'numeric')
        self.assertEqual(
            Decimal(str(self.version.mdl_hourly_wage_exact)),
            Decimal('26.3157894737'),
        )
        self.assertEqual(self.version.mdl_daily_wage, 250.0)
        self.assertEqual(self.version.hourly_wage, 26.32)
        self.assertNotIn('mdl_net_daily_wage', self.version._fields)
        self.assertNotIn('mdl_net_hourly_wage', self.version._fields)
        self.version.mdl_additional_day_wage = 950.0
        self.assertEqual(self.version.mdl_additional_day_hourly_wage, 100.0)

    def test_monthly_pay_cycle_is_enforced_and_weekend_rule_is_retired(self):
        self.version.write({'schedule_pay': 'weekly'})
        self.assertEqual(self.version.schedule_pay, 'monthly')
        self.assertFalse(self.env['hr.salary.rule'].with_context(
            active_test=False).search([
                ('code', '=', 'IL_WEEKEND_GROSS'),
                ('active', '=', True),
            ], limit=1))

    def test_rounding_recovers_when_stored_exact_rate_is_stale(self):
        self.version.mdl_hourly_wage_exact = 0.0
        payslip = self._create_payslip()
        self.assertEqual(payslip._il_exact_hourly_rate(), Decimal('26.3157894737'))
        self.assertAlmostEqual(payslip._il_wage_rounding_amount(), -0.80, places=2)
        self.assertTrue(payslip._il_has_wage_rounding())
        by_code = {
            line['code']: line['total']
            for line in payslip._get_payslip_lines()
        }
        self.assertAlmostEqual(by_code['IL_WAGE_ROUNDING'], -0.80, places=2)

    def test_target_uses_work100_hours_never_day_units(self):
        payslip = self._create_payslip()
        attendance = payslip.worked_days_line_ids.filtered(
            lambda worked: worked.code == 'WORK100')
        gross_amount = sum(attendance.mapped('amount'))
        self.assertEqual(payslip._il_net_attendance_target(), 5000.0)
        self.assertGreater(gross_amount, 5000.0)

        attendance.number_of_days = 1.0
        payslip._il_run_gross_up_engine()
        self.assertEqual(payslip._il_net_attendance_target(), 5000.0)
        self.assertEqual(sum(attendance.mapped('amount')), gross_amount)

    def test_gross_up_reaches_requested_net_through_salary_rules(self):
        payslip = self._create_payslip()
        attendance = payslip.worked_days_line_ids.filtered(
            lambda worked: worked.code == 'WORK100')
        payslip._il_set_regular_attendance_amount(0.0)
        baseline = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()

        payslip._il_run_gross_up_engine()
        gross_amount = sum(attendance.mapped('amount'))
        solved_net = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()
        target = payslip._il_net_attendance_target()
        display_target = payslip._il_net_attendance_display_target()
        self.assertGreater(gross_amount, target)
        self.assertAlmostEqual(
            solved_net,
            baseline + display_target,
            delta=payslip.currency_id.rounding,
        )

        line_values = payslip._get_payslip_lines()
        by_code = {line['code']: line['total'] for line in line_values}
        self.assertAlmostEqual(by_code['BASIC'], gross_amount, places=2)
        self.assertNotIn('IL_NET_BASE_GROSSUP', by_code)
        self.assertAlmostEqual(by_code['IL_WAGE_ROUNDING'], -0.80, places=2)

        payslip.compute_sheet()
        stored_by_code = {
            line.code: line.total
            for line in payslip.line_ids
        }
        self.assertAlmostEqual(stored_by_code['BASIC'], gross_amount, places=2)
        self.assertNotIn('IL_NET_BASE_GROSSUP', stored_by_code)
        self.assertAlmostEqual(
            stored_by_code['IL_WAGE_ROUNDING'], -0.80, places=2)
        self.assertAlmostEqual(
            stored_by_code['NET'],
            baseline + display_target,
            delta=payslip.currency_id.rounding,
        )

    def test_net_additional_day_is_grossed_up_without_salary_input(self):
        monthly_type = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        monthly_structure = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il')
        employee = self.env['hr.employee'].create({
            'name': 'Net Additional Day Employee',
            'company_id': self.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': self.calendar.id,
            'structure_type_id': monthly_type.id,
            'il_salary_structure_id': monthly_structure.id,
            'mdl_wage_type': 'mdl_monthly',
            'wage': 10000.0,
            'mdl_additional_day_wage': 500.0,
            'mdl_wage_rate_type': 'net',
            'il_tax_credit_points': 0.0,
        })
        version = employee.version_id
        version.date_version = date(2026, 1, 1)
        self.assertEqual(version.mdl_wage_rate_type, 'net')
        self.assertAlmostEqual(
            version.mdl_additional_day_hourly_wage, 500.0 / 9.5, places=2)
        payslip = self.env['hr.payslip'].create({
            'name': 'Net Additional Day Payslip',
            'employee_id': employee.id,
            'company_id': self.company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': version.id,
            'struct_id': monthly_structure.id,
            'edited': True,
        })
        payslip.write({
            'version_id': version.id,
            'struct_id': monthly_structure.id,
            'worked_days_line_ids': [
                Command.clear(),
                Command.create({
                    'work_entry_type_id': self.env.ref(
                        'l10n_il_hr_payroll.work_entry_type_additional_day').id,
                    'number_of_hours': 19.0,
                    'number_of_days': 2.0,
                }),
            ],
        })
        payslip.worked_days_line_ids._compute_is_paid()
        payslip._compute_input_line_ids()
        additional = payslip.worked_days_line_ids.filtered(
            lambda worked: worked.code == 'ADDITIONAL_DAY')
        additional_gross = sum(additional.mapped('amount'))
        self.assertGreater(additional_gross, 1000.0)
        self.assertFalse(payslip.input_line_ids.filtered(
            lambda line: line.code == 'IL_NET_ADDITIONAL_DAY'))

        payslip._il_set_worked_days_amount('ADDITIONAL_DAY', 0.0)
        baseline_net = payslip._il_compute_net_total()
        payslip._il_gross_up_additional_day()
        by_code = {
            line['code']: line['total']
            for line in payslip._get_payslip_lines()
        }
        self.assertAlmostEqual(
            by_code['IL_ADDITIONAL_DAY_GROSS'],
            sum(additional.mapped('amount')),
            places=2,
        )
        self.assertNotIn('IL_NET_ADDITIONAL_DAY_GROSSUP', by_code)
        self.assertAlmostEqual(
            by_code['NET'], baseline_net + 1000.0,
            delta=payslip.currency_id.rounding,
        )

    def test_overtime_is_paid_on_top_of_net_target(self):
        regular = self._create_payslip()
        regular._il_run_gross_up_engine()
        regular_amount = sum(regular.worked_days_line_ids.filtered(
            lambda item: item.code == 'WORK100').mapped('amount'))

        overtime = self._create_payslip(overtime_hours=10.0)
        overtime._il_run_gross_up_engine()
        overtime_amount = sum(overtime.worked_days_line_ids.filtered(
            lambda item: item.code == 'WORK100').mapped('amount'))
        self.assertEqual(overtime_amount, regular_amount)
        overtime_worked_days = overtime.worked_days_line_ids.filtered(
            lambda item: item.code == 'OVERTIME')
        self.assertGreater(
            overtime._il_overtime_amount(),
            0.0,
            msg=(
                f'overtime rows={len(overtime_worked_days)}, '
                f'hours={overtime_worked_days.mapped("number_of_hours")}, '
                f'paid={overtime_worked_days.mapped("is_paid")}, '
                f'rates={overtime_worked_days.mapped("work_entry_type_id.amount_rate")}, '
                f'gross base={overtime_amount}, '
                f'gross hourly={overtime._il_net_base_gross_hourly_rate()}'
            ),
        )
        self.assertGreater(
            overtime._il_compute_net_total(),
            regular._il_compute_net_total(),
        )

    def test_fixed_overtime_is_paid_on_top_of_net_target(self):
        overtime_type = self.env.ref(
            'hr_work_entry.work_entry_type_overtime')
        self.env['hr.attendance.overtime.line'].create({
            'employee_id': self.employee.id,
            'date': date(2026, 1, 15),
            'status': 'approved',
            'duration': 10.0,
            'manual_duration': 10.0,
            'amount_rate': 0.0,
            'mdl_fixed_hourly_amount': 50.0,
            'work_entry_type_overtime_id': overtime_type.id,
        })
        overtime = self._create_payslip(overtime_hours=10.0)
        overtime._il_run_gross_up_engine()
        self.assertAlmostEqual(overtime._il_overtime_amount(), 500.0, places=2)

    def test_palestinian_daily_structure_uses_same_net_target_contract(self):
        palestinian_structure = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_daily')
        payslip = self._create_payslip(structure=palestinian_structure)
        self.assertEqual(payslip._il_worker_profile(), 'palestinian')
        payslip._il_set_regular_attendance_amount(0.0)
        baseline = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()
        payslip._il_run_gross_up_engine()
        solved_net = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()
        self.assertAlmostEqual(
            solved_net,
            baseline + payslip._il_net_attendance_display_target(),
            delta=payslip.currency_id.rounding,
        )

    def test_all_four_israeli_structures_compute_complete_payslip(self):
        structure_xmlids = (
            'hr_payroll_structure_il',
            'hr_payroll_structure_il_pal_monthly',
            'hr_payroll_structure_il_isr_daily',
            'hr_payroll_structure_il_pal_daily',
        )
        attendance_type = self.env.ref('hr_work_entry.work_entry_type_attendance')
        for xmlid in structure_xmlids:
            structure = self.env.ref(f'l10n_il_hr_payroll_account.{xmlid}')
            daily = structure.type_id.wage_type == 'hourly'
            expected_profile = (
                'palestinian' if structure.code.startswith('IL_PAL_') else 'israeli')
            with self.subTest(structure=structure.code):
                employee_values = {
                    'name': f'Structure Matrix {structure.code}',
                    'company_id': self.company.id,
                    'contract_date_start': date(2026, 1, 1),
                    'date_version': date(2026, 1, 1),
                    'resource_calendar_id': self.calendar.id,
                    'structure_type_id': structure.type_id.id,
                    'il_salary_structure_id': structure.id,
                    'mdl_wage_type': 'mdl_daily' if daily else 'mdl_monthly',
                    'il_tax_credit_points': 0.0,
                }
                if daily:
                    employee_values.update({
                        'mdl_daily_wage': 250.0,
                        'mdl_wage_rate_type': 'gross',
                    })
                else:
                    employee_values['wage'] = 10000.0
                employee = self.env['hr.employee'].create(employee_values)
                payslip = self.env['hr.payslip'].create({
                    'name': f'Structure Matrix {structure.code}',
                    'employee_id': employee.id,
                    'company_id': self.company.id,
                    'date_from': date(2026, 1, 1),
                    'date_to': date(2026, 1, 31),
                    'version_id': employee.version_id.id,
                    'struct_id': structure.id,
                    'edited': True,
                    'worked_days_line_ids': [Command.create({
                        'work_entry_type_id': attendance_type.id,
                        'number_of_hours': 19.0,
                        'number_of_days': 2.0,
                    })],
                })
                payslip.worked_days_line_ids._compute_is_paid()
                payslip._compute_input_line_ids()
                by_code = {
                    line['code']: line['total']
                    for line in payslip._get_payslip_lines()
                }
                self.assertEqual(payslip._il_worker_profile(), expected_profile)
                self.assertIn('GROSS', by_code)
                self.assertIn('NET', by_code)
                self.assertIn('IL_NET_TO_PAY', by_code)
                if daily:
                    self.assertIn('IL_WAGE_ROUNDING', by_code)

    def test_daily_wage_validation_and_shared_rate_type(self):
        with self.assertRaisesRegex(ValidationError, 'שכר יומי'):
            self.version.mdl_daily_wage = 0.0
        self.version.invalidate_recordset()

        self.version.write({
            'mdl_wage_type': 'mdl_monthly',
            'mdl_wage_rate_type': 'net',
        })
        self.assertEqual(self.version.mdl_wage_rate_type, 'net')
        self.assertEqual(self.version.schedule_pay, 'monthly')
