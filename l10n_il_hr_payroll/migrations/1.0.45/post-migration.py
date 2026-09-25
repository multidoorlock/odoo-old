def migrate(cr, version):
    """Install the native mutually-exclusive Sign controls on a fresh template."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    Form101 = env['hr.employee.form.101'].sudo()
    form_model = env['ir.model']._get('hr.employee.form.101')
    templates = env['sign.template'].sudo().with_context(active_test=False).search([
        ('model_id', '=', form_model.id),
    ])
    requests = env['sign.request'].sudo().search([
        ('template_id', 'in', templates.ids),
    ])
    forms = Form101.search([
        '|',
        ('sign_template_id', 'in', templates.ids),
        ('sign_request_id', 'in', requests.ids),
    ])
    if forms:
        forms.write({
            'sign_request_id': False,
            'sign_template_id': False,
        })
    if requests:
        requests.unlink()
    env['ir.model.data'].sudo().search([
        ('module', '=', 'l10n_il_hr_payroll'),
        ('name', '=', 'sign_template_form_101'),
    ]).unlink()
    if templates:
        templates.unlink()

    template = Form101._ensure_form_101_sign_template()
    Form101.search([('sign_template_id', '=', False)]).write({
        'sign_template_id': template.id,
    })
