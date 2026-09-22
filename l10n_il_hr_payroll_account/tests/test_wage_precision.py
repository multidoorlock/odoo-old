from datetime import date, datetime, timedelta
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

    def test_attendance_wage_is_rounded_on_worked_days(self):
        self.assertEqual(self.payslip.version_id.mdl_wage_type, 'mdl_daily')
        self.assertEqual(self.payslip._il_basic_line_name(), 'שכר בסיס')
        self.assertAlmostEqual(self.worked_days.amount, 5000.0, places=2)
        self.assertAlmostEqual(self.payslip._il_basic_amount(), 5000.0, places=2)
        self.assertFalse(self.payslip._il_has_wage_rounding())

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

    def test_gross_additional_day_uses_configured_rate_and_actual_hours(self):
        self.version.mdl_additional_day_wage = 475.0
        entry_type = self.env['hr.work.entry.type'].create({
            'name': 'Configured Extra Day',
            'code': 'CONFIGURED_EXTRA_DAY',
            'is_extra_hours': True,
            'round_days': 'NO',
        })
        self.company.mdl_additional_day_work_entry_type_id = entry_type
        self.payslip.write({
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': entry_type.id,
                'number_of_hours': 4.75,
                'number_of_days': 1.0,
            })],
        })
        additional = self.payslip.worked_days_line_ids.filtered(
            lambda line: line.work_entry_type_id == entry_type)
        additional._compute_is_paid()
        self.assertAlmostEqual(additional.amount, 237.50, places=2)
        self.assertAlmostEqual(
            self.payslip._il_additional_day_amount(), 237.50, places=2)

    def test_rounding_rules_are_retired_in_all_israeli_structures(self):
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
            self.assertFalse(rules)
            final_rounding_rules = structure.rule_ids.filtered(
                lambda rule: rule.code == 'IL_PAYSLIP_ROUNDING' and rule.active)
            self.assertFalse(final_rounding_rules)
            self.assertFalse(structure.rule_ids.filtered(
                lambda rule: rule.code in ('IL_PAYMENTS', 'IL_NET_TO_PAY')
                and rule.active))
            self.assertFalse(structure.rule_ids.filtered(
                lambda rule: rule.code == 'IL_ADJUSTMENT_NET_DIRECT' and rule.active))

    def test_all_four_structures_have_the_same_active_rule_codes(self):
        structures = self.env['hr.payroll.structure'].search([
            ('code', 'in', [
                'IL_ISR_MONTHLY', 'IL_PAL_MONTHLY',
                'IL_ISR_DAILY', 'IL_PAL_DAILY',
            ]),
        ]).sorted('code')
        expected = set(structures[0].rule_ids.filtered('active').mapped('code'))
        self.assertTrue(expected)
        for structure in structures[1:]:
            self.assertEqual(
                set(structure.rule_ids.filtered('active').mapped('code')),
                expected,
                structure.code,
            )
        self.assertIn('IL_ISR_INCOME_TAX', expected)
        self.assertIn('IL_PAL_INCOME_TAX', expected)
        self.assertFalse(any(code.startswith('IL_FOR_') for code in expected))
        self.assertFalse({
            'ASSIG_SALARY', 'ATTACH_SALARY', 'CHILD_SUPPORT',
            'DEDUCTION', 'REIMBURSEMENT',
        } & expected)

    def test_existing_structure_and_rule_are_adopted_when_xmlids_are_missing(self):
        module = 'l10n_il_hr_payroll_account'
        structure = self.env.ref(
            f'{module}.hr_payroll_structure_il')
        basic = self.env.ref(f'{module}.hr_salary_rule_il_basic')
        xml_names = (
            'hr_payroll_structure_il',
            'hr_salary_rule_il_basic',
        )
        self.env['ir.model.data'].search([
            ('module', '=', module), ('name', 'in', xml_names),
        ]).unlink()

        self.env['hr.payroll.structure']._il_bind_existing_structure_xmlids()

        self.assertEqual(
            self.env.ref(f'{module}.hr_payroll_structure_il'), structure)
        self.assertEqual(
            self.env.ref(f'{module}.hr_salary_rule_il_basic'), basic)

    def test_structure_sync_replaces_changed_and_unneeded_rules(self):
        template = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il')
        target = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_daily')
        template_basic = template.rule_ids.filtered(
            lambda rule: rule.code == 'BASIC')
        target_basic = target.rule_ids.filtered(
            lambda rule: rule.code == 'BASIC')
        target_basic.write({
            'name': 'Wrong rule',
            'amount_python_compute': 'result = 123456',
        })
        obsolete = self.env['hr.salary.rule'].create({
            'name': 'Obsolete custom rule',
            'code': 'IL_OBSOLETE_CUSTOM',
            'sequence': 999,
            'category_id': self.env.ref('hr_payroll.BASIC').id,
            'struct_id': target.id,
            'condition_select': 'none',
            'amount_select': 'fix',
            'amount_fix': 1.0,
        })

        self.env['hr.payroll.structure']._il_sync_structures_and_rules()

        self.assertFalse(obsolete.exists())
        target_basic = target.rule_ids.filtered(lambda rule: rule.code == 'BASIC')
        self.assertEqual(len(target_basic), 1)
        self.assertEqual(target_basic.name, template_basic.name)
        self.assertEqual(
            target_basic.amount_python_compute,
            template_basic.amount_python_compute,
        )

    def test_palestinian_insurance_matches_supplied_payslip_rates(self):
        self.assertEqual(
            self.payslip._rule_parameter('IL_TAX_BRACKET_3_LIMIT'), 19000)
        self.assertEqual(
            self.payslip._rule_parameter('IL_TAX_BRACKET_4_LIMIT'), 25100)
        self.assertAlmostEqual(
            self.payslip._il_ni_amount(
                6716.46, 'PAL',
                'IL_PAL_NI_EE_REDUCED_RATE',
                'IL_PAL_NI_EE_FULL_RATE'),
            4.701522,
            places=6,
        )
        self.assertAlmostEqual(
            self.payslip._il_ni_amount(
                10975.59, 'PAL',
                'IL_PAL_NI_EE_REDUCED_RATE',
                'IL_PAL_NI_EE_FULL_RATE'),
            25.354899,
            places=6,
        )

    def test_israeli_insurance_profile_rates_and_exemptions(self):
        self.version.write({
            'il_ni_full_rate_from_first_shekel': False,
            'il_national_insurance_exempt': False,
            'il_health_insurance_exempt': False,
        })
        self.assertAlmostEqual(self.payslip._il_ni_amount(
            10807.85, 'ISR', 'IL_ISR_NI_EE_REDUCED_RATE',
            'IL_ISR_NI_EE_FULL_RATE'), 297.45, places=2)
        self.assertAlmostEqual(self.payslip._il_ni_amount(
            10807.85, 'ISR', 'IL_ISR_HEALTH_REDUCED_RATE',
            'IL_ISR_HEALTH_FULL_RATE'), 409.327645, places=6)
        self.version.il_ni_full_rate_from_first_shekel = True
        self.assertAlmostEqual(self.payslip._il_ni_amount(
            9793.0, 'ISR', 'IL_ISR_NI_EE_REDUCED_RATE',
            'IL_ISR_NI_EE_FULL_RATE'), 685.51, places=2)
        self.assertAlmostEqual(self.payslip._il_ni_amount(
            9793.0, 'ISR', 'IL_ISR_HEALTH_REDUCED_RATE',
            'IL_ISR_HEALTH_FULL_RATE'), 506.30, places=2)

        self.version.write({
            'il_national_insurance_exempt': True,
            'il_health_insurance_exempt': True,
        })
        self.assertEqual(self.payslip._il_ni_amount(
            9793.0, 'ISR', 'IL_ISR_NI_EE_REDUCED_RATE',
            'IL_ISR_NI_EE_FULL_RATE'), 0.0)
        self.assertEqual(self.payslip._il_ni_amount(
            9793.0, 'ISR', 'IL_ISR_HEALTH_REDUCED_RATE',
            'IL_ISR_HEALTH_FULL_RATE'), 0.0)

    def test_taxable_benefit_changes_bases_without_changing_gross(self):
        input_type = self.env.ref(
            'l10n_il_hr_payroll_account.input_type_il_adj_bonus')
        attachment = self.env['hr.salary.attachment'].create({
            'employee_ids': [self.employee.id],
            'description': 'Non-cash taxable benefit',
            'other_input_type_id': input_type.id,
            'duration_type': 'unlimited',
            'date_start': date(2026, 1, 1),
            'monthly_amount': 785.53,
            'il_effect_type': 'taxable_benefit',
        })
        self.assertEqual(attachment.il_effect_type, 'taxable_benefit')
        self.payslip._compute_input_line_ids()
        line = self.payslip.input_line_ids.filtered(
            lambda item: item.il_salary_attachment_id == attachment)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.il_effect_type, 'taxable_benefit')
        by_code = {
            item['code']: item['total']
            for item in self.payslip._get_payslip_lines()
        }
        self.assertAlmostEqual(by_code['GROSS'], 5000.0, places=2)
        self.assertAlmostEqual(by_code['IL_TAX_BASE'], 5785.53, places=2)
        self.assertAlmostEqual(by_code['IL_NI_BASE'], 5785.53, places=2)

    def test_employee_insured_wage_caps_pension_and_severance_base(self):
        self.version.write({
            'il_pension_enabled': True,
            'il_employee_pension_rate': 6.0,
            'il_pension_insured_wage': 9430.0,
        })
        self.assertEqual(self.payslip._il_pension_base(10807.85), 9430.0)
        self.assertAlmostEqual(
            self.payslip._il_pension_base(10807.85)
            * self.version.il_employee_pension_rate / 100.0,
            565.80,
            places=2,
        )

    def test_active_form_101_drives_rules_and_reproduces_gross_payslip(self):
        """Source-payslip amounts: gross 10,807.85 and net 9,000.00.

        The employee is deliberately configured as gross-paid.  The 2.25
        points come from the active Form 101, not from the legacy manual
        field on the employee version.  The isolated fixture uses January so
        no unavailable preceding-year-to-date payslips distort cumulative
        withholding.
        """
        structure = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il')
        employee = self.env['hr.employee'].create({
            'name': 'Form 101 Gross Document Sample',
            'company_id': self.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': self.calendar.id,
            'structure_type_id': structure.type_id.id,
            'il_salary_structure_id': structure.id,
            'mdl_wage_type': 'mdl_monthly',
            'mdl_wage_rate_type': 'gross',
            'wage': 10807.85,
            # Proves that an applicable active form supersedes this field.
            'il_tax_credit_points': 99.0,
            'il_monthly_tax_credit_adjustment': -0.23,
            'il_pension_enabled': True,
            'il_employee_pension_rate': 6.0,
            'il_pension_insured_wage': 9430.0,
        })
        form = self.env['hr.employee.form.101'].create({
            'employee_id': employee.id,
            'tax_year': '2026',
            'state': 'active',
            'employer_name': 'Document Employer',
            'employer_address': 'Test Address',
            'employer_phone': '03-5555555',
            'employer_withholding_file': '935000000',
            'has_israeli_id': 'yes',
            'identification_id': '326356482',
            'first_name': 'Gross',
            'last_name': 'Sample',
            'birthday': date(1990, 1, 1),
            'private_street': 'Test Street',
            'private_house_number': '1',
            'private_city': 'Tel Aviv',
            'mobile_phone': '050-5555555',
            'sex': 'male',
            'marital': 'married',
            'spouse_has_israeli_id': 'yes',
            'spouse_identification_id': '123456789',
            'spouse_first_name': 'Spouse',
            'spouse_last_name': 'Sample',
            'spouse_birthdate': date(1991, 1, 1),
            'spouse_has_income': 'yes',
            'is_israeli_resident': 'yes',
            'relief_resident': True,
            'employer_income_main_type': 'monthly',
            'employment_start_date': date(2026, 1, 1),
            'has_other_income': 'no',
            'declaration_confirmed': True,
            'declaration_date': date(2026, 1, 1),
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'Form 101 Gross Document Sample',
            'employee_id': employee.id,
            'company_id': self.company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': employee.version_id.id,
            'struct_id': structure.id,
            'edited': True,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': self.env.ref(
                    'hr_work_entry.work_entry_type_attendance').id,
                'number_of_hours': 190.0,
                'number_of_days': 22.0,
            })],
        })
        payslip.worked_days_line_ids._compute_is_paid()
        by_code = {
            line['code']: line['total']
            for line in payslip._get_payslip_lines()
        }
        self.assertEqual(payslip._il_active_form_101(), form)
        self.assertEqual(
            form._il_payroll_credit_points(date(2026, 1, 1)), 2.25)
        self.assertAlmostEqual(by_code['BASIC'], 10807.85, places=2)
        self.assertAlmostEqual(by_code['GROSS'], 10807.85, places=2)
        self.assertLess(by_code['IL_ISR_INCOME_TAX'], 0.0)
        self.assertLess(by_code['IL_ISR_NI_EE'], 0.0)
        self.assertLess(by_code['IL_ISR_HEALTH_EE'], 0.0)
        self.assertAlmostEqual(by_code['IL_ISR_PENSION_EE'], -565.80, places=2)
        self.assertAlmostEqual(by_code['NET'], 9000.00, places=2)

    def test_sample_payslips_reproduce_supplied_gross_and_net(self):
        attendance_type = self.env.ref('hr_work_entry.work_entry_type_attendance')
        samples = (
            {
                'name': 'Israeli document sample',
                'structure': self.env.ref(
                    'l10n_il_hr_payroll_account.hr_payroll_structure_il'),
                'net': 9000.0,
                'gross': 10807.85,
                'credit_points': 2.25,
                'tax_credit_adjustment': -0.23,
                'pension': True,
                'insured_wage': 9430.0,
            },
            {
                'name': 'Palestinian document sample',
                'structure': self.env.ref(
                    'l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_monthly'),
                'net': 6250.0,
                'gross': 6716.46,
                'credit_points': 1.0,
                'tax_credit_adjustment': -32.11,
                'pension': False,
                'insured_wage': 0.0,
            },
        )
        for sample in samples:
            with self.subTest(sample=sample['name']):
                structure = sample['structure']
                employee = self.env['hr.employee'].create({
                    'name': sample['name'],
                    'company_id': self.company.id,
                    'contract_date_start': date(2026, 1, 1),
                    'date_version': date(2026, 1, 1),
                    'resource_calendar_id': self.calendar.id,
                    'structure_type_id': structure.type_id.id,
                    'il_salary_structure_id': structure.id,
                    'mdl_wage_type': 'mdl_monthly',
                    'mdl_wage_rate_type': 'net',
                    'wage': sample['net'],
                    'il_tax_credit_points': sample['credit_points'],
                    'il_monthly_tax_credit_adjustment': sample[
                        'tax_credit_adjustment'],
                    'il_pension_enabled': sample['pension'],
                    'il_employee_pension_rate': 6.0 if sample['pension'] else 0.0,
                    'il_pension_insured_wage': sample['insured_wage'],
                })
                payslip = self.env['hr.payslip'].create({
                    'name': sample['name'],
                    'employee_id': employee.id,
                    'company_id': self.company.id,
                    'date_from': date(2026, 1, 1),
                    'date_to': date(2026, 1, 31),
                    'version_id': employee.version_id.id,
                    'struct_id': structure.id,
                    'edited': True,
                    'worked_days_line_ids': [Command.create({
                        'work_entry_type_id': attendance_type.id,
                        'number_of_hours': 190.0,
                        'number_of_days': 22.0,
                    })],
                })
                payslip.worked_days_line_ids._compute_is_paid()
                payslip._compute_input_line_ids()
                payslip._il_run_gross_up_engine()
                by_code = {
                    line['code']: line['total']
                    for line in payslip._get_payslip_lines()
                }
                self.assertAlmostEqual(by_code['BASIC'], sample['gross'], places=2)
                self.assertAlmostEqual(by_code['GROSS'], sample['gross'], places=2)
                self.assertAlmostEqual(by_code['NET'], sample['net'], places=2)

    def test_redundant_base_is_hidden_only_when_equal_to_gross(self):
        gross = self.payslip.gross_wage
        rule = self.env.ref(
            'l10n_il_hr_payroll_account.hr_salary_rule_il_tax_base')
        line = self.env['hr.payslip.line'].create({
            'slip_id': self.payslip.id,
            'name': 'בסיס מס הכנסה',
            'code': 'IL_TAX_BASE',
            'salary_rule_id': rule.id,
            'category_id': rule.category_id.id,
            'amount': gross,
            'total': gross,
            'quantity': 1.0,
            'rate': 100.0,
        })
        self.assertTrue(line.il_hide_redundant_base)
        line.write({'amount': gross + 100.0, 'total': gross + 100.0})
        line.flush_recordset(['amount', 'total', 'il_hide_redundant_base'])
        line.invalidate_recordset(['total', 'il_hide_redundant_base'])
        self.assertFalse(line.il_hide_redundant_base)


    def test_compute_sheet_refreshes_redundant_base_visibility(self):
        self.payslip.compute_sheet()
        base_lines = self.payslip.line_ids.filtered(
            lambda line: line.code in {
                'IL_TAX_BASE', 'IL_NI_BASE', 'IL_PENSION_BASE',
                'IL_SEVERANCE_BASE', 'IL_STUDY_FUND_BASE',
                'IL_PAL_EQUALIZATION_BASE',
            }
        )
        for line in base_lines:
            expected = self.payslip.currency_id.compare_amounts(
                line.total, self.payslip.gross_wage
            ) == 0
            self.assertEqual(line.il_hide_redundant_base, expected)

    def test_final_payslip_net_is_not_rounded(self):
        self.assertEqual(self.payslip._il_payslip_rounding_amount(1000.01), 0.0)
        self.assertEqual(self.payslip._il_payslip_rounding_amount(1000.50), 0.0)
        self.assertFalse(self.payslip._il_has_payslip_rounding(1000.00))
        self.assertFalse(self.payslip._il_has_payslip_rounding(1000.01))

        by_code = {
            line['code']: line['total']
            for line in self.payslip._get_payslip_lines()
        }
        self.assertNotIn('IL_PAYSLIP_ROUNDING', by_code)
        self.assertNotIn('IL_NET_BEFORE_DIRECT_ADJUSTMENTS', by_code)

    def test_zero_tax_base_never_creates_income_tax_or_refund(self):
        self.assertEqual(
            self.payslip._il_income_tax(0.0, 'IL_ISR_INCOME_TAX'), 0.0)
        self.assertEqual(
            self.payslip._il_income_tax(-100.0, 'IL_ISR_INCOME_TAX'), 0.0)

    def test_israeli_payroll_version_gets_a_real_contract_start(self):
        employee = self.env['hr.employee'].create({
            'name': 'Missing Contract Start Employee',
            'company_id': self.company.id,
            'date_version': date(2026, 6, 1),
            'resource_calendar_id': self.calendar.id,
            'structure_type_id': self.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_type_il').id,
        })
        self.assertEqual(employee.version_id.date_start, date(2026, 6, 1))
        self.assertEqual(
            employee.version_id.contract_date_start, date(2026, 6, 1))


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_source_gross')
class TestSourcePayslipGrossScenarios(TransactionCase):
    """Eight gross checks taken from the supplied 2026 payslip PDFs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.country_id = cls.env.ref('base.il')
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Source Payslip Gross Test Calendar',
            'company_id': cls.company.id,
            'tz': 'Asia/Jerusalem',
            'mdl_schedule_type': 'attendance',
            'mdl_schedule_frequency': 'daily_duration',
            'mdl_hours_per_day': 9.5,
        })
        cls.attendance_type = cls.env.ref(
            'hr_work_entry.work_entry_type_attendance')

    def _assert_source_gross(self, structure_xmlid, gross, source, daily=False):
        structure = self.env.ref(structure_xmlid)
        employee_values = {
            'name': source,
            'company_id': self.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': self.calendar.id,
            'structure_type_id': structure.type_id.id,
            'il_salary_structure_id': structure.id,
            'mdl_wage_rate_type': 'gross',
            'il_tax_credit_points': 2.25,
            'il_pension_enabled': False,
        }
        worked_hours = 190.0
        if daily:
            # A 950 daily wage on this 9.5-hour calendar is exactly 100/hour;
            # varying hours lets the test exercise the daily rule at cent
            # precision without pre-rounding the source gross into a wage.
            employee_values.update({
                'mdl_wage_type': 'mdl_daily',
                'mdl_daily_wage': 950.0,
            })
            worked_hours = gross / 100.0
        else:
            employee_values.update({
                'mdl_wage_type': 'mdl_monthly',
                'wage': gross,
            })
        employee = self.env['hr.employee'].create(employee_values)
        payslip = self.env['hr.payslip'].create({
            'name': source,
            'employee_id': employee.id,
            'company_id': self.company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': employee.version_id.id,
            'struct_id': structure.id,
            'edited': True,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': self.attendance_type.id,
                'number_of_hours': worked_hours,
                'number_of_days': worked_hours / 9.5,
            })],
        })
        payslip.worked_days_line_ids._compute_is_paid()
        by_code = {
            line['code']: line['total']
            for line in payslip._get_payslip_lines()
        }
        self.assertAlmostEqual(by_code['GROSS'], gross, places=2, msg=source)

    def test_israeli_monthly_multi_april_page_3(self):
        self._assert_source_gross(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il',
            10807.85,
            'Multi April 2026 page 3',
        )

    def test_israeli_monthly_multi_april_page_4(self):
        self._assert_source_gross(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il',
            10513.28,
            'Multi April 2026 page 4',
        )

    def test_israeli_daily_multi_april_page_14(self):
        self._assert_source_gross(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_isr_daily',
            1045.20,
            'Multi April 2026 page 14',
            daily=True,
        )

    def test_israeli_daily_multi_april_page_16(self):
        self._assert_source_gross(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_isr_daily',
            4178.00,
            'Multi April 2026 page 16',
            daily=True,
        )

    def test_palestinian_monthly_autonomy_february_page_1(self):
        self._assert_source_gross(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_monthly',
            6716.46,
            'Autonomy February 2026 page 1',
        )

    def test_palestinian_monthly_autonomy_february_page_2(self):
        self._assert_source_gross(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_monthly',
            10975.59,
            'Autonomy February 2026 page 2',
        )

    def test_palestinian_daily_autonomy_february_page_23(self):
        self._assert_source_gross(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_daily',
            3119.67,
            'Autonomy February 2026 page 23',
            daily=True,
        )

    def test_palestinian_daily_autonomy_march_page_24(self):
        self._assert_source_gross(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_daily',
            3071.93,
            'Autonomy March 2026 page 24',
            daily=True,
        )


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
        self.assertGreater(
            payslip.worked_days_line_ids.filtered(
                lambda line: line.code == 'WORK100').amount,
            5000.0)
        self.assertEqual(payslip._il_net_attendance_target(), 5000.0)
        self.assertFalse(payslip._il_has_wage_rounding())
        by_code = {
            line['code']: line['total']
            for line in payslip._get_payslip_lines()
        }
        self.assertNotIn('IL_WAGE_ROUNDING', by_code)
        self.assertGreater(by_code['BASIC'], 5000.0)

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
            il_solving_net_base_wage=True,
            il_skip_wage_rounding=True)._il_compute_net_total()

        payslip._il_run_gross_up_engine()
        gross_amount = sum(attendance.mapped('amount'))
        solved_net = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()
        target = payslip._il_net_attendance_target()
        self.assertGreater(gross_amount, target)
        self.assertAlmostEqual(
            solved_net,
            baseline + target,
            delta=payslip.currency_id.rounding / 2,
        )
        self.assertEqual(
            payslip._il_currency_round_decimal(Decimal(str(solved_net))),
            payslip._il_currency_round_decimal(
                Decimal(str(baseline + target))),
        )

        line_values = payslip._get_payslip_lines()
        by_code = {line['code']: line['total'] for line in line_values}
        self.assertAlmostEqual(by_code['BASIC'], gross_amount, places=2)
        self.assertNotIn('IL_NET_BASE_GROSSUP', by_code)
        self.assertNotIn('IL_WAGE_ROUNDING', by_code)

        payslip.compute_sheet()
        stored_by_code = {
            line.code: line.total
            for line in payslip.line_ids
        }
        self.assertAlmostEqual(stored_by_code['BASIC'], gross_amount, places=2)
        self.assertNotIn('IL_NET_BASE_GROSSUP', stored_by_code)
        self.assertNotIn('IL_WAGE_ROUNDING', stored_by_code)
        self.assertAlmostEqual(
            stored_by_code['NET'],
            baseline + target,
            delta=payslip.currency_id.rounding / 2,
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

    def test_friday_overtime_split_is_paid_as_one_fixed_additional_day(self):
        monthly_type = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        monthly_structure = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il')
        fixed_calendar = self.env['resource.calendar'].create({
            'name': 'Monday Only Additional Day Calendar',
            'company_id': self.company.id,
            'tz': 'UTC',
            'mdl_schedule_type': 'attendance',
            'mdl_schedule_frequency': 'fixed_intervals',
            'attendance_ids': [Command.create({
                'name': 'Monday',
                'dayofweek': '0',
                'day_period': 'morning',
                'hour_from': 6.5,
                'hour_to': 16.0,
            })],
        })
        employee = self.env['hr.employee'].create({
            'name': 'Fixed Additional Day Employee',
            'company_id': self.company.id,
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': fixed_calendar.id,
            'structure_type_id': monthly_type.id,
            'il_salary_structure_id': monthly_structure.id,
            'mdl_wage_type': 'mdl_monthly',
            'mdl_wage_rate_type': 'gross',
            'wage': 10000.0,
            'mdl_additional_day_wage': 400.0,
        })
        version = employee.version_id
        version.write({
            'work_entry_source': 'attendance',
            'ruleset_id': self.env['hr.attendance.overtime.ruleset'].create({
                'name': 'Friday 6 plus 3',
                'company_id': self.company.id,
            }).id,
        })
        attendance = self.env['hr.attendance'].create({
            'employee_id': employee.id,
            'check_in': datetime(2026, 1, 9, 6, 30),
            'check_out': datetime(2026, 1, 9, 15, 30),
        })
        overtime_type = self.env.ref('hr_work_entry.work_entry_type_overtime')
        for duration in (6.0, 3.0):
            self.env['hr.attendance.overtime.line'].create({
                'employee_id': employee.id,
                'date': date(2026, 1, 9),
                'status': 'approved',
                'duration': duration,
                'manual_duration': duration,
                'time_start': attendance.check_in,
                'time_stop': attendance.check_out,
                'work_entry_type_overtime_id': overtime_type.id,
            })
        entries = version.generate_work_entries(
            date(2026, 1, 9), date(2026, 1, 9), force=True)
        self.assertEqual(
            entries.mapped('work_entry_type_id.code'), ['ADDITIONAL_DAY'])
        active_additional = self.env['hr.work.entry'].search([
            ('version_id', '=', version.id),
            ('date', '=', date(2026, 1, 9)),
            ('work_entry_type_id.code', '=', 'ADDITIONAL_DAY'),
        ])
        self.assertEqual(
            len(active_additional), 1,
            msg='before payslip: %s' % [
                (entry.id, entry.duration, entry.active)
                for entry in active_additional
            ],
        )

        payslip = self.env['hr.payslip'].create({
            'name': 'Fixed Additional Day Payslip',
            'employee_id': employee.id,
            'company_id': self.company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': version.id,
            'struct_id': monthly_structure.id,
        })
        payslip.compute_sheet()
        active_additional = self.env['hr.work.entry'].search([
            ('version_id', '=', version.id),
            ('date', '=', date(2026, 1, 9)),
            ('work_entry_type_id.code', '=', 'ADDITIONAL_DAY'),
        ])
        self.assertEqual(
            len(active_additional), 1,
            msg='after payslip: %s' % [
                (entry.id, entry.duration, entry.active)
                for entry in active_additional
            ],
        )
        worked_codes = payslip.worked_days_line_ids.mapped('code')
        self.assertIn('ADDITIONAL_DAY', worked_codes)
        self.assertNotIn('OVERTIME', worked_codes)
        by_code = {line.code: line.total for line in payslip.line_ids}
        additional_worked_day = payslip.worked_days_line_ids.filtered(
            lambda item: item.code == 'ADDITIONAL_DAY')
        self.assertTrue(additional_worked_day.work_entry_type_id.is_extra_hours)
        self.assertAlmostEqual(
            sum(additional_worked_day.mapped('amount')), 400.0, places=2)
        self.assertAlmostEqual(by_code['BASIC'], 10000.0, places=2)
        self.assertAlmostEqual(
            by_code['IL_ADDITIONAL_DAY_GROSS'], 400.0, places=2,
            msg=str([
                (line.code, line.number_of_days, line.number_of_hours, line.amount)
                for line in payslip.worked_days_line_ids
            ]),
        )
        self.assertAlmostEqual(by_code['GROSS'], 10400.0, places=2)

    def test_monthly_additional_day_is_paid_in_every_schedule_mode(self):
        """The UI schedule variants must all reach the same payroll result.

        Fixed/daily calendars classify a day with no planned hours as an
        additional day.  Weekly calendars classify the first day beyond the
        configured weekly quota.  In every case a monthly gross employee keeps
        the full monthly wage and receives the fixed additional-day amount on
        top of it.
        """
        monthly_type = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        monthly_structure = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il')
        modes = (
            ('attendance', 'fixed_intervals'),
            ('attendance', 'daily_duration'),
            ('attendance', 'weekly_quota'),
            ('shifts', 'daily_duration'),
            ('shifts', 'weekly_quota'),
        )
        scenarios = [
            (source, schedule_type, frequency)
            for source in ('attendance', 'calendar')
            for schedule_type, frequency in modes
        ]
        for index, (source, schedule_type, frequency) in enumerate(scenarios):
            with self.subTest(source=source,
                              schedule_type=schedule_type,
                              frequency=frequency):
                calendar_values = {
                    'name': 'Additional day %s %s' % (
                        schedule_type, frequency),
                    'company_id': self.company.id,
                    'tz': 'UTC',
                    'mdl_schedule_type': schedule_type,
                    'mdl_schedule_frequency': frequency,
                    'mdl_hours_per_day': 9.5,
                    'mdl_shifts_per_week': 1,
                }
                if frequency == 'weekly_quota':
                    calendar_values['hours_per_week'] = 9.5
                elif schedule_type == 'shifts':
                    calendar_values['mdl_shift_day_monday'] = True
                else:
                    calendar_values['attendance_ids'] = [Command.create({
                        'name': 'Monday',
                        'dayofweek': '0',
                        'day_period': (
                            'full_day' if frequency == 'daily_duration'
                            else 'morning'),
                        'hour_from': 6.5,
                        'hour_to': 16.0,
                        'duration_hours': 9.5,
                        'mdl_day_input_method': 'hours',
                    })]
                calendar = self.env['resource.calendar'].create(
                    calendar_values)
                employee = self.env['hr.employee'].create({
                    'name': 'Monthly Additional Day %s' % index,
                    'company_id': self.company.id,
                    'contract_date_start': date(2026, 2, 1),
                    'date_version': date(2026, 2, 1),
                    'resource_calendar_id': calendar.id,
                    'structure_type_id': monthly_type.id,
                    'il_salary_structure_id': monthly_structure.id,
                    'mdl_wage_type': 'mdl_monthly',
                    'mdl_wage_rate_type': 'gross',
                    'wage': 10000.0,
                    'mdl_additional_day_wage': 400.0,
                })
                version = employee.version_id
                version.work_entry_source = source

                first_day = date(2026, 2, 2) + timedelta(days=index * 7)
                attendance_days = (
                    (first_day, first_day + timedelta(days=1))
                    if frequency == 'weekly_quota'
                    else (first_day + timedelta(days=5),)
                )
                for attendance_day in attendance_days:
                    self.env['hr.attendance'].create({
                        'employee_id': employee.id,
                        'check_in': datetime.combine(
                            attendance_day, datetime.min.time()
                        ) + timedelta(hours=6, minutes=30),
                        'check_out': datetime.combine(
                            attendance_day, datetime.min.time()
                        ) + timedelta(hours=16),
                    })
                version.generate_work_entries(
                    attendance_days[0], attendance_days[-1], force=True)

                active_entries = self.env['hr.work.entry'].search([
                    ('version_id', '=', version.id),
                    ('date', '>=', attendance_days[0]),
                    ('date', '<=', attendance_days[-1]),
                    ('state', '!=', 'cancelled'),
                ])
                additional_entries = active_entries.filtered(
                    lambda entry:
                    entry.work_entry_type_id.code == 'ADDITIONAL_DAY')
                self.assertEqual(len(additional_entries), 1)

                payslip = self.env['hr.payslip'].create({
                    'name': 'Monthly Additional Day Payslip %s' % index,
                    'employee_id': employee.id,
                    'company_id': self.company.id,
                    'date_from': attendance_days[0],
                    'date_to': attendance_days[-1],
                    'version_id': version.id,
                    'struct_id': monthly_structure.id,
                })
                payslip.compute_sheet()
                by_code = {
                    line.code: line.total for line in payslip.line_ids
                }
                self.assertAlmostEqual(by_code['BASIC'], 10000.0, places=2)
                self.assertAlmostEqual(
                    by_code['IL_ADDITIONAL_DAY_GROSS'], 400.0, places=2)
                self.assertAlmostEqual(by_code['GROSS'], 10400.0, places=2)

    def test_daily_employee_keeps_normal_daily_wage_without_additional_day(self):
        fixed_calendar = self.env['resource.calendar'].create({
            'name': 'Daily Employee Monday Calendar',
            'company_id': self.company.id,
            'tz': 'UTC',
            'mdl_schedule_type': 'attendance',
            'mdl_schedule_frequency': 'fixed_intervals',
            'attendance_ids': [Command.create({
                'name': 'Monday',
                'dayofweek': '0',
                'day_period': 'morning',
                'hour_from': 6.5,
                'hour_to': 16.0,
            })],
        })
        employee = self.env['hr.employee'].create({
            'name': 'Gross Daily End To End Employee',
            'company_id': self.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': fixed_calendar.id,
            'structure_type_id': self.daily_type.id,
            'il_salary_structure_id': self.daily_structure.id,
            'mdl_wage_type': 'mdl_daily',
            'mdl_wage_rate_type': 'gross',
            'mdl_daily_wage': 400.0,
        })
        version = employee.version_id
        version.work_entry_source = 'attendance'
        self.env['hr.attendance'].create({
            'employee_id': employee.id,
            'check_in': datetime(2026, 1, 5, 6, 30),
            'check_out': datetime(2026, 1, 5, 16, 0),
        })
        version.generate_work_entries(
            date(2026, 1, 5), date(2026, 1, 5), force=True)
        payslip = self.env['hr.payslip'].create({
            'name': 'Gross Daily End To End Payslip',
            'employee_id': employee.id,
            'company_id': self.company.id,
            'date_from': date(2026, 1, 5),
            'date_to': date(2026, 1, 5),
            'version_id': version.id,
            'struct_id': self.daily_structure.id,
        })
        payslip.compute_sheet()
        self.assertIn('WORK100', payslip.worked_days_line_ids.mapped('code'))
        self.assertNotIn(
            'ADDITIONAL_DAY', payslip.worked_days_line_ids.mapped('code'))
        self.assertNotIn('OVERTIME', payslip.worked_days_line_ids.mapped('code'))
        by_code = {line.code: line.total for line in payslip.line_ids}
        self.assertAlmostEqual(by_code['BASIC'], 400.0, places=2)
        self.assertNotIn('IL_WAGE_ROUNDING', by_code)
        self.assertAlmostEqual(by_code['GROSS'], 400.0, places=2)
        self.assertAlmostEqual(
            by_code.get('IL_ADDITIONAL_DAY_GROSS', 0.0), 0.0, places=2)

    def test_gross_daily_additional_day_is_included_in_salary(self):
        fixed_calendar = self.env['resource.calendar'].create({
            'name': 'Gross Daily Additional Day Calendar',
            'company_id': self.company.id,
            'tz': 'UTC',
            'mdl_schedule_type': 'attendance',
            'mdl_schedule_frequency': 'fixed_intervals',
            'attendance_ids': [Command.create({
                'name': 'Monday',
                'dayofweek': '0',
                'day_period': 'morning',
                'hour_from': 6.5,
                'hour_to': 16.0,
            })],
        })
        employee = self.env['hr.employee'].create({
            'name': 'Gross Daily Additional Day Employee',
            'company_id': self.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': fixed_calendar.id,
            'structure_type_id': self.daily_type.id,
            'il_salary_structure_id': self.daily_structure.id,
            'mdl_wage_type': 'mdl_daily',
            'mdl_wage_rate_type': 'gross',
            'mdl_daily_wage': 400.0,
            'mdl_additional_day_wage': 600.0,
        })
        employee.version_id.work_entry_source = 'attendance'
        self.env['hr.attendance'].create({
            'employee_id': employee.id,
            'check_in': datetime(2026, 1, 10, 6, 30),
            'check_out': datetime(2026, 1, 10, 16, 0),
        })
        entries = employee.version_id.generate_work_entries(
            date(2026, 1, 10), date(2026, 1, 10), force=True)
        self.assertEqual(
            entries.mapped('work_entry_type_id.code'), ['ADDITIONAL_DAY'])

        payslip = self.env['hr.payslip'].create({
            'name': 'Gross Daily Additional Day Payslip',
            'employee_id': employee.id,
            'company_id': self.company.id,
            'date_from': date(2026, 1, 10),
            'date_to': date(2026, 1, 10),
            'version_id': employee.version_id.id,
            'struct_id': self.daily_structure.id,
        })
        payslip.compute_sheet()
        self.assertEqual(
            payslip.worked_days_line_ids.mapped('code'), ['ADDITIONAL_DAY'])
        by_code = {line.code: line.total for line in payslip.line_ids}
        self.assertAlmostEqual(by_code.get('BASIC', 0.0), 0.0, places=2)
        self.assertAlmostEqual(
            by_code['IL_ADDITIONAL_DAY_GROSS'], 600.0, places=2)
        self.assertAlmostEqual(by_code['GROSS'], 600.0, places=2)

    def test_net_daily_additional_day_is_grossed_up(self):
        self.version.mdl_additional_day_wage = 475.0
        entry_type = self.env['hr.work.entry.type'].create({
            'name': 'Configured Net Extra Day',
            'code': 'CONFIGURED_NET_EXTRA_DAY',
            'is_extra_hours': True,
            'round_days': 'NO',
        })
        self.company.mdl_additional_day_work_entry_type_id = entry_type
        regular = self._create_payslip()
        regular._il_run_gross_up_engine()
        regular_net = regular._il_compute_net_total()

        payslip = self._create_payslip()
        payslip.write({
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': entry_type.id,
                'number_of_hours': 4.75,
                'number_of_days': 1.0,
            })],
        })
        payslip.worked_days_line_ids._compute_is_paid()
        payslip._il_run_gross_up_engine()
        by_code = {
            line['code']: line['total']
            for line in payslip._get_payslip_lines()
        }

        self.assertGreater(by_code['IL_ADDITIONAL_DAY_GROSS'], 237.50)
        self.assertAlmostEqual(
            by_code['NET'], regular_net + 237.50,
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
        overtime_line = self.env['hr.attendance.overtime.line'].create({
            'employee_id': self.employee.id,
            'date': date(2026, 1, 15),
            'status': 'approved',
            'duration': 10.0,
            'manual_duration': 10.0,
            'amount_rate': 0.0,
            'mdl_fixed_hourly_amount': 50.0,
            'work_entry_type_overtime_id': overtime_type.id,
        })
        self.env['hr.work.entry'].create({
            'name': 'Represented fixed overtime',
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'company_id': self.company.id,
            'date': date(2026, 1, 15),
            'duration': 10.0,
            'work_entry_type_id': overtime_type.id,
            'overtime_id': overtime_line.id,
        })
        overtime = self._create_payslip(overtime_hours=10.0)
        overtime._il_run_gross_up_engine()
        self.assertAlmostEqual(overtime._il_overtime_amount(), 500.0, places=2)

    def test_unrepresented_fixed_overtime_is_not_paid(self):
        overtime_type = self.env.ref(
            'hr_work_entry.work_entry_type_overtime')
        self.env['hr.attendance.overtime.line'].create({
            'employee_id': self.employee.id,
            'date': date(2026, 1, 16),
            'status': 'approved',
            'duration': 9.0,
            'manual_duration': 9.0,
            'amount_rate': 0.0,
            'mdl_fixed_hourly_amount': 50.0,
            'work_entry_type_overtime_id': overtime_type.id,
        })
        payslip = self._create_payslip()
        self.assertEqual(payslip._il_overtime_amount(), 0.0)

    def test_monthly_basic_is_not_reduced_by_missing_attendance(self):
        monthly_type = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        monthly_structure = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il')
        employee = self.env['hr.employee'].create({
            'name': 'Monthly Missing Attendance Employee',
            'company_id': self.company.id,
            'contract_date_start': date(2026, 1, 1),
            'date_version': date(2026, 1, 1),
            'resource_calendar_id': self.calendar.id,
            'structure_type_id': monthly_type.id,
            'il_salary_structure_id': monthly_structure.id,
            'mdl_wage_type': 'mdl_monthly',
            'wage': 10000.0,
        })
        version = employee.version_id
        payslip = self.env['hr.payslip'].create({
            'name': 'Monthly Missing Attendance Payslip',
            'employee_id': employee.id,
            'company_id': self.company.id,
            'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31),
            'version_id': version.id,
            'struct_id': monthly_structure.id,
            'edited': True,
            'worked_days_line_ids': [Command.create({
                'work_entry_type_id': self.env.ref(
                    'l10n_il_hr_payroll.work_entry_type_unpaid_absence').id,
                'number_of_hours': 9.5,
                'number_of_days': 1.0,
            })],
        })
        self.assertEqual(payslip._il_basic_amount(), 10000.0)

    def test_monthly_net_wage_is_grossed_up_for_both_structures(self):
        monthly_structures = (
            self.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_il'),
            self.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_monthly'),
        )
        attendance_type = self.env.ref(
            'hr_work_entry.work_entry_type_attendance')

        for structure in monthly_structures:
            with self.subTest(structure=structure.code):
                employee = self.env['hr.employee'].create({
                    'name': f'Monthly Net Gross-Up {structure.code}',
                    'company_id': self.company.id,
                    'contract_date_start': date(2026, 1, 1),
                    'date_version': date(2026, 1, 1),
                    'resource_calendar_id': self.calendar.id,
                    'structure_type_id': structure.type_id.id,
                    'il_salary_structure_id': structure.id,
                    'mdl_wage_type': 'mdl_monthly',
                    'mdl_wage_rate_type': 'net',
                    'wage': 10000.0,
                    'il_tax_credit_points': 0.0,
                })
                payslip = self.env['hr.payslip'].create({
                    'name': f'Monthly Net Gross-Up {structure.code}',
                    'employee_id': employee.id,
                    'company_id': self.company.id,
                    'date_from': date(2026, 1, 1),
                    'date_to': date(2026, 1, 31),
                    'version_id': employee.version_id.id,
                    'struct_id': structure.id,
                    'edited': True,
                    'worked_days_line_ids': [Command.create({
                        'work_entry_type_id': attendance_type.id,
                        'number_of_hours': 190.0,
                        'number_of_days': 20.0,
                    })],
                })
                payslip.worked_days_line_ids._compute_is_paid()
                payslip._compute_input_line_ids()
                payslip._il_set_regular_attendance_amount(0.0)
                baseline = payslip.with_context(
                    il_solving_net_base_wage=True,
                    il_skip_wage_rounding=True)._il_compute_net_total()

                payslip._il_run_gross_up_engine()
                gross_amount = sum(payslip.worked_days_line_ids.filtered(
                    lambda line: line.code == 'WORK100').mapped('amount'))
                solved_net = payslip.with_context(
                    il_solving_net_base_wage=True)._il_compute_net_total()

                self.assertEqual(payslip._il_net_attendance_target(), 10000.0)
                self.assertGreater(gross_amount, 10000.0)
                self.assertAlmostEqual(
                    solved_net,
                    baseline + 10000.0,
                    delta=payslip.currency_id.rounding / 2,
                )
                by_code = {
                    line['code']: line['total']
                    for line in payslip._get_payslip_lines()
                }
                self.assertAlmostEqual(
                    by_code['BASIC'], gross_amount, places=2)
                self.assertNotIn('IL_WAGE_ROUNDING', by_code)

    def test_palestinian_daily_structure_uses_same_net_target_contract(self):
        palestinian_structure = self.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_daily')
        payslip = self._create_payslip(structure=palestinian_structure)
        self.assertEqual(payslip._il_worker_profile(), 'palestinian')
        payslip._il_set_regular_attendance_amount(0.0)
        baseline = payslip.with_context(
            il_solving_net_base_wage=True,
            il_skip_wage_rounding=True)._il_compute_net_total()
        payslip._il_run_gross_up_engine()
        solved_net = payslip.with_context(
            il_solving_net_base_wage=True)._il_compute_net_total()
        self.assertAlmostEqual(
            solved_net,
            baseline + payslip._il_net_attendance_target(),
            delta=payslip.currency_id.rounding / 2,
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
                self.assertNotIn('IL_PAYMENTS', by_code)
                self.assertNotIn('IL_NET_TO_PAY', by_code)
                self.assertNotIn('IL_WAGE_ROUNDING', by_code)

    def test_daily_wage_validation_and_shared_rate_type(self):
        with self.assertRaisesRegex(ValidationError, 'שכר יומי'):
            self.version.mdl_daily_wage = 0.0
        self.version.invalidate_recordset()

        self.version.write({
            'mdl_wage_type': 'mdl_monthly',
            'mdl_wage_rate_type': 'net',
            'structure_type_id': self.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_type_il').id,
            'il_salary_structure_id': self.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_il').id,
        })
        self.assertEqual(self.version.mdl_wage_rate_type, 'net')
        self.assertEqual(self.version.schedule_pay, 'monthly')
