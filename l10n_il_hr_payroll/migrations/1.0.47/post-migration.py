def migrate(cr, version):
    """Remove only custom Form 101 records from Odoo Sign."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    Form101 = env['hr.employee.form.101'].sudo()
    form_model = env['ir.model']._get('hr.employee.form.101')

    template_xmlid = env['ir.model.data'].sudo().search([
        ('module', '=', 'l10n_il_hr_payroll'),
        ('name', '=', 'sign_template_form_101'),
    ])
    role_xmlid = env['ir.model.data'].sudo().search([
        ('module', '=', 'l10n_il_hr_payroll'),
        ('name', '=', 'sign_item_role_form_101_employee'),
    ])
    templates = env['sign.template'].sudo().with_context(active_test=False).search([
        ('model_id', '=', form_model.id),
    ])
    if template_xmlid and template_xmlid.model == 'sign.template':
        templates |= env['sign.template'].sudo().with_context(
            active_test=False).browse(template_xmlid.res_id).exists()

    item_types = env['sign.item.type'].sudo().search([
        ('model_id', '=', form_model.id),
    ])
    custom_items = env['sign.item'].sudo().search([
        ('type_id', 'in', item_types.ids),
    ])
    templates |= custom_items.document_id.template_id
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
    if template_xmlid:
        template_xmlid.unlink()
    if templates:
        templates.unlink()
    if item_types:
        item_types.unlink()

    role = env['sign.item.role']
    if role_xmlid and role_xmlid.model == 'sign.item.role':
        role = env['sign.item.role'].sudo().browse(role_xmlid.res_id).exists()
    if role_xmlid:
        role_xmlid.unlink()
    role_items = env['sign.item'].sudo().search_count([
        ('responsible_id', 'in', role.ids),
    ]) if role else 0
    role_requests = env['sign.request.item'].sudo().search_count([
        ('role_id', 'in', role.ids),
    ]) if role else 0
    if role and not role_items and not role_requests:
        role.unlink()
