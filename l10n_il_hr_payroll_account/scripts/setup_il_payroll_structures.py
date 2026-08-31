"""One-time, idempotent production setup for the Israeli payroll structures.

Run only after deploying/restarting with ``l10n_il_hr_payroll_account`` 1.1.0:

    odoo-bin shell -c /path/to/odoo.conf -d DATABASE \
        < l10n_il_hr_payroll_account/scripts/setup_il_payroll_structures.py

The script commits only after all post-conditions pass. Take a database backup
before running it in production.
"""


MODULE = "l10n_il_hr_payroll_account"
MONTHLY_TYPE_NAME = "\u05d7\u05d5\u05d3\u05e9\u05d9 \u05de\u05d3\u05d9\u05e0\u05ea \u05d9\u05e9\u05e8\u05d0\u05dc"
DAILY_TYPE_NAME = "\u05d9\u05d5\u05de\u05d9 \u05de\u05d3\u05d9\u05e0\u05ea \u05d9\u05e9\u05e8\u05d0\u05dc"


def ensure_xml_record(xml_name, model_name, domain, values):
    """Find/create a record and make the module XML ID point to it."""
    full_xmlid = "%s.%s" % (MODULE, xml_name)
    record = env.ref(full_xmlid, raise_if_not_found=False)
    if record:
        if record._name != model_name:
            raise RuntimeError("%s points to %s instead of %s" % (
                full_xmlid, record._name, model_name))
        record.write(values)
        return record

    record = env[model_name].with_context(active_test=False).search(domain, limit=1)
    if record:
        record.write(values)
    else:
        record = env[model_name].create(values)
    env["ir.model.data"].create({
        "module": MODULE,
        "name": xml_name,
        "model": model_name,
        "res_id": record.id,
        "noupdate": False,
    })
    return record


module = env["ir.module.module"].search([("name", "=", MODULE)], limit=1)
if not module or module.state != "installed":
    raise RuntimeError(
        "l10n_il_hr_payroll_account must be installed and its new Python code must "
        "be loaded before running this script."
    )
if not hasattr(env["hr.payroll.structure"], "_il_sync_structures_and_rules"):
    raise RuntimeError("The running Odoo process has not loaded the new module code; restart it first.")

country = env.ref("base.il")

monthly_type = ensure_xml_record(
    "hr_payroll_structure_type_il",
    "hr.payroll.structure.type",
    [("name", "=", MONTHLY_TYPE_NAME), ("country_id", "=", country.id)],
    {
        "name": MONTHLY_TYPE_NAME,
        "country_id": country.id,
        "default_schedule_pay": "monthly",
        "wage_type": "monthly",
    },
)
daily_type = ensure_xml_record(
    "hr_payroll_structure_type_il_daily",
    "hr.payroll.structure.type",
    [("name", "=", DAILY_TYPE_NAME), ("country_id", "=", country.id)],
    {
        "name": DAILY_TYPE_NAME,
        "country_id": country.id,
        "default_schedule_pay": "monthly",
        "wage_type": "hourly",
    },
)

structure_specs = [
    ("hr_payroll_structure_il", "IL_ISR_MONTHLY", "\u05e9\u05db\u05e8 \u05d9\u05e9\u05e8\u05d0\u05dc\u05d9 \u05d7\u05d5\u05d3\u05e9\u05d9", monthly_type),
    ("hr_payroll_structure_il_pal_monthly", "IL_PAL_MONTHLY", "\u05e9\u05db\u05e8 \u05e4\u05dc\u05e9\u05ea\u05d9\u05e0\u05d9 \u05d7\u05d5\u05d3\u05e9\u05d9", monthly_type),
    ("hr_payroll_structure_il_isr_daily", "IL_ISR_DAILY", "\u05e9\u05db\u05e8 \u05d9\u05e9\u05e8\u05d0\u05dc\u05d9 \u05d9\u05d5\u05de\u05d9", daily_type),
    ("hr_payroll_structure_il_pal_daily", "IL_PAL_DAILY", "\u05e9\u05db\u05e8 \u05e4\u05dc\u05e9\u05ea\u05d9\u05e0\u05d9 \u05d9\u05d5\u05de\u05d9", daily_type),
]
structures = env["hr.payroll.structure"]
for xml_name, code, name, structure_type in structure_specs:
    structure = ensure_xml_record(
        xml_name,
        "hr.payroll.structure",
        [("code", "=", code)],
        {
            "name": name,
            "code": code,
            "type_id": structure_type.id,
            "country_id": country.id,
            "active": True,
        },
    )
    structures |= structure

monthly_type.default_struct_id = env.ref("%s.hr_payroll_structure_il" % MODULE)
daily_type.default_struct_id = env.ref("%s.hr_payroll_structure_il_isr_daily" % MODULE)

template = env.ref("%s.hr_payroll_structure_il" % MODULE)
if not template.rule_ids:
    raise RuntimeError(
        "The Israeli monthly template has no salary rules. Upgrade "
        "l10n_il_hr_payroll_account first, then rerun this script."
    )

# These module methods are the same source of truth used during an upgrade.
env["hr.rule.parameter"]._il_rebuild_2026_parameters()
env["hr.payroll.structure"]._il_sync_structures_and_rules()

# Reapply canonical labels after the synchronization and validate everything.
for xml_name, code, name, structure_type in structure_specs:
    structure = env.ref("%s.%s" % (MODULE, xml_name))
    structure.write({
        "name": name,
        "code": code,
        "type_id": structure_type.id,
        "country_id": country.id,
        "active": True,
    })

expected_codes = {spec[1] for spec in structure_specs}
active_il_structures = env["hr.payroll.structure"].search([
    ("country_id", "=", country.id),
    ("active", "=", True),
])
actual_codes = set(active_il_structures.mapped("code"))
if actual_codes != expected_codes:
    raise RuntimeError("Unexpected active Israeli structures: %s" % sorted(actual_codes))

for structure in structures:
    rules = structure.rule_ids
    if not rules:
        raise RuntimeError("Structure %s has no salary rules" % structure.code)
    copy_names = rules.filtered(lambda rule: "copy" in (rule.name or "").lower())
    if copy_names:
        raise RuntimeError("Structure %s still has Copy rule names: %s" % (
            structure.code, copy_names.mapped("name")))

if monthly_type.default_schedule_pay != "monthly" or daily_type.default_schedule_pay != "monthly":
    raise RuntimeError("Payment frequency must be monthly for both Israeli structure types")

env.cr.commit()
print("ISRAEL_PAYROLL_SETUP_OK")
print("STRUCTURE_TYPES", [
    (monthly_type.id, monthly_type.name, monthly_type.wage_type, monthly_type.default_struct_id.code),
    (daily_type.id, daily_type.name, daily_type.wage_type, daily_type.default_struct_id.code),
])
print("STRUCTURES", [
    (structure.id, structure.code, structure.name, structure.type_id.name, len(structure.rule_ids))
    for structure in structures.sorted("code")
])
