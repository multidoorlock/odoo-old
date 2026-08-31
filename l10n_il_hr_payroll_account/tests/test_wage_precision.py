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
            'mdl_net_daily_wage': 250.0,
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

    def test_net_rate_is_exact_and_gross_fields_are_not_reused(self):
        exact_field = self.env['hr.version']._fields['mdl_net_hourly_wage_exact']
        self.assertEqual(exact_field.column_type[0], 'numeric')
        self.assertEqual(
            Decimal(str(self.version.mdl_net_hourly_wage_exact)),
            Decimal('26.3157894737'),
        )
        self.assertEqual(self.version.mdl_net_hourly_wage, 26.32)
        self.assertEqual(self.version.mdl_hourly_wage_exact, 0.0)
        self.assertEqual(self.version.hourly_wage, 0.0)

    def test_target_uses_work100_hours_never_day_units(self):
        payslip = self._create_payslip()
        line = payslip.input_line_ids.filtered(
            lambda item: item.code == 'IL_NET_BASE_WAGE')
        self.assertEqual(len(line), 1)
        self.assertEqual(line.il_original_amount, 5000.0)

        attendance = payslip.worked_days_line_ids.filtered(
            lambda worked: worked.code == 'WORK100')
        attendance.number_of_days = 1.0
        payslip._compute_input_line_ids()
        line = payslip.input_line_ids.filtered(
            lambda item: item.code == 'IL_NET_BASE_WAGE')
        self.assertEqual(line.il_original_amount, 5000.0)

    def test_gross_up_reaches_requested_net_through_salary_rules(self):
        payslip = self._create_payslip()
        target_line = payslip.input_line_ids.filtered(
            lambda item: item.code == 'IL_NET_BASE_WAGE')
        target_line.amount = 0.0
        baseline = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()

        payslip._il_run_gross_up_engine()
        gross_amount = target_line.amount
        solved_net = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()
        self.assertGreater(gross_amount, target_line.il_original_amount)
        self.assertAlmostEqual(
            solved_net,
            baseline + target_line.il_original_amount,
            delta=payslip.currency_id.rounding,
        )

        line_values = payslip._get_payslip_lines()
        by_code = {line['code']: line['total'] for line in line_values}
        self.assertNotIn('BASIC', by_code)
        self.assertNotIn('IL_WAGE_ROUNDING', by_code)
        self.assertAlmostEqual(
            by_code['IL_NET_BASE_GROSSUP'], gross_amount, places=2)

        payslip.compute_sheet()
        stored_by_code = {
            line.code: line.total
            for line in payslip.line_ids
        }
        self.assertNotIn('BASIC', stored_by_code)
        self.assertNotIn('IL_WAGE_ROUNDING', stored_by_code)
        self.assertAlmostEqual(
            stored_by_code['IL_NET_BASE_GROSSUP'], gross_amount, places=2)
        self.assertAlmostEqual(
            stored_by_code['NET'],
            baseline + target_line.il_original_amount,
            delta=payslip.currency_id.rounding,
        )

    def test_overtime_is_paid_on_top_of_net_target(self):
        regular = self._create_payslip()
        regular._il_run_gross_up_engine()
        regular_line = regular.input_line_ids.filtered(
            lambda item: item.code == 'IL_NET_BASE_WAGE')

        overtime = self._create_payslip(overtime_hours=10.0)
        overtime._il_run_gross_up_engine()
        overtime_line = overtime.input_line_ids.filtered(
            lambda item: item.code == 'IL_NET_BASE_WAGE')
        self.assertEqual(overtime_line.amount, regular_line.amount)
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
                f'gross base={overtime_line.amount}, '
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
        target_line = payslip.input_line_ids.filtered(
            lambda item: item.code == 'IL_NET_BASE_WAGE')
        target_line.amount = 0.0
        baseline = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()
        payslip._il_run_gross_up_engine()
        solved_net = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()
        self.assertAlmostEqual(
            solved_net,
            baseline + target_line.il_original_amount,
            delta=payslip.currency_id.rounding,
        )

    def test_net_wage_validation(self):
        with self.assertRaisesRegex(ValidationError, 'שכר יומי נטו'):
            self.version.mdl_net_daily_wage = 0.0
        self.version.invalidate_recordset()

        with self.assertRaisesRegex(ValidationError, 'לעובד יומי בלבד'):
            self.version.write({
                'mdl_wage_type': 'mdl_monthly',
                'mdl_wage_rate_type': 'net',
            })
