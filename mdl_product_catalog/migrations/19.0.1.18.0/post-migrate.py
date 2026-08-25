from odoo import SUPERUSER_ID, api


def _clean_text(value):
    return " ".join(str(value or "").split())


def migrate(cr, version):
    """Align existing automatic sale labels with the displayed product label."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["sale.order.line"].search(
        [
            ("display_type", "=", False),
            ("state", "in", ("draft", "sent", "sale")),
            ("product_id.mdl_generated_name", "!=", False),
        ]
    )
    for line in lines:
        description_lines = (line.name or "").splitlines()
        if not description_lines:
            continue
        generated_name = _clean_text(line.product_id.mdl_generated_name)
        if _clean_text(description_lines[0]) != generated_name:
            continue
        description_lines[0] = _clean_text(
            line.product_id.with_context(
                display_default_code=True,
            ).display_name
        )
        line.name = "\n".join(description_lines)
