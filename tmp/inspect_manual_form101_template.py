templates = env['sign.template'].sudo().with_context(active_test=False).search([
    ('name', 'ilike', '101'),
])
print('TEMPLATES', len(templates), templates.ids)
for template in templates:
    print(
        'TEMPLATE', template.id, repr(template.name),
        'active=', template.active,
        'model=', template.model_id.model,
        'requests=', len(template.sign_request_ids),
        'documents=', template.document_ids.ids,
    )
    for item in template.sign_item_ids.sorted(lambda record: (record.page, record.posY, record.posX)):
        print(
            'ITEM', item.id,
            'page=', item.page,
            'type=', item.type_id.item_type,
            'type_id=', item.type_id.id,
            'type_name=', repr(item.type_id.name),
            'auto_field=', repr(item.type_id.auto_field),
            'role=', repr(item.responsible_id.name),
            'required=', item.required,
            'x=', round(item.posX * 210, 3),
            'y=', round(item.posY * 297, 3),
            'w=', round(item.width * 210, 3),
            'h=', round(item.height * 297, 3),
            'radio_set=', item.radio_set_id.id,
        )
