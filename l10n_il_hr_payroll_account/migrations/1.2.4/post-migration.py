from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Retire weekend salary rules and force monthly employee pay cycles."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.version'].with_context(active_test=False).search([]).write({
        'schedule_pay': 'monthly',
    })

    rules = env['hr.salary.rule'].with_context(active_test=False).search([
        ('code', '=', 'IL_WEEKEND_GROSS'),
    ])
    if not rules:
        return
    used_rules = rules.filtered(lambda rule: env['hr.payslip.line'].search_count([
        ('salary_rule_id', '=', rule.id),
    ], limit=1))
    unused_rules = rules - used_rules
    if used_rules:
        used_rules.active = False
    if unused_rules:
        env['ir.model.data'].search([
            ('model', '=', 'hr.salary.rule'),
            ('res_id', 'in', unused_rules.ids),
        ]).unlink()
        unused_rules.unlink()
