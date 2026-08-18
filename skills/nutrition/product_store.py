"""⭐ P17f — THE PRODUCT EVIDENCE STORE. APPEND-ONLY. SNAPSHOT-ADDRESSED.

⛔⛔ THE FROZEN STORAGE INVARIANT *(Danny, 2026-08-17)*:

    EVIDENCE ROWS ARE IMMUTABLE SNAPSHOTS.
    CANONICAL MEAL ROWS REFERENCE THEM.
    ACQUISITION MAY ADD EVIDENCE; SETTLEMENT MAY ONLY READ EVIDENCE.

One sentence, one storage model — for P17f, for the P17f.5 barcode wire, for
B-1.8 corrections, and eventually for PRODUCT_VARIANT. OFF is mutable, so the
persisted object represents the exact evidence Arnie USED, never "whatever OFF
currently says about this barcode": a re-acquisition that finds changed facts
INSERTS a new snapshot, and yesterday's meals keep pointing at yesterday's.

    OFF snapshot (rev 4, 55 g/bar, 200 kcal/bar)  ->  product_evidence PE_123
    meal: 2 bars, rung PRODUCT, evidence PE_123, factor 2  ->  400 kcal
    six months later, "actually I had 3 bars":
        load PE_123 -> factor 2 -> 3 -> reprice.  No fetch. No reinterpretation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def canonical_code(barcode: str) -> str:
    """ZERO-NORMALIZED digits. Codified from the P17d.0 probe: OFF resolves
    equivalent UPC-A/EAN-13 forms to its own stored form in BOTH directions, so
    two spellings of one product must not become two identities."""
    return re.sub(r"\D", "", str(barcode or "")).lstrip("0")


def _fingerprint(facts: dict) -> str:
    """A hash of the EXACT persisted facts — what a later reprice must be able
    to reproduce. An id plus a provider name identifies a moving target; the
    fingerprint pins what Arnie actually saw."""
    return hashlib.sha256(
        json.dumps(facts, sort_keys=True, ensure_ascii=False)
        .encode()).hexdigest()[:16]


async def append_product_evidence(db, *, record: dict, serving_unit: str = "",
                                  package_unit: str = ""):
    """Persist one OFF record as an immutable snapshot. IDEMPOTENT BY FACTS:
    the same facts re-acquired land on the same row; CHANGED facts insert a NEW
    row and touch nothing. ACQUISITION-TIME ONLY — nothing at settlement may
    call this, which is what keeps Gate B a fact rather than a hope.
    """
    from sqlalchemy import select

    from db.models import ProductEvidenceRecord
    from skills.nutrition.off import product_evidence_from_off

    evidence = product_evidence_from_off(record, serving_unit=serving_unit,
                                         package_unit=package_unit)
    if evidence is None:
        return None
    code = canonical_code(record.get("code"))
    per100_key = str(record.get("nutrition_data_per") or "100g").strip()
    facts = {
        "code": code,
        "per_serving": evidence.per_serving,
        "per100g": evidence.per100g,
        "per100ml_marker": per100_key if per100_key != "100g" else None,
        "serving_grams": evidence.serving_grams,
        "serving_unit": evidence.serving_unit,
        "package_unit": evidence.package_unit,
        "servings_per_package": evidence.servings_per_package,
        # ⛔ NO `rev` IN HERE. The fingerprint pins the FACTS; the provider
        # revision is its own explicit column in the snapshot identity. Mixing
        # them conflated "the facts changed" with "the provider version moved"
        # — a metadata-only edit (rev bump, same nutrition) is a NEW snapshot
        # by the four-part key, visibly, not a hash coincidence.
    }
    fingerprint = _fingerprint(facts)

    existing = (await db.execute(select(ProductEvidenceRecord).where(
        ProductEvidenceRecord.provider == "off",
        ProductEvidenceRecord.canonical_code == code,
        ProductEvidenceRecord.provider_revision == str(record.get("rev") or ""),
        ProductEvidenceRecord.source_fingerprint == fingerprint,
    ))).scalar_one_or_none()
    if existing is not None:
        return existing

    row = ProductEvidenceRecord(
        provider="off", canonical_code=code,
        provider_revision=str(record.get("rev") or ""),
        provider_modified_at=record.get("last_modified_t"),
        source_fingerprint=fingerprint,
        product_name=str(record.get("product_name") or "") or None,
        brands=str(record.get("brands") or "") or None,
        per_serving_json=(json.dumps(evidence.per_serving)
                          if evidence.per_serving else None),
        per100g_json=(json.dumps(evidence.per100g)
                      if evidence.per100g else None),
        serving_amount=1.0 if evidence.serving_unit else None,
        serving_unit=evidence.serving_unit or None,
        serving_mass_g=evidence.serving_grams,
        package_unit=evidence.package_unit or None,
        servings_per_package=evidence.servings_per_package,
        source_reference_json=json.dumps({
            "dataset_id": "off", "record_key": code,
            "rev": record.get("rev"),
            "modified_t": record.get("last_modified_t"),
            "source_id": evidence.source_id,
            # ⛔ NEVER immutable: a crowd database has no releases, and this
            # row is the immutability — the snapshot, not the source.
            "immutable_within_version": False,
        }),
    )
    db.add(row)
    await db.flush()
    logger.info("event=product_evidence_appended code=%s rev=%s fp=%s id=%s",
                code, record.get("rev"), fingerprint, row.id)
    return row


async def load_product_evidence(db, evidence_id: int):
    """The snapshot a meal used, BY ID, back as a pricing input. SETTLEMENT'S
    ONLY VERB. Returns None for an unknown id — a missing snapshot is a
    declined rung, never a fetch."""
    from db.models import ProductEvidenceRecord

    row = await db.get(ProductEvidenceRecord, int(evidence_id))
    return _to_evidence(row) if row is not None else None


async def latest_product_evidence(db, barcode: str):
    """Acquisition convenience: the NEWEST snapshot for a code. A query over
    created_at — deliberately not an overwrite, and deliberately not what a
    committed meal reads (a meal reads its own referenced snapshot)."""
    from sqlalchemy import select

    from db.models import ProductEvidenceRecord

    code = canonical_code(barcode)
    if not code:
        return None
    row = (await db.execute(
        select(ProductEvidenceRecord)
        .where(ProductEvidenceRecord.provider == "off",
               ProductEvidenceRecord.canonical_code == code)
        .order_by(ProductEvidenceRecord.created_at.desc(),
                  ProductEvidenceRecord.id.desc())
        .limit(1))).scalar_one_or_none()
    return row


def _to_evidence(row):
    """Row -> `ProductEvidence`, structurally identical to what the producer
    built at acquisition — the round-trip P17f.2 requires."""
    from core.canonical_pricing import ProductEvidence

    return ProductEvidence(
        identifier=f"off:{row.canonical_code}",
        per_serving=(json.loads(row.per_serving_json)
                     if row.per_serving_json else None),
        per100g=(json.loads(row.per100g_json) if row.per100g_json else None),
        serving_grams=row.serving_mass_g,
        serving_unit=row.serving_unit or "",
        package_unit=row.package_unit or "",
        servings_per_package=row.servings_per_package,
        source_id=json.loads(row.source_reference_json).get("source_id", ""),
        dataset_id=str(json.loads(row.source_reference_json).get("dataset_id", "") or ""),
        record_version=(f"rev:{row.provider_revision}@{row.provider_modified_at}"
                        if row.provider_revision not in (None, "") else ""))
