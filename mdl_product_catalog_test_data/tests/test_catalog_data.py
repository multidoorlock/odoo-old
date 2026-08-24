from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.mdl_product_catalog_test_data.hooks import (
    MODULE,
    ODOO_DEMO_PRODUCT_XMLIDS,
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

    def test_filter_systems_use_four_native_templates(self):
        expected = {
            "40 - מערכת סינון — רב בריח — לביא PRO": 1,
            "40 - מערכת סינון — רב בריח — כפיר+": 11,
            "40 - מערכת סינון — בית אל — Rainbow": 1,
            "40 - מערכת סינון — בית אל — Hidden": 5,
        }
        active_variants = self.env["product.product"]
        for key, expected_count in expected.items():
            template = self.env.ref(
                f"{MODULE}.{_xmlid_name('template', key)}"
            )
            lines = template.attribute_line_ids.sorted(
                lambda line: (line.sequence, line.id)
            )
            self.assertEqual(
                [line.attribute_id.name for line in lines],
                ["קיבולת נפשות"],
            )
            variants = template.product_variant_ids.filtered("active")
            self.assertEqual(len(variants), expected_count)
            active_variants |= variants

        self.assertEqual(len(active_variants), 18)
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
                    for text in ("למרחב מוגן", 'לממ"מ', "בהתקנה")
                )
                for product in active_variants
            )
        )

    def test_white_mamad_wings_use_two_logical_templates(self):
        expected = {
            '1201 - כנף לדלת ממ"ד לבן — פתיחה רגילה': 22,
            '1201 - כנף לדלת ממ"ד לבן — הזזה': 16,
        }
        for key, expected_count in expected.items():
            template = self.env.ref(
                f"{MODULE}.{_xmlid_name('template', key)}"
            )
            self.assertEqual(
                [
                    line.attribute_id.name
                    for line in template.attribute_line_ids.sorted(
                        lambda line: (line.sequence, line.id)
                    )
                ],
                ["צורת פתיחה לדלת", "פתח אור לדלת", "גובה כנף"],
            )
            self.assertEqual(
                len(template.product_variant_ids.filtered("active")),
                expected_count,
            )

    def test_master_product_categories_have_no_test_parent(self):
        category_xmlids = self.env["ir.model.data"].search(
            [("module", "=", MODULE), ("model", "=", "product.category")]
        )
        categories = self.env["product.category"].browse(
            category_xmlids.mapped("res_id")
        ).exists()
        self.assertTrue(categories)
        self.assertFalse(categories.mapped("parent_id"))
        self.assertFalse(
            category_xmlids.filtered(
                lambda item: item.name == _xmlid_name("category", "test_root")
            )
        )

    def test_basic_odoo_demo_products_are_archived(self):
        xmlids = self.env["ir.model.data"].search(
            [
                ("module", "=", "product"),
                ("name", "in", ODOO_DEMO_PRODUCT_XMLIDS),
                ("model", "in", ("product.product", "product.template")),
            ]
        )
        product_xmlids = xmlids.filtered(
            lambda item: item.model == "product.product"
        )
        template_xmlids = xmlids.filtered(
            lambda item: item.model == "product.template"
        )
        products = self.env["product.product"].with_context(
            active_test=False
        ).browse(product_xmlids.mapped("res_id")).exists()
        templates = (
            products.product_tmpl_id
            | self.env["product.template"].with_context(
                active_test=False
            ).browse(template_xmlids.mapped("res_id")).exists()
        )
        self.assertTrue(all(not template.active for template in templates))

    def test_filter_technical_data_is_on_the_final_variant(self):
        product = self.env["product.product"].search(
            [("default_code", "=", "402501")], limit=1
        )
        self.assertTrue(product)
        self.assertEqual(product.mdl_generated_name, "מערכת סינון רב בריח כפיר+ 25 נפשות")
        self.assertEqual(product.mdl_max_protected_area_m2, 10.0)
        self.assertEqual(product.mdl_installation_type, "overhead")
