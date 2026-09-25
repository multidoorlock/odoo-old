from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Install the corrected 2026 statutory tables on existing databases."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    values = {
        'IL_TAX_BRACKET_3_LIMIT': 19000,
        'IL_TAX_BRACKET_4_LIMIT': 25100,
        'IL_PENSION_TAX_CREDIT_RATE': 35,
        'IL_PENSION_TAX_CREDIT_MAX_CONTRIBUTION_RATE': 7,
        'IL_PAL_NI_REDUCED_LIMIT': 7703,
        'IL_PAL_NI_MAX_BASE': 51910,
        'IL_PAL_NI_EE_REDUCED_RATE': 0.07,
        'IL_PAL_NI_EE_FULL_RATE': 0.61,
        'IL_PAL_NI_ER_REDUCED_RATE': 0.71,
        'IL_PAL_NI_ER_FULL_RATE': 2.49,
    }
    Parameter = env['hr.rule.parameter'].with_context(active_test=False)
    Value = env['hr.rule.parameter.value']
    country = env.ref('base.il')
    for code, value in values.items():
        parameter = Parameter.search([('code', '=', code)], limit=1)
        if not parameter:
            parameter = Parameter.create({
                'name': code,
                'code': code,
                'country_id': country.id,
            })
        version_value = parameter.parameter_version_ids.filtered(
            lambda item: str(item.date_from) == '2026-01-01')[:1]
        if version_value:
            version_value.parameter_value = repr(value)
        else:
            Value.create({
                'rule_parameter_id': parameter.id,
                'date_from': '2026-01-01',
                'parameter_value': repr(value),
            })

    env['hr.payroll.structure']._il_sync_structures_and_rules()
