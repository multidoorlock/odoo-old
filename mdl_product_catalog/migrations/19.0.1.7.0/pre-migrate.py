def migrate(cr, version):
    """Create and seed the split group/model columns before ORM recomputation."""
    cr.execute(
        """
        ALTER TABLE product_category
            ADD COLUMN IF NOT EXISTS mdl_sku_component varchar
        """
    )
    cr.execute(
        """
        ALTER TABLE product_template
            ADD COLUMN IF NOT EXISTS mdl_group_name_override varchar,
            ADD COLUMN IF NOT EXISTS mdl_group_sku_override varchar,
            ADD COLUMN IF NOT EXISTS mdl_model_sku_component varchar,
            ADD COLUMN IF NOT EXISTS mdl_model_name_override varchar,
            ADD COLUMN IF NOT EXISTS mdl_model_sku_override varchar,
            ADD COLUMN IF NOT EXISTS mdl_effective_base_name varchar
        """
    )
    cr.execute(
        """
        UPDATE product_category category
           SET mdl_sku_component = source.group_sku
          FROM (
                SELECT DISTINCT ON (categ_id)
                       categ_id,
                       substring(mdl_sku_prefix FROM 1 FOR 2) AS group_sku
                  FROM product_template
                 WHERE COALESCE(mdl_sku_prefix, '') <> ''
                 ORDER BY categ_id, id
               ) source
         WHERE category.id = source.categ_id
           AND COALESCE(category.mdl_sku_component, '') = ''
        """
    )
    cr.execute(
        """
        UPDATE product_template
           SET mdl_model_sku_component = substring(mdl_sku_prefix FROM 3)
         WHERE COALESCE(mdl_sku_prefix, '') <> ''
           AND COALESCE(mdl_model_sku_component, '') = ''
        """
    )
