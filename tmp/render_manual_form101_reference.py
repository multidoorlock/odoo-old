import base64
import os

import fitz


template = env['sign.template'].sudo().search([
    ('name', 'ilike', '101'),
    ('active', '=', True),
], order='id desc', limit=1)
document = template.document_ids[:1]
output_dir = r'C:\odoo\odoo-19\project\tmp\pdfs\manual_form101_reference'
os.makedirs(output_dir, exist_ok=True)
pdf = fitz.open(stream=base64.b64decode(document.datas), filetype='pdf')

colors = {
    'text': (0.0, 0.25, 0.9),
    'signature': (0.8, 0.0, 0.0),
    'checkbox': (0.0, 0.55, 0.2),
    'radio': (0.55, 0.0, 0.75),
}
for item in document.sign_item_ids.filtered(lambda record: record.page in (1, 2)):
    page = pdf[item.page - 1]
    rect = fitz.Rect(
        item.posX * page.rect.width,
        item.posY * page.rect.height,
        (item.posX + item.width) * page.rect.width,
        (item.posY + item.height) * page.rect.height,
    )
    item_type = item.type_id.item_type
    color = colors.get(item_type, (0.8, 0.4, 0.0))
    page.draw_rect(rect, color=color, fill=color, fill_opacity=0.10, width=0.45)
    page.insert_textbox(
        rect, str(item.id), fontsize=3.4, color=color,
        align=fitz.TEXT_ALIGN_LEFT,
    )

for index, page in enumerate(pdf):
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    pixmap.save(os.path.join(output_dir, f'page_{index + 1}.png'))
pdf.save(os.path.join(output_dir, 'manual_reference.pdf'))
print('REFERENCE', template.id, len(document.sign_item_ids), output_dir)
