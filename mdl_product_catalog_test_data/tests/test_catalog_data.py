from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.mdl_product_catalog_test_data.hooks import (
    MODULE,
    _xmlid_name,
)


@tagged("post_install", "-at_install")
class TestGeneratedCatalog(TransactionCase):
    def test_all_source_products_and_skus_are_loaded_once(self):
        template_xmlids = self.env["ir.model.data"].search(
            [("module", "=", MODULE), ("model", "=", "product.template")]
        )
        templates = self.env["product.template"].with_context(
            active_test=False
        ).browse(template_xmlids.mapped("res_id")).exists()
        active_products = templates.product_variant_ids.filtered("active")

        self.assertEqual(len(active_products), 1274)
        self.assertEqual(len(set(active_products.mapped("default_code"))), 1274)
        self.assertTrue(all(active_products.mapped("default_code")))

    def test_filter_systems_use_one_native_template(self):
        template = self.env.ref(
            f"{MODULE}.{_xmlid_name('template', '40 - מערכת סינון')}"
        )
        lines = template.attribute_line_ids.sorted(
            lambda line: (line.sequence, line.id)
        )
        self.assertEqual(template.name, "מערכת סינון")
        self.assertEqual(
            [line.attribute_id.name for line in lines],
            ["קיבולת נפשות", "חברה", "דגם מערכת סינון"],
        )

        all_variants = template.with_context(
            active_test=False
        ).product_variant_ids
        active_variants = all_variants.filtered("active")
        self.assertEqual(len(all_variants), 120)
        self.assertEqual(len(active_variants), 18)
        self.assertEqual(
            len(all_variants.filtered(lambda item: not item.mdl_catalog_allowed)),
            102,
        )

        expected_skus = {
            "400601", "400609", "402501", "403001", "403309", "404001",
            "405001", "405009", "406001", "406609", "408001", "408309",
            "4010001", "4010009", "4012001", "4015001", "4016001",
            "4020001",
        }
        self.assertEqual(set(active_variants.mapped("default_code")), expected_skus)
        self.assertTrue(
            all(
                not any(
                    text in product.mdl_generated_name
                    for text in ("למרחב מוגן", "לממ\"מ", "בהתקנה")
                )
                for product in active_variants
            )
        )

    def test_filter_technical_data_is_on_the_final_variant(self):
        product = self.env["product.product"].search(
            [("default_code", "=", "402501")], limit=1
        )
        self.assertTrue(product)
        self.assertEqual(product.mdl_generated_name, "מערכת סינון 25 נפשות רב בריח כפיר+")
        self.assertEqual(product.mdl_max_protected_area_m2, 10.0)
        self.assertEqual(product.mdl_installation_type, "overhead")
