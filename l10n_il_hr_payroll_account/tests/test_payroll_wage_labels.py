from datetime import date

from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_il_hr_payroll_account_wage_labels')
class TestPayrollWageLabels(TransactionCase):

    def _import(self):
        return self.env['ir.module.module']._il_import_hr_hebrew_ui_translations()

    def test_payslip_form_and_selection_labels_are_hebrew_only(self):
        specifications = {
            'hr.payslip': ['gross_wage', 'net_wage', 'il_net_amount_to_pay'],
            'hr.payslip.input': ['il_effect_type', 'il_net_adjustment_treatment'],
            'hr.salary.attachment': ['il_effect_type', 'il_net_adjustment_treatment'],
            'hr.payslip.input.type': ['il_net_adjustment_treatment'],
            'hr.employee': ['mdl_wage_rate_type'],
            'hr.version': ['mdl_wage_rate_type'],
        }
        english = {model: self.env[model].with_context(lang='en_US').fields_get(
            names, attributes=['string', 'selection', 'help'])
            for model, names in specifications.items()}
        english_view = self.env['hr.payslip'].with_context(lang='en_US').get_view(view_type='form')['arch']
        self._import()
        for model, names in specifications.items():
            self.assertEqual(self.env[model].with_context(lang='en_US').fields_get(
                names, attributes=['string', 'selection', 'help']), english[model])
        self.assertEqual(self.env['hr.payslip'].with_context(lang='en_US').get_view(
            view_type='form')['arch'], english_view)
        fields = self.env['hr.payslip'].with_context(lang='he_IL').fields_get(specifications['hr.payslip'])
        self.assertEqual(fields['gross_wage']['string'], 'שכר ברוטו')
        self.assertEqual(fields['net_wage']['string'], 'שכר נטו')
        self.assertEqual(fields['il_net_amount_to_pay']['string'], 'יתרת שכר נטו לתשלום')
        arch = etree.fromstring(self.env['hr.payslip'].with_context(lang='he_IL').get_view(
            view_type='form')['arch'])
        for name, label in [('gross_wage', 'שכר ברוטו'), ('net_wage', 'שכר נטו'),
                            ('il_net_amount_to_pay', 'שכר נטו לתשלום')]:
            self.assertIn(label, arch.xpath("//field[@name='%s']/@string" % name))
        effect_type_models = {'hr.payslip.input', 'hr.salary.attachment'}
        for model, field in [('hr.payslip.input', 'il_effect_type'),
                             ('hr.salary.attachment', 'il_effect_type'),
                             ('hr.employee', 'mdl_wage_rate_type'),
                             ('hr.version', 'mdl_wage_rate_type')]:
            selection = dict(self.env[model].with_context(lang='he_IL').fields_get(
                [field])[field]['selection'])
            if model in effect_type_models:
                self.assertEqual(
                    selection.pop('taxable_benefit'),
                    '\u05e9\u05d5\u05d5\u05d9 \u05d7\u05d9\u05d9\u05d1 (\u05dc\u05d0 \u05de\u05e9\u05d5\u05dc\u05dd)',
                )
            self.assertEqual(dict(selection), {'gross': 'שכר ברוטו', 'net': 'שכר נטו'})
        for model in ['hr.payslip.input', 'hr.salary.attachment', 'hr.payslip.input.type']:
            selection = self.env[model].with_context(lang='he_IL').fields_get(
                ['il_net_adjustment_treatment'])['il_net_adjustment_treatment']['selection']
            self.assertEqual(dict(selection), {'gross_up': 'גילום שכר נטו',
                                                'direct_net': 'השפעה ישירה על שכר הנטו'})

    def test_rule_rename_upgrades_old_translation_without_changing_calculation(self):
        rule = self.env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_gross').with_context(lang='en_US')
        fields = ['name', 'code', 'amount_select', 'amount_python_compute', 'category_id', 'active']
        original = rule.read(fields)
        rule.update_field_translations('name', {'he_IL': 'ברוטו'})
        # Cloned structures have their own rules with no external ID.
        clone = rule.copy({'name': 'ברוטו'})
        clone.update_field_translations('name', {'he_IL': 'ברוטו'})
        self._import()
        self.assertEqual(rule.with_context(lang='he_IL').name, 'שכר ברוטו')
        self.assertEqual(clone.with_context(lang='he_IL').name, 'שכר ברוטו')
        self.assertEqual(rule.read(fields), original)
        self.assertEqual(clone.with_context(lang='en_US').name, 'ברוטו')
        self.assertEqual(clone.code, rule.code)
        self.assertEqual(clone.amount_python_compute, rule.amount_python_compute)
        rule.update_field_translations('name', {'he_IL': 'כותרת שכר מותאמת אישית'})
        self._import()
        self.assertEqual(rule.with_context(lang='he_IL').name, 'כותרת שכר מותאמת אישית')
        self.assertEqual(rule.read(fields), original)
        self.assertEqual(self._import(), {'model_terms': 0, 'model_values': 0, 'named_values': 0})

    def test_saved_payslip_lines_render_new_labels_without_rewriting_salary(self):
        structure = self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il')
        employee = self.env['hr.employee'].create({
            'name': 'Wage Label UI Employee', 'company_id': self.env.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'structure_type_id': structure.type_id.id,
            'il_salary_structure_id': structure.id, 'schedule_pay': 'monthly',
        })
        slip = self.env['hr.payslip'].create({
            'name': 'Existing Wage Label Payslip', 'employee_id': employee.id,
            'company_id': self.env.company.id, 'date_from': date(2026, 1, 1),
            'date_to': date(2026, 1, 31), 'version_id': employee.version_id.id,
            'struct_id': structure.id, 'edited': True,
        })
        gross_rule = self.env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_gross')
        net_rule = self.env.ref('l10n_il_hr_payroll_account.hr_salary_rule_il_net')
        lines = self.env['hr.payslip.line'].create([
            {'slip_id': slip.id, 'salary_rule_id': gross_rule.id, 'name': 'ברוטו',
             'amount': 7000, 'total': 7000},
            {'slip_id': slip.id, 'salary_rule_id': net_rule.id, 'name': 'נטו',
             'amount': 6000, 'total': 6000},
            {'slip_id': slip.id, 'salary_rule_id': net_rule.id, 'name': 'נטו מתוקן ידנית',
             'amount': 100, 'total': 100},
        ])
        stored_fields = ['name', 'code', 'amount', 'total', 'rate', 'quantity', 'write_date']
        before = lines.read(stored_fields)
        spec = {'line_ids': {'fields': {'name': {}, 'code': {}, 'amount': {}, 'total': {}}}}
        hebrew = {row['id']: row for row in slip.with_context(lang='he_IL').web_read(spec)[0]['line_ids']}
        self.assertEqual(hebrew[lines[0].id]['name'], 'שכר ברוטו')
        self.assertEqual(hebrew[lines[1].id]['name'], 'שכר נטו')
        self.assertEqual(hebrew[lines[2].id]['name'], 'נטו מתוקן ידנית')
        english = {row['id']: row for row in slip.with_context(lang='en_US').web_read(spec)[0]['line_ids']}
        for row in before:
            self.assertEqual(english[row['id']]['name'], row['name'])
            for field in ['code', 'amount', 'total']:
                self.assertEqual(hebrew[row['id']][field], row[field])
        self.assertEqual(lines.read(stored_fields), before)
