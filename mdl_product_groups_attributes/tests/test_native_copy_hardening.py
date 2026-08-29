from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestNativeCopyHardening(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env["product.category"].create(
            {"name": "דלת", "mdl_sku_component": "10"}
        )
        cls.width = cls.env["product.attribute"].create(
            {"name": "רוחב הקשחה", "create_variant": "always"}
        )
        cls.height = cls.env["product.attribute"].create(
            {"name": "גובה הקשחה", "create_variant": "always"}
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

    def _managed_template(self):
        return self.env["product.template"].create(
            {
                "name": "כנף",
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

    def test_category_code_does_not_manage_an_ordinary_odoo_product(self):
        ordinary = self.env["product.template"].create(
            {"name": "מוצר Odoo רגיל", "categ_id": self.category.id}
        )
        self.assertFalse(ordinary.mdl_catalog_managed)
        self.assertFalse(ordinary.mdl_group_default_name)
        self.assertFalse(ordinary.mdl_group_default_sku)
        ordinary.write(
            {
                "mdl_group_name_override": False,
                "mdl_group_sku_override": False,
                "mdl_model_name_override": False,
                "mdl_model_sku_override": False,
            }
        )
        self.assertFalse(ordinary.mdl_catalog_managed)
        ordinary.name = "שם Odoo רגיל מעודכן"
        self.assertFalse(ordinary.mdl_native_name_override)

        explicitly_managed = self.env["product.template"].create(
            {
                "name": "קבוצה מפורשת",
                "categ_id": self.category.id,
                "mdl_catalog_managed": True,
            }
        )
        self.assertTrue(explicitly_managed.mdl_catalog_managed)
        self.assertEqual(explicitly_managed.mdl_group_default_name, "דלת")
        self.assertEqual(explicitly_managed.mdl_group_default_sku, "10")

        managed_by_catalog_field = self.env["product.template"].create(
            {
                "name": "קבוצה עם מקור",
                "categ_id": self.category.id,
                "mdl_group_default_name": "מקור מפורש",
            }
        )
        self.assertTrue(managed_by_catalog_field.mdl_catalog_managed)

        explicitly_native = self.env["product.template"].create(
            {
                "name": "נשאר רגיל",
                "categ_id": self.category.id,
                "mdl_catalog_managed": False,
                "mdl_group_default_sku": "99",
            }
        )
        self.assertFalse(explicitly_native.mdl_catalog_managed)

    def test_native_name_drives_variants_reset_and_copy(self):
        legacy_template = self._managed_template()
        legacy_template.name = "שם מותאם לפני המרה"
        self.assertEqual(
            legacy_template.mdl_effective_base_name,
            "שם מותאם לפני המרה",
        )
        legacy_template.action_mdl_reset_base_name()
        self.assertEqual(legacy_template.name, "דלת כנף")
        self.assertFalse(legacy_template.mdl_native_name_override)
        self.assertFalse(legacy_template.mdl_native_name_source)

        template = self._managed_template()
        template._mdl_convert_models_to_attributes()

        template.name = "שם Odoo מותאם"
        self.assertEqual(template.mdl_native_name_override, "שם Odoo מותאם")
        self.assertEqual(template.mdl_effective_base_name, "שם Odoo מותאם")
        self.assertTrue(
            all(
                name.startswith("שם Odoo מותאם")
                for name in template.product_variant_ids.mapped(
                    "mdl_generated_name"
                )
            )
        )

        copied = template.copy()
        self.assertEqual(copied.name, "שם Odoo מותאם (copy)")
        self.assertEqual(copied.mdl_native_name_override, copied.name)
        self.assertEqual(copied.mdl_effective_base_name, copied.name)

        explicitly_named = template.copy({"name": "שם העתק מפורש"})
        self.assertEqual(explicitly_named.name, "שם העתק מפורש")
        self.assertEqual(
            explicitly_named.mdl_effective_base_name,
            "שם העתק מפורש",
        )

        template.action_mdl_reset_base_name()
        self.assertFalse(template.mdl_native_name_override)
        self.assertEqual(template.name, "דלת כנף")
        self.assertEqual(template.mdl_effective_base_name, "דלת")

        template.name = "התאמה נוספת"
        template.action_mdl_reset_base_values()
        self.assertFalse(template.mdl_native_name_override)
        self.assertEqual(template.name, "דלת כנף")
        self.assertEqual(template.mdl_effective_base_name, "דלת")

    def test_copy_preserves_exact_legacy_blocked_combination(self):
        template = self._managed_template()
        blocked = template.product_variant_ids.filtered(
            lambda product: self.width_90 in (
                product.product_template_attribute_value_ids
                .product_attribute_value_id
            )
        )
        blocked.with_context(skip_mdl_catalog_sync=True).write(
            {"mdl_catalog_allowed": False, "active": False}
        )

        copied = template.copy()
        copied_variants = copied.with_context(
            active_test=False
        ).product_variant_ids
        copied_blocked = copied_variants.filtered(
            lambda product: self.width_90 in (
                product.product_template_attribute_value_ids
                .product_attribute_value_id
            )
        )

        self.assertEqual(len(copied_blocked), 1)
        self.assertFalse(copied_blocked.mdl_catalog_allowed)
        self.assertFalse(copied_blocked.active)

    def test_copy_defaults_can_replace_structure_or_disable_catalog(self):
        template = self._managed_template()
        source_values = template.mdl_attribute_value_ids
        self.env["product.template.attribute.exclusion"].with_context(
            mdl_skip_combination_sync=True
        ).create(
            {
                "product_tmpl_id": template.id,
                "mdl_is_catalog_condition": True,
                "mdl_rule_type": "forbidden",
                "mdl_combination_value_ids": [
                    Command.set(
                        source_values.filtered(
                            lambda value: value.product_attribute_value_id
                            in (self.width_90 | self.height_100)
                        ).ids
                    )
                ],
            }
        )

        changed = template.copy(
            {
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.width.id,
                            "value_ids": [Command.set(self.width_80.ids)],
                        }
                    )
                ]
            }
        )
        self.assertEqual(changed.attribute_line_ids.attribute_id, self.width)
        self.assertFalse(
            changed.mdl_exclusion_ids.filtered("mdl_is_catalog_condition")
        )

        native_copy = template.copy({"mdl_catalog_managed": False})
        self.assertFalse(native_copy.mdl_catalog_managed)
        self.assertFalse(
            native_copy.mdl_exclusion_ids.filtered("mdl_is_catalog_condition")
        )

    def test_conversion_reuses_matching_value_on_multi_model_line(self):
        model_attribute = self.env["product.attribute"].create(
            {"name": "דגם", "create_variant": "always"}
        )
        wing = self.env["product.attribute.value"].create(
            {
                "name": "כנף",
                "attribute_id": model_attribute.id,
                "mdl_sku_component": "11",
            }
        )
        frame = self.env["product.attribute.value"].create(
            {
                "name": "משקוף",
                "attribute_id": model_attribute.id,
                "mdl_sku_component": "12",
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "דלת כנף",
                "categ_id": self.category.id,
                "mdl_group_default_name": "דלת",
                "mdl_group_default_sku": "10",
                "mdl_model_sku_component": "01",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": model_attribute.id,
                            "value_ids": [Command.set((wing | frame).ids)],
                        }
                    )
                ],
            }
        )
        model_line = template.attribute_line_ids
        value_ids_before = set(model_line.value_ids.ids)
        product_ids_before = set(
            template.with_context(active_test=False).product_variant_ids.ids
        )

        template._mdl_convert_models_to_attributes()

        self.assertEqual(set(model_line.value_ids.ids), value_ids_before)
        self.assertEqual(
            set(template.with_context(active_test=False).product_variant_ids.ids),
            product_ids_before,
        )
        self.assertTrue(model_line.mdl_is_model_attribute)
        wing_template_value = model_line.product_template_value_ids.filtered(
            lambda value: value.product_attribute_value_id == wing
        )
        frame_template_value = model_line.product_template_value_ids.filtered(
            lambda value: value.product_attribute_value_id == frame
        )
        self.assertEqual(wing_template_value.mdl_sku_component_override, "01")
        self.assertFalse(frame_template_value.mdl_sku_component_override)

    def test_duplicate_codes_wait_for_a_distinct_group_sku(self):
        template = self._managed_template()
        template._mdl_convert_models_to_attributes()
        source_codes = set(template.product_variant_ids.mapped("default_code"))
        self.assertNotIn(False, source_codes)

        copied = template.copy()
        self.assertTrue(copied.mdl_copy_requires_new_sku)
        self.assertEqual(
            set(
                copied.with_context(active_test=False)
                .product_variant_ids.mapped("default_code")
            ),
            {False},
        )
        copied.attribute_line_ids[:1].sequence += 1
        self.assertEqual(
            set(
                copied.with_context(active_test=False)
                .product_variant_ids.mapped("default_code")
            ),
            {False},
        )

        copied.mdl_group_sku_override = "20"
        self.assertFalse(copied.mdl_copy_requires_new_sku)
        copied_codes = set(
            copied.with_context(active_test=False)
            .product_variant_ids.mapped("default_code")
        )
        self.assertNotIn(False, copied_codes)
        self.assertFalse(source_codes & copied_codes)

        copied_with_sku = template.copy({"mdl_group_default_sku": "30"})
        self.assertFalse(copied_with_sku.mdl_copy_requires_new_sku)
        self.assertFalse(
            source_codes
            & set(copied_with_sku.product_variant_ids.mapped("default_code"))
        )
