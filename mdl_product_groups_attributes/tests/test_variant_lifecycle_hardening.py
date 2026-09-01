from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestVariantLifecycleHardening(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env["product.category"].create(
            {"name": "Lifecycle", "mdl_sku_component": "10"}
        )
        cls.width = cls.env["product.attribute"].create(
            {"name": "Lifecycle Width", "create_variant": "always"}
        )
        cls.height = cls.env["product.attribute"].create(
            {"name": "Lifecycle Height", "create_variant": "always"}
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
                "name": "Panel",
                "categ_id": self.category.id,
                "mdl_model_sku_component": "01",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.width.id,
                            "sequence": 10,
                            "value_ids": [
                                Command.set((self.width_80 | self.width_90).ids)
                            ],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": self.height.id,
                            "sequence": 20,
                            "value_ids": [Command.set(self.height_100.ids)],
                        }
                    ),
                ],
            }
        )

    def _template_value(self, template, attribute_value):
        return template.attribute_line_ids.product_template_value_ids.filtered(
            lambda value: value.product_attribute_value_id == attribute_value
        )

    def test_archived_variant_reference_is_updated_and_repaired_on_unarchive(self):
        template = self._create_template()
        product = template.product_variant_ids.filtered(
            lambda variant: self.width_80
            in variant.product_template_attribute_value_ids.product_attribute_value_id
        )
        product.active = False

        self.width_80.mdl_sku_component = "080"
        self.assertEqual(product.default_code, "1001080100")

        product.with_context(skip_mdl_catalog_sync=True).default_code = "STALE"
        product.active = True
        self.assertEqual(product.default_code, "1001080100")

    def test_preserve_variant_ids_keeps_native_access_contract(self):
        template = self._create_template()
        product = template.product_variant_ids[:1]
        restricted_user = new_test_user(
            self.env,
            login="variant_lifecycle_portal",
            groups="base.group_portal",
        )
        restricted_product = product.with_user(restricted_user).with_context(
            mdl_preserve_variant_ids=True
        )

        with self.assertRaises(AccessError):
            restricted_product._unlink_or_archive(check_access=True)
        self.assertTrue(product.active)

        restricted_product._unlink_or_archive(check_access=False)
        product.invalidate_recordset(["active"])
        self.assertFalse(product.active)

    def test_catalog_rule_survives_ptav_archive_and_reactivation(self):
        template = self._create_template()
        width_line = template.attribute_line_ids.filtered(
            lambda line: line.attribute_id == self.width
        )
        width_value = self._template_value(template, self.width_80)
        height_value = self._template_value(template, self.height_100)
        referenced_product = template.product_variant_ids.filtered(
            lambda variant: self.width_80
            in variant.product_template_attribute_value_ids.product_attribute_value_id
        )
        partner = self.env["res.partner"].create(
            {"name": "Lifecycle archive customer"}
        )
        self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    Command.create(
                        {
                            "product_id": referenced_product.id,
                            "product_uom_qty": 1,
                        }
                    )
                ],
            }
        )
        rule = self.env["product.template.attribute.exclusion"].create(
            {
                "product_tmpl_id": template.id,
                "mdl_is_catalog_condition": True,
                "mdl_rule_type": "forbidden",
                "mdl_combination_value_ids": [
                    Command.set((width_value | height_value).ids)
                ],
            }
        )
        rule_id = rule.id

        width_line.with_context(mdl_preserve_variant_ids=True).write(
            {"value_ids": [Command.unlink(self.width_80.id)]}
        )
        self.assertTrue(rule.exists())
        self.assertTrue(width_value.exists())
        self.assertFalse(width_value.ptav_active)

        width_line.value_ids = [Command.link(self.width_80.id)]
        self.assertEqual(rule.id, rule_id)
        self.assertTrue(rule.exists())
        self.assertTrue(width_value.ptav_active)
        self.assertEqual(
            rule.mdl_combination_value_ids,
            width_value | height_value,
        )
        self.assertEqual(
            rule.product_template_attribute_value_id | rule.value_ids,
            width_value | height_value,
        )

    def test_batch_duplicate_create_never_returns_deleted_rules(self):
        template = self._create_template()
        width_value = self._template_value(template, self.width_80)
        height_value = self._template_value(template, self.height_100)
        common = {
            "product_tmpl_id": template.id,
            "mdl_is_catalog_condition": True,
            "mdl_rule_type": "forbidden",
        }

        rules = self.env["product.template.attribute.exclusion"].create(
            [
                {
                    **common,
                    "mdl_combination_value_ids": [
                        Command.set((width_value | height_value).ids)
                    ],
                },
                {
                    **common,
                    "mdl_combination_value_ids": [
                        Command.set((height_value | width_value).ids)
                    ],
                },
            ]
        )

        self.assertEqual(len(rules), 2)
        self.assertEqual(rules, rules.exists())
