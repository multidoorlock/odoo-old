from odoo import api, SUPERUSER_ID


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
    """Remove the superseded net-base input/rules when no history uses them."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    _remove_unused_or_archive(
        env,
        env['hr.salary.rule'].with_context(active_test=False).search([
            ('code', '=', 'IL_NET_BASE_GROSSUP'),
        ]),
        'hr.payslip.line',
        'salary_rule_id',
    )
    _remove_unused_or_archive(
        env,
        env['hr.payslip.input.type'].with_context(active_test=False).search([
            ('code', '=', 'IL_NET_BASE_WAGE'),
        ]),
        'hr.payslip.input',
        'input_type_id',
    )
