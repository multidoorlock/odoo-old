import fitz


pdf_path = r'C:\odoo\odoo-19\project\l10n_il_hr_payroll\static\src\pdf\form_101.pdf'
output_path = r'C:\odoo\odoo-19\project\tmp\pdfs\form101_sign_overlay.pdf'

template = env.ref('l10n_il_hr_payroll.sign_template_form_101')
document = template.document_ids[:1]
pdf = fitz.open(pdf_path)

for item in document.sign_item_ids.filtered(lambda record: record.page in (1, 2)):
    page = pdf[item.page - 1]
    page_rect = page.rect
    rect = fitz.Rect(
        item.posX * page_rect.width,
        item.posY * page_rect.height,
        (item.posX + item.width) * page_rect.width,
        (item.posY + item.height) * page_rect.height,
    )
    is_signature = item.type_id.item_type == 'signature'
    color = (0.8, 0.0, 0.0) if is_signature else (0.0, 0.25, 0.9)
    page.draw_rect(rect, color=color, fill=color, fill_opacity=0.12, width=0.45)
    label = item.name or item.type_id.name
    page.insert_textbox(
        rect,
        label,
        fontsize=3.2 if not is_signature else 5,
        color=color,
        align=fitz.TEXT_ALIGN_LEFT,
    )

pdf.save(output_path)
for index, page in enumerate(pdf):
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    pixmap.save(
        rf'C:\odoo\odoo-19\project\tmp\pdfs\form101_sign_overlay_p{index + 1}.png')

print('OVERLAY', output_path, 'ITEMS', len(document.sign_item_ids))
