# -*- coding: utf-8 -*-
from odoo import api, models


class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    @api.model
    def _il_sync_structures_and_rules(self):
        refs = {
            'isr_monthly': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il'),
            'pal_monthly': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_monthly'),
            'isr_daily': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_isr_daily'),
            'pal_daily': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_daily'),
        }
        country = self.env.ref('base.il')
        obsolete_structures = self.with_context(active_test=False).search([
            ('country_id', '=', country.id),
            ('id', 'not in', [structure.id for structure in refs.values()]),
        ])
        for structure in obsolete_structures:
            if self.env['hr.payslip'].search_count([('struct_id', '=', structure.id)]):
                structure.active = False
            else:
                structure.unlink()
        template = refs['isr_monthly']
        rules = template.rule_ids
        common = rules.filtered(lambda r: not r.code.startswith(('IL_ISR_', 'IL_PAL_', 'IL_FOR_')))
        groups = {
            'pal_monthly': common | rules.filtered(lambda r: r.code.startswith('IL_PAL_')),
            'isr_daily': common | rules.filtered(lambda r: r.code.startswith('IL_ISR_')),
            'pal_daily': common | rules.filtered(lambda r: r.code.startswith('IL_PAL_')),
        }
        values_by_key = {}
        for key, selected in groups.items():
            values_by_key[key] = []
            for rule in selected:
                values = rule.copy_data(default={
                    'struct_id': False,
                    # copy_data adds "(copy)" by default. These are the same
                    # statutory rules in another structure, so keep the
                    # canonical user-facing name.
                    'name': rule.name,
                })[0]
                values_by_key[key].append((rule.code, values))
        inputs = template.input_line_type_ids

        def retire(rule):
            """Never delete a salary rule referenced by historical payslip lines."""
            if self.env['hr.payslip.line'].search_count([('salary_rule_id', '=', rule.id)]):
                rule.active = False
            else:
                rule.unlink()

        # Keep XML-owned common/Israeli template rules stable across upgrades,
        # while excluding rules belonging to other employee populations.
        for rule in template.with_context(active_test=False).rule_ids.filtered(
                lambda item: item.code.startswith(('IL_PAL_', 'IL_FOR_'))):
            retire(rule)
        for key, structure in refs.items():
            if key == 'isr_monthly':
                structure.input_line_type_ids = inputs
                continue
            existing_rules = structure.with_context(active_test=False).rule_ids
            desired_codes = {code for code, values in values_by_key[key]}
            for code, values in values_by_key[key]:
                matches = existing_rules.filtered(lambda item: item.code == code)
                values.update({'struct_id': structure.id, 'active': True})
                if matches:
                    matches[:1].write(values)
                    for duplicate in matches[1:]:
                        retire(duplicate)
                else:
                    self.env['hr.salary.rule'].create(values)
            for rule in existing_rules.filtered(lambda item: item.active and item.code not in desired_codes):
                retire(rule)
            structure.input_line_type_ids = inputs
        return True
