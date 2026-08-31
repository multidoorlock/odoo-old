from odoo import api, SUPERUSER_ID


LEGACY_RULE_CODES = (
    'IL_NET_WEEKEND_GROSSUP',
    'IL_NET_ADDITIONAL_DAY_GROSSUP',
)
LEGACY_INPUT_CODES = (
    'IL_NET_WEEKEND',
    'IL_NET_ADDITIONAL_DAY',
)


def _remove_unused_or_archive(env, records, usage_model, usage_field):
    if not records:
        return
    if env[usage_model].search_count([(usage_field, 'in', records.ids)], limit=1):
        records.write({'active': False})
        return
    env['ir.model.data'].search([
        ('model', '=', records._name),
        ('res_id', 'in', records.ids),
    ]).unlink()
    records.unlink()


def migrate(cr, version):
    """Retire technical net inputs after moving gross-up to Worked Days."""
    env = api.Environment(cr, SUPERUSER_ID, {})

    input_types = env['hr.payslip.input.type'].with_context(active_test=False).search([
        ('code', 'in', LEGACY_INPUT_CODES),
    ])
    if input_types:
        env['hr.payslip.input'].search([
            ('input_type_id', 'in', input_types.ids),
            ('payslip_id.state', '=', 'draft'),
        ]).unlink()
        _remove_unused_or_archive(
            env, input_types, 'hr.payslip.input', 'input_type_id')

    rules = env['hr.salary.rule'].with_context(active_test=False).search([
        ('code', 'in', LEGACY_RULE_CODES),
    ])
    if rules:
        env['hr.payslip.line'].search([
            ('salary_rule_id', 'in', rules.ids),
            ('slip_id.state', '=', 'draft'),
        ]).unlink()
        _remove_unused_or_archive(
            env, rules, 'hr.payslip.line', 'salary_rule_id')
