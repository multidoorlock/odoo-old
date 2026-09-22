templates = env['sign.template'].with_context(active_test=False).search([
    ('name', 'ilike', '101'),
])
print('TEMPLATE_COUNT', len(templates))
for template in templates:
    print(
        'TEMPLATE', template.id,
        repr(template.name),
        'active=', template.active,
        'model=', template.model_id.model,
        'xmlids=', template.get_external_id().get(template.id),
        'documents=', template.document_ids.ids,
        'items=', len(template.sign_item_ids),
        'requests=', env['sign.request'].search_count([
            ('template_id', '=', template.id),
        ]),
    )
