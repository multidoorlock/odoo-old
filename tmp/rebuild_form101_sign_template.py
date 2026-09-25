Form101 = env['hr.employee.form.101'].sudo()
Template = env['sign.template'].sudo().with_context(active_test=False)

form_model = env['ir.model']._get('hr.employee.form.101')
templates = Template.search([('model_id', '=', form_model.id)])
requests = env['sign.request'].sudo().search([('template_id', 'in', templates.ids)])
forms = Form101.search([
    '|',
    ('sign_template_id', 'in', templates.ids),
    ('sign_request_id', 'in', requests.ids),
])

print(
    'REMOVING',
    'templates=', templates.ids,
    'documents=', templates.document_ids.ids,
    'items=', len(templates.sign_item_ids),
    'requests=', requests.ids,
    'forms=', forms.ids,
)

# These are the obsolete local Form 101 signature attempts.  Reset linked
# demo forms first so no record can still point at a deleted request/template.
if forms:
    forms.with_context(skip_form_101_employee_sync=True).write({
        'state': 'draft',
    })
    forms.with_context(skip_form_101_employee_sync=True).write({
        'sign_request_id': False,
        'sign_template_id': False,
        'form_file': False,
        'form_filename': False,
    })
if requests:
    requests.unlink()
templates.unlink()

# Drop a stale XML id if the ORM kept it after removing the former template.
env['ir.model.data'].sudo().search([
    ('module', '=', 'l10n_il_hr_payroll'),
    ('name', '=', 'sign_template_form_101'),
]).unlink()

template = Form101._ensure_form_101_sign_template()
Form101.search([('sign_template_id', '=', False)]).write({
    'sign_template_id': template.id,
})
env.cr.commit()

print(
    'CREATED',
    'template=', template.id,
    'name=', repr(template.name),
    'documents=', template.document_ids.ids,
    'items=', len(template.sign_item_ids),
    'requests=', env['sign.request'].search_count([
        ('template_id', '=', template.id),
    ]),
)
