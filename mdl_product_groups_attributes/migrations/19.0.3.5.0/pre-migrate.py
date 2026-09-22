"""Make the visible group-name field the sole variant-name source.

This pre-phase must run before the new registry computes managed names. The old
renderer reads the stored effective base, which can legitimately differ from a
fresh evaluation of legacy overrides. Preserve that actual displayed value,
including translated fallbacks and blank values. The frozen 19.0.3.4.9 formula
is retained for diagnostics and inputs predating the stored field. Only
``mdl_group_default_name`` is updated. Titles, legacy overrides, generated names,
SKUs and links are untouched.
"""
import json
import logging


_logger = logging.getLogger(__name__)
_SOURCE_COLUMNS = (
    "name",
    "mdl_group_default_name",
    "mdl_group_name_override",
    "mdl_model_name_override",
    "mdl_native_name_override",
)
_STORED_BASE_COLUMN = "mdl_effective_base_name"


def _clean_text(value):
    # Keep byte-for-byte parity with the pre-upgrade catalog_utils.clean_text.
    if value in (None, False):
        return ""
    return " ".join(str(value).split())


def _translated(value, language):
    """Odoo JSON translations fall back per field, not per assembled name."""
    if not isinstance(value, dict):
        return value
    translated = value.get(language)
    # An explicit empty string is a translation; JSON null/missing falls back.
    return value.get("en_US") if translated is None else translated


def _resolved(default, override):
    default = _clean_text(default)
    if default == "—":
        default = ""
    override = _clean_text(override)
    if override == "—":
        return ""
    return override or default


def _without_group(group, title):
    group, title = _clean_text(group), _clean_text(title)
    if group and title == group:
        return ""
    prefix = group + " " if group else ""
    return title[len(prefix):] if prefix and title.startswith(prefix) else title


def _old_base_name(row, language):
    value = lambda field: _translated(row.get(field), language)
    native = _clean_text(value("mdl_native_name_override"))
    if native:
        return _resolved("", native)
    group = _resolved(value("mdl_group_default_name"), value("mdl_group_name_override"))
    model = "" if row.get("mdl_model_as_attribute") else _resolved(
        _without_group(value("mdl_group_default_name"), value("name")),
        value("mdl_model_name_override"),
    )
    return _clean_text(" ".join(part for part in (group, model) if part))


def _materialized_names(row):
    # Preserve stored translations even for inactive/uninstalled languages.
    # Any language absent from every input formerly used all English fallbacks;
    # it will continue to use the new English fallback with the identical result.
    languages = {"en_US"}
    for field in _SOURCE_COLUMNS + (_STORED_BASE_COLUMN,):
        translations = row.get(field)
        if isinstance(translations, dict):
            languages.update(translations)
    if _STORED_BASE_COLUMN in row:
        # The old renderer applies clean_text even to an explicit blank or a
        # SQL NULL. Neither case authorizes introducing a legacy title prefix.
        return {language: _clean_text(_translated(row[_STORED_BASE_COLUMN], language))
                for language in sorted(languages)}
    return {language: _old_base_name(row, language) for language in sorted(languages)}


def migrate(cr, version):
    if not version:
        return
    last_id = updated = 0
    while True:
        # No active filter: archived templates need the same future behavior.
        # Keyset batches allow writes with this cursor without losing a pending
        # SELECT result and do not place an arbitrary cap on the managed catalog.
        cr.execute(
            """
            SELECT id, name, mdl_group_default_name, mdl_group_name_override,
                   mdl_model_name_override, mdl_native_name_override,
                   mdl_model_as_attribute, mdl_effective_base_name
              FROM product_template
             WHERE mdl_catalog_managed IS TRUE AND id > %s
             ORDER BY id
             LIMIT 500
            """,
            (last_id,),
        )
        records = cr.fetchall()
        if not records:
            break
        for record in records:
            row = dict(zip(("id",) + _SOURCE_COLUMNS + ("mdl_model_as_attribute", _STORED_BASE_COLUMN), record))
            names = _materialized_names(row)
            if any(name == "—" for name in names.values()):
                # New source-field semantics use — as intentional omission;
                # the old renderer displayed a literal stored —. Do not turn
                # that exceptional pre-upgrade state into a silent rename.
                raise RuntimeError(
                    "Cannot preserve literal em-dash stored name base for "
                    f"product group {row['id']}; review this unsupported pre-upgrade state."
                )
            divergent = [language for language, name in names.items()
                         if name != _old_base_name(row, language)]
            if divergent:
                _logger.warning(
                    "Preserving stored variant-name base rather than stale legacy inputs "
                    "for product group %s in languages %s", row["id"], ", ".join(divergent),
                )
            if names == row["mdl_group_default_name"]:
                continue
            cr.execute(
                """
                UPDATE product_template
                   SET mdl_group_default_name = %s::jsonb
                 WHERE id = %s
                """,
                (json.dumps(names, ensure_ascii=False), row["id"]),
            )
            updated += 1
        last_id = records[-1][0]
    _logger.info("Materialized the existing variant-name base for %s managed product groups", updated)
