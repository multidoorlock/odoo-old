from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'il_payroll_parameter_preservation')
class TestPayrollParameterPreservation(TransactionCase):

    def _parameter(self, code):
        parameter = self.env['hr.rule.parameter'].search([('code', '=', code)])
        self.assertEqual(len(parameter), 1)
        return parameter

    def _replace_versions(self, parameter, versions):
        # Test-only changes are rolled back by TransactionCase. They model
        # company-maintained parameter versions before a module upgrade.
        parameter.parameter_version_ids.unlink()
        return self.env['hr.rule.parameter.value'].create([
            {'rule_parameter_id': parameter.id, 'date_from': start,
             'parameter_value': repr(value)}
            for start, value in versions
        ])

    def _snapshot(self, parameters):
        return (
            parameters.sorted('id').read(['name', 'code', 'country_id', 'description', 'write_date']),
            parameters.parameter_version_ids.sorted('id').read(
                ['rule_parameter_id', 'date_from', 'parameter_value', 'write_date']),
        )

    def test_repeated_upgrade_preserves_custom_history_and_extra_israeli_code(self):
        parameter = self._parameter('IL_TAX_CREDIT_POINT_VALUE')
        parameter.write({'name': 'Locally approved credit point', 'description': '<p>Keep approved versions</p>'})
        self._replace_versions(parameter, [('2025-01-01', 240), ('2026-01-01', 0), ('2027-01-01', 275)])
        custom = self.env['hr.rule.parameter'].create({
            'name': 'Custom agreement', 'code': 'IL_TEST_CUSTOM_AGREEMENT',
            'country_id': self.env.ref('base.il').id,
        })
        self._replace_versions(custom, [('2026-02-01', {'rate': 12.5})])
        before = self._snapshot(parameter | custom)

        for _attempt in range(2):
            self.env['hr.rule.parameter']._il_rebuild_2026_parameters()
            self.assertEqual(self._snapshot(parameter | custom), before)
        Model = self.env['hr.rule.parameter']
        self.assertEqual(Model._get_parameter_from_code(parameter.code, date(2026, 6, 1)), 0)
        self.assertEqual(Model._get_parameter_from_code(parameter.code, date(2027, 6, 1)), 275)
        self.assertEqual(Model._get_parameter_from_code(custom.code, date(2026, 6, 1)), {'rate': 12.5})

    def test_empty_israeli_parameter_is_seeded_once_without_replacing_record(self):
        parameter = self._parameter('IL_PAL_HEALTH_STAMP_AMOUNT')
        self._replace_versions(parameter, [])
        parameter.name = 'Custom display name for an empty parameter'
        identity = parameter.read(['name', 'country_id', 'description', 'write_date'])

        self.env['hr.rule.parameter']._il_rebuild_2026_parameters()
        self.assertEqual(parameter.read(['name', 'country_id', 'description', 'write_date']), identity)
        self.assertEqual(len(parameter.parameter_version_ids), 1)
        self.assertEqual(parameter.parameter_version_ids.date_from, date(2026, 1, 1))
        self.assertEqual(parameter.parameter_version_ids.parameter_value, '0')
        before = self._snapshot(parameter)
        self.env['hr.rule.parameter']._il_rebuild_2026_parameters()
        self.assertEqual(self._snapshot(parameter), before)

    def test_missing_code_gets_default_without_changing_other_parameters(self):
        code = 'IL_TAX_MAX_WITHHOLDING_RATE'
        self._parameter(code).unlink()
        others = self.env['hr.rule.parameter'].search([])
        before = self._snapshot(others)

        self.env['hr.rule.parameter']._il_rebuild_2026_parameters()
        parameter = self._parameter(code)
        self.assertEqual(parameter.country_id, self.env.ref('base.il'))
        self.assertEqual(len(parameter.parameter_version_ids), 1)
        self.assertEqual(parameter.parameter_version_ids.parameter_value, '47')
        self.assertEqual(self._snapshot(others), before)
        self.assertEqual(self.env['hr.rule.parameter'].search_count([]), len(others) + 1)

    def test_existing_global_code_and_future_only_history_are_not_replaced(self):
        parameter = self._parameter('IL_TAX_CREDIT_POINT_VALUE')
        self._replace_versions(parameter, [('2027-01-01', 999)])
        global_code = self._parameter('IL_TAX_MAX_WITHHOLDING_RATE')
        global_code.country_id = self.env.ref('base.us')
        self._replace_versions(global_code, [])
        before = self._snapshot(parameter | global_code)

        self.env['hr.rule.parameter']._il_rebuild_2026_parameters()
        self.assertEqual(self._snapshot(parameter | global_code), before)
        self.assertFalse(global_code.parameter_version_ids)
        self.assertFalse(self.env['hr.rule.parameter']._get_parameter_from_code(
            parameter.code, date(2026, 6, 1), raise_if_not_found=False))
        self.assertEqual(self.env['hr.rule.parameter']._get_parameter_from_code(
            parameter.code, date(2027, 6, 1)), 999)
