from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestProductCatalog(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env["product.category"].create(
            {"name": "דלת", "mdl_group_code": "10"}
        )
        cls.width = cls.env["product.attribute"].create(
            {"name": "רוחב", "create_variant": "always"}
        )
        cls.height = cls.env["product.attribute"].create(
            {"name": "גובה", "create_variant": "always"}
        )
        cls.width_80 = cls.env["product.attribute.value"].create(
            {
                "name": "80",
                "attribute_id": cls.width.id,
                "mdl_sku_component": "80",
            }
        )
        cls.width_90 = cls.env["product.attribute.value"].create(
            {
                "name": "90",
                "attribute_id": cls.width.id,
                "mdl_sku_component": "90",
            }
        )
        cls.height_100 = cls.env["product.attribute.value"].create(
            {
                "name": "100",
                "attribute_id": cls.height.id,
                "mdl_sku_component": "100",
            }
        )

    def _create_template(self):
        return self.env["product.template"].create(
            {
                "name": "כנף",
                "categ_id": self.category.id,
                "mdl_model_code": "01",
                "mdl_name_format": "[שם קבוצת פריטים] [דגם] [רוחב]/[גובה] +ידית",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.width.id,
                            "value_ids": [Command.set([self.width_80.id, self.width_90.id])],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": self.height.id,
                            "value_ids": [Command.set([self.height_100.id])],
                        }
                    ),
                ],
            }
        )

    def test_generates_sku_and_name_from_format(self):
        template = self._create_template()
        self.assertEqual(len(template.product_variant_ids), 2)
        by_width = {
            product.product_template_attribute_value_ids.filtered(
                lambda value: value.attribute_id == self.width
            ).product_attribute_value_id.name: product
            for product in template.product_variant_ids
        }
        self.assertEqual(by_width["80"].mdl_generated_sku, "100180100")
        self.assertEqual(by_width["80"].default_code, "100180100")
        self.assertEqual(
            by_width["80"].mdl_generated_name,
            "דלת כנף 80/100 +ידית",
        )

    def test_model_specific_name_override(self):
        template = self._create_template()
        template.mdl_template_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        ).mdl_name_component_override = "80 ס״מ"
        product = template.product_variant_ids.filtered(
            lambda variant: self.width_80
            in variant.product_template_attribute_value_ids.product_attribute_value_id
        )
        self.assertEqual(product.mdl_generated_name, "דלת כנף 80 ס״מ/100 +ידית")

    def test_unknown_token_is_reported(self):
        template = self._create_template()
        template.mdl_name_format = "[שם קבוצת פריטים] [דגם] [צבע]"
        self.assertEqual(template.mdl_catalog_status, "error")
        self.assertIn("[צבע]", template.mdl_catalog_errors)

