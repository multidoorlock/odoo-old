Form101 = env['hr.employee.form.101'].sudo()
form_model = env['ir.model']._get('hr.employee.form.101')
templates = env['sign.template'].sudo().with_context(active_test=False).search([
    '|',
    ('model_id', '=', form_model.id),
    ('name', 'ilike', '101'),
])
for template in templates:
    print(
        'TEMPLATE', template.id, repr(template.name),
        'active=', template.active,
        'model=', template.model_id.model,
        'documents=', template.document_ids.ids,
        'items=', len(template.sign_item_ids),
        'requests=', len(template.sign_request_ids),
    )
    for document in template.document_ids:
        named = document.sign_item_ids.filtered('name')
        radios = document.sign_item_ids.filtered(
            lambda item: item.type_id.item_type == 'radio')
        print(
            ' DOCUMENT', document.id,
            'pages=', document.num_pages,
            'items=', len(document.sign_item_ids),
            'named=', len(named),
            'radios=', len(radios),
            'radio_sets=', len(radios.radio_set_id),
        )
