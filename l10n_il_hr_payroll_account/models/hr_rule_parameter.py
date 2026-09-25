# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import ValidationError


class HrRuleParameter(models.Model):
    _inherit = 'hr.rule.parameter'

    @api.model
    def _il_rebuild_2026_parameters(self):
        """Seed missing 2026 defaults without replacing configured history.

        Parameter codes are globally unique in native Odoo. Existing values
        remain authoritative, including future versions and customized codes
        or countries. Only an empty Israeli parameter needs its initial value.
        """
        values = {
            'IL_TAX_BRACKET_1_LIMIT': 7010, 'IL_TAX_BRACKET_1_RATE': 10,
            'IL_TAX_BRACKET_2_LIMIT': 10060, 'IL_TAX_BRACKET_2_RATE': 14,
            'IL_TAX_BRACKET_3_LIMIT': 19000, 'IL_TAX_BRACKET_3_RATE': 20,
            'IL_TAX_BRACKET_4_LIMIT': 25100, 'IL_TAX_BRACKET_4_RATE': 31,
            'IL_TAX_BRACKET_5_LIMIT': 46690, 'IL_TAX_BRACKET_5_RATE': 35,
            'IL_TAX_BRACKET_6_LIMIT': 60130, 'IL_TAX_BRACKET_6_RATE': 47,
            'IL_TAX_BRACKET_7_RATE': 47,
            'IL_TAX_CREDIT_POINT_VALUE': 242,
            'IL_PENSION_TAX_CREDIT_RATE': 35,
            'IL_PENSION_TAX_CREDIT_MAX_CONTRIBUTION_RATE': 7,
            'IL_TAX_MAX_WITHHOLDING_RATE': 47,
            'IL_TAX_SURTAX_THRESHOLD': 60130, 'IL_TAX_SURTAX_RATE': 3,
            'IL_PENSION_MANDATORY_CEILING': 0,
            'IL_STUDY_FUND_TAX_CEILING': 0,
            'IL_ISR_NI_REDUCED_LIMIT': 7703, 'IL_ISR_NI_MAX_BASE': 51910,
            'IL_ISR_NI_EE_REDUCED_RATE': 1.04, 'IL_ISR_NI_EE_FULL_RATE': 7.0,
            'IL_ISR_NI_ER_REDUCED_RATE': 4.51, 'IL_ISR_NI_ER_FULL_RATE': 7.6,
            'IL_ISR_HEALTH_REDUCED_RATE': 3.23, 'IL_ISR_HEALTH_FULL_RATE': 5.17,
            # Palestinian payroll values remain explicit parameters and can be
            # versioned independently when PIBA publishes a newer table.
            'IL_PAL_NI_REDUCED_LIMIT': 7703, 'IL_PAL_NI_MAX_BASE': 51910,
            'IL_PAL_NI_EE_REDUCED_RATE': 0.07, 'IL_PAL_NI_EE_FULL_RATE': 0.61,
            'IL_PAL_NI_ER_REDUCED_RATE': 0.71, 'IL_PAL_NI_ER_FULL_RATE': 2.49,
            'IL_PAL_HEALTH_STAMP_AMOUNT': 0,
            'IL_PAL_ORGANIZATION_TAX_RATE': 0.75,
            'IL_PAL_ORGANIZATION_TAX_CEILING': 22637,
            'IL_PAL_EQUALIZATION_RATE': 0,
            'IL_PAL_EQUALIZATION_CONSTRUCTION_RATE': 0,
            'IL_PAL_EQUALIZATION_INDUSTRY_RATE': 0,
            'IL_PAL_EQUALIZATION_AGRICULTURE_RATE': 0,
        }
        country = self.env.ref('base.il')
        existing = self.with_context(active_test=False).search([
            ('code', 'in', list(values)),
        ])
        by_code = {}
        for parameter in existing:
            if parameter.code in by_code:
                # Native Odoo enforces unique(code). Do not choose a record
                # or delete history if a damaged/custom database violates it.
                raise ValidationError(_(
                    'נמצאו כמה פרמטרי שכר עם הקוד %s. יש לבדוק את ההגדרות לפני העדכון.',
                    parameter.code))
            by_code[parameter.code] = parameter
        Value = self.env['hr.rule.parameter.value']
        for code, value in values.items():
            parameter = by_code.get(code)
            if parameter:
                if parameter.parameter_version_ids or parameter.country_id != country:
                    continue
            else:
                parameter = self.create({'name': code, 'code': code, 'country_id': country.id})
            Value.create({
                'rule_parameter_id': parameter.id,
                'date_from': '2026-01-01',
                'parameter_value': repr(value),
            })
        return True
