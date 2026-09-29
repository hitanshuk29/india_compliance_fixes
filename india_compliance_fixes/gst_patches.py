"""
Runtime patches applied against the india_compliance app, without modifying its source.

Background
----------
india_compliance.gst_india.overrides.transaction.validate_transaction() calls
validate_item_tax_template(doc) twice for Sales/Purchase style documents:
    1. Once from the "validate" doc event (before the document is saved).
    2. Once again from the "on_submit" doc event.

Between these two calls, Frappe rebuilds the document's child table row objects
(e.g. doc.items gets a fresh list of new row instances after insert), while
india_compliance's cached `_item_wise_tax_details` (built once during
calculate_taxes_and_totals) still points at the old, now-detached row objects.
This causes the second (on_submit) call to see item.cgst_rate/sgst_rate/igst_rate
reset to 0 even though the first (validate) call already confirmed correct GST
rates, incorrectly failing submission with:
    "No GST is being charged on Taxable Items."

Fix
---
Only run validate_item_tax_template() once per document instance. The first
successful run (during "validate") is authoritative; skip the redundant,
stale-data-prone re-check that runs again during "on_submit".
"""

import frappe


def apply(doc=None, method=None):
    """Hooked on before_validate for every doctype so this runs early in every
    worker process, before india_compliance's GST checks fire for the first time."""
    _patch_validate_item_tax_template()


def _patch_validate_item_tax_template():
    from india_compliance.gst_india.overrides import transaction

    original = transaction.validate_item_tax_template

    if getattr(original, "_is_india_compliance_fixes_patch", False):
        return

    def validate_item_tax_template(doc, method=None):
        if doc.flags.get("_gst_item_tax_template_already_checked"):
            return

        result = original(doc)
        doc.flags._gst_item_tax_template_already_checked = True
        return result

    validate_item_tax_template._is_india_compliance_fixes_patch = True
    transaction.validate_item_tax_template = validate_item_tax_template

    frappe.logger("india_compliance_fixes").info(
        "Patched india_compliance validate_item_tax_template to skip the redundant on_submit re-check."
    )
