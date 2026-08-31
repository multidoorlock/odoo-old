from datetime import date
from decimal import Decimal

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_wage_precision')
class TestWagePrecision(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
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
