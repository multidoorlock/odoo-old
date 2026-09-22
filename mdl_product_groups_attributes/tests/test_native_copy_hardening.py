from odoo.exceptions import UserError
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

    def test_category_selection_updates_group_sources(self):
        second_category = self.env["product.category"].create(
            {"name": "חלון", "mdl_sku_component": "20"}
        )
        ordinary = self.env["product.template"].create(
            {"name": "מוצר רגיל", "categ_id": self.category.id}
        )

        ordinary.write({"mdl_catalog_managed": True})

        self.assertEqual(ordinary.mdl_group_default_name, "דלת")
        self.assertEqual(ordinary.mdl_group_default_sku, "10")
        ordinary.categ_id = second_category
        self.assertEqual(ordinary.mdl_group_default_name, "חלון")
        self.assertEqual(ordinary.mdl_group_default_sku, "20")

        implicit = self.env["product.template"].create(
            {"name": "מוצר נוסף", "categ_id": second_category.id}
        )
        implicit.write({"mdl_group_name_override": "קבוצה מיוחדת"})
        self.assertTrue(implicit.mdl_catalog_managed)
        self.assertEqual(implicit.mdl_group_default_name, "חלון")
        self.assertEqual(implicit.mdl_group_default_sku, "20")

        explicit = self.env["product.template"].create(
            {"name": "מקור מפורש", "categ_id": self.category.id}
        )
        explicit.write(
            {
                "mdl_catalog_managed": True,
                "mdl_group_default_name": "מקור ידני",
                "mdl_group_default_sku": "77",
            }
        )
        self.assertEqual(explicit.mdl_group_default_name, "מקור ידני")
        self.assertEqual(explicit.mdl_group_default_sku, "77")

        first_bulk = self.env["product.template"].create(
            {"name": "ראשון", "categ_id": self.category.id}
        )
        second_bulk = self.env["product.template"].create(
            {"name": "שני", "categ_id": second_category.id}
        )
        (first_bulk | second_bulk).write({"mdl_catalog_managed": True})
        self.assertEqual(first_bulk.mdl_group_default_name, "דלת")
        self.assertEqual(first_bulk.mdl_group_default_sku, "10")
        self.assertEqual(second_bulk.mdl_group_default_name, "חלון")
        self.assertEqual(second_bulk.mdl_group_default_sku, "20")

    def test_catalog_toggle_preserves_configuration_and_rebuilds_names(self):
        template = self._managed_template()
        template._mdl_convert_models_to_attributes()
        variants = template.with_context(active_test=False).product_variant_ids
        original_names = {
            product.id: product.mdl_generated_name for product in variants
        }
        original_codes = {
            product.id: product.default_code for product in variants
        }
        original_sources = (
            template.mdl_group_default_name,
            template.mdl_group_default_sku,
        )

        template.mdl_catalog_managed = False

        self.assertEqual(
            (
                template.mdl_group_default_name,
                template.mdl_group_default_sku,
            ),
            original_sources,
        )
        self.assertTrue(all(not product.mdl_generated_name for product in variants))
        self.assertEqual(
            {product.id: product.default_code for product in variants},
            original_codes,
        )

        template.mdl_catalog_managed = True

        self.assertEqual(
            {product.id: product.mdl_generated_name for product in variants},
            original_names,
        )
        self.assertEqual(
            {product.id: product.default_code for product in variants},
            original_codes,
        )

    def test_display_title_is_independent_from_variant_source_and_copy(self):
        template = self._managed_template()
        original = {
            product.id: (product.default_code, product.mdl_generated_name)
            for product in template.product_variant_ids
        }
        source_name = template.mdl_group_default_name

        template.name = "שם Odoo מותאם"
        self.assertEqual(template.name, "שם Odoo מותאם")
        self.assertEqual(template.mdl_effective_base_name, source_name)
        self.assertFalse(template.mdl_native_name_override)
        self.assertEqual(
            {
                product.id: (product.default_code, product.mdl_generated_name)
                for product in template.product_variant_ids
            },
            original,
        )

        copied = template.copy()
        copied_title = "שם Odoo מותאם (copy)"
        self.assertEqual(copied.name, copied_title)
        self.assertEqual(copied.mdl_group_default_name, source_name)
        self.assertEqual(copied.mdl_effective_base_name, source_name)
        self.assertFalse(copied.mdl_native_name_override)
        self.assertTrue(copied.mdl_copy_requires_new_sku)
        self.assertTrue(all(not p.default_code for p in copied.product_variant_ids))
        self.assertEqual(
            set(copied.product_variant_ids.mapped("mdl_generated_name")),
            {name for code, name in original.values()},
        )
        copied_ids = copied.product_variant_ids.ids

        copied.mdl_effective_base_name = "בסיס ערוך בעותק"
        self.assertEqual(copied.mdl_group_default_name, "בסיס ערוך בעותק")
        self.assertEqual(copied.name, copied_title)
        self.assertEqual(copied.product_variant_ids.ids, copied_ids)
        self.assertTrue(
            all(
                name.startswith("בסיס ערוך בעותק")
                for name in copied.product_variant_ids.mapped(
                    "mdl_generated_name"
                )
            )
        )
        self.assertEqual(template.mdl_group_default_name, source_name)

        copied.mdl_effective_base_name = False
        self.assertFalse(copied.mdl_group_default_name)
        self.assertFalse(copied.mdl_effective_base_name)
        copied.action_mdl_reset_base_name()
        self.assertFalse(copied.mdl_effective_base_name)
        self.assertEqual(copied.name, copied_title)
        self.assertTrue(copied.mdl_copy_requires_new_sku)
        self.assertTrue(all(not p.default_code for p in copied.product_variant_ids))

        explicitly_named = template.copy({"name": "שם העתק מפורש"})
        self.assertEqual(explicitly_named.name, "שם העתק מפורש")
        self.assertEqual(explicitly_named.mdl_group_default_name, source_name)
        self.assertEqual(explicitly_named.mdl_effective_base_name, source_name)

        template.action_mdl_reset_base_name()
        template.action_mdl_reset_base_values()
        self.assertEqual(template.name, "שם Odoo מותאם")
        self.assertEqual(template.mdl_group_default_name, source_name)
        self.assertEqual(
            {
                product.id: (product.default_code, product.mdl_generated_name)
                for product in template.product_variant_ids
            },
            original,
        )

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

    def test_group_only_multi_model_line_keeps_native_line_configuration(self):
        model_attribute = self.env["product.attribute"].create(
            {"name": "דגם", "create_variant": "always"}
        )
        first_model = self.env["product.attribute.value"].create(
            {"name": "ראשון", "attribute_id": model_attribute.id}
        )
        second_model = self.env["product.attribute.value"].create(
            {"name": "שני", "attribute_id": model_attribute.id}
        )
        template = self.env["product.template"].create(
            {
                "name": "דלת",
                "categ_id": self.category.id,
                "mdl_group_default_name": "דלת",
                "mdl_group_default_sku": "10",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": model_attribute.id,
                            "sequence": 37,
                            "mdl_name_suffix": " / ",
                            "value_ids": [
                                Command.set((first_model | second_model).ids)
                            ],
                        }
                    )
                ],
            }
        )
        model_line = template.attribute_line_ids
        values_before = set(model_line.value_ids.ids)
        product_ids_before = set(
            template.with_context(active_test=False).product_variant_ids.ids
        )
        line_state_before = (
            model_line.active,
            model_line.sequence,
            model_line.mdl_name_suffix,
        )

        template._mdl_convert_models_to_attributes()

        self.assertTrue(model_line.mdl_is_model_attribute)
        self.assertEqual(set(model_line.value_ids.ids), values_before)
        self.assertEqual(
            set(template.with_context(active_test=False).product_variant_ids.ids),
            product_ids_before,
        )
        self.assertEqual(
            (
                model_line.active,
                model_line.sequence,
                model_line.mdl_name_suffix,
            ),
            line_state_before,
        )
        self.assertFalse(
            model_line.product_template_value_ids.filtered(
                lambda value: (
                    value.mdl_name_component_override
                    or value.mdl_sku_component_override
                )
            )
        )

    def test_duplicate_normalized_global_model_values_fail_before_conversion(self):
        model_attribute = self.env["product.template"]._mdl_get_model_attribute()
        unique_model_name = "Native Duplicate Guard 93817"
        self.env["product.attribute.value"].create(
            [
                {
                    "name": unique_model_name.upper(),
                    "attribute_id": model_attribute.id,
                },
                {
                    "name": unique_model_name.lower(),
                    "attribute_id": model_attribute.id,
                },
            ]
        )
        first = self.env["product.template"].create(
            {
                "name": f"דלת {unique_model_name}",
                "categ_id": self.category.id,
                "mdl_group_default_name": "דלת",
            }
        )
        second = self._managed_template()

        with self.assertRaises(UserError):
            (second | first)._mdl_convert_models_to_attributes()

        self.assertFalse(first.mdl_model_as_attribute)
        self.assertFalse(second.mdl_model_as_attribute)

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

        copied.mdl_group_default_sku = "10"
        self.assertTrue(copied.mdl_copy_requires_new_sku)
        self.assertEqual(
            set(copied.product_variant_ids.mapped("default_code")),
            {False},
        )
        copied.mdl_group_sku_override = "10"
        copied.mdl_group_default_sku = "99"
        self.assertTrue(copied.mdl_copy_requires_new_sku)
        self.assertEqual(copied.mdl_group_sku_value, "10")

        copied.mdl_group_sku_override = "20"
        self.assertFalse(copied.mdl_copy_requires_new_sku)
        self.assertFalse(copied.mdl_copy_source_group_sku)
        self.assertEqual(copied.mdl_group_default_sku, "20")
        self.assertFalse(copied.mdl_group_sku_override)
        copied_codes = set(
            copied.with_context(active_test=False)
            .product_variant_ids.mapped("default_code")
        )
        self.assertNotIn(False, copied_codes)
        self.assertFalse(source_codes & copied_codes)
        copied.action_mdl_reset_base_sku()
        self.assertEqual(copied.mdl_group_default_sku, "20")
        self.assertFalse(copied.mdl_group_sku_override)
        self.assertEqual(
            set(copied.product_variant_ids.mapped("default_code")),
            copied_codes,
        )

        copied_with_sku = template.copy({"mdl_group_default_sku": "30"})
        self.assertFalse(copied_with_sku.mdl_copy_requires_new_sku)
        self.assertFalse(
            source_codes
            & set(copied_with_sku.product_variant_ids.mapped("default_code"))
        )
        same_source_copy = template.copy({"mdl_group_default_sku": "10"})
        self.assertTrue(same_source_copy.mdl_copy_requires_new_sku)
        self.assertEqual(
            set(same_source_copy.product_variant_ids.mapped("default_code")),
            {False},
        )

        source_with_override = self._managed_template()
        source_with_override._mdl_convert_models_to_attributes()
        source_with_override.mdl_group_sku_override = "15"
        explicit_source_copy = source_with_override.copy(
            {"mdl_group_default_sku": "30"}
        )
        self.assertFalse(explicit_source_copy.mdl_copy_requires_new_sku)
        self.assertEqual(explicit_source_copy.mdl_group_default_sku, "30")
        self.assertFalse(explicit_source_copy.mdl_group_sku_override)

        explicit_override_copy = template.copy(
            {"mdl_group_sku_override": "40"}
        )
        self.assertFalse(explicit_override_copy.mdl_copy_requires_new_sku)
        self.assertEqual(explicit_override_copy.mdl_group_default_sku, "40")
        self.assertFalse(explicit_override_copy.mdl_group_sku_override)
