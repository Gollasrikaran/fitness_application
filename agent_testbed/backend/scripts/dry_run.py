"""Phase 8 dry run: "Generate plan" over a random sample of real patients.

Reads the clinic DB (read-only) and writes only to the temp DB, as doctor
DRY_RUN_DOCTOR. Patients who already have a plan or a waiting draft are
skipped, so no doctor's work is touched. The drafts it makes are deleted at
the end (they would otherwise show as waiting for the patient); the
assessments are kept for audit.

    cd agent_testbed/backend
    .venv/Scripts/python -m scripts.dry_run --n 50 --out dry_run.json

Costs one AI call per patient, plus one per patient who isn't severe.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, select

from agent.assess import run_assessment
from agent.conditions import load_reference, rule_findings
from agent.draft import build_draft
from app import clinic
from app.db import pool
from store import plans as plan_store
from store.db import session
from store.models import Plan, PlanProposal
from store.seed import init_store

DRY_RUN_DOCTOR = "dry-run-p8"
log = logging.getLogger("dry_run")


def _unmatched_text(context: dict, rules) -> list[dict]:
    """Diagnoses no alias matched: where the alias file may need a row."""
    matched = {f.where for f in rules.findings}
    out = []
    for v in context["visits"]:
        where = f"visit {v['date']}, diagnosis"
        text = " / ".join(filter(None, (v.get("diagnosis_confirmed"), v.get("diagnosis_provisional"))))
        if text and where not in matched:
            out.append({"where": where, "text": text.strip()})
    return out


def run_one(patient_id: str) -> dict:
    context = clinic.patient_context(patient_id)
    with session() as db:
        ref = load_reference(db)
    rules = rule_findings(context, ref)
    assessment = run_assessment(patient_id, DRY_RUN_DOCTOR, context=context)
    patient = {"age": context["patient"]["age"], "sex": context["patient"]["sex"], "bmi": context["body"]["bmi"]}
    with session() as db:
        draft = build_draft(db, patient_id, assessment, patient)
        draft_out = {"id": draft.id, "source": draft.source, "kind": draft.kind, "reason": draft.reason,
                     "exercises": [e["name"] for e in draft.exercises]}
    return {"patient_id": patient_id, "age": patient["age"], "sex": patient["sex"], "bmi": patient["bmi"],
            "assessment": {k: assessment.get(k) for k in ("severity", "severe_reasons", "codes", "conditions",
                                                          "problem", "body_area", "concerns", "missing", "unmapped",
                                                          "warnings", "ai_status", "dropped")},
            "draft": draft_out, "unmatched_diagnoses": _unmatched_text(context, rules)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=8)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    pool.open()
    init_store()
    pool_ids = [p["id"] for p in clinic.patients(None, "", limit=500, min_visits=2)]
    with session() as db:
        busy = set(db.scalars(select(Plan.patient_id))) | set(
            db.scalars(select(PlanProposal.patient_id).where(PlanProposal.status == "pending")))
    sample = random.Random(args.seed).sample([p for p in pool_ids if p not in busy], args.n)
    print(f"{len(pool_ids)} recent patients, {len(busy)} skipped (plan or draft), running {len(sample)}")

    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, out in enumerate(ex.map(lambda pid: _safe(pid), sample), 1):
            results.append(out)
            print(f"{i}/{len(sample)} {out['patient_id'][:8]} "
                  f"{out.get('assessment', {}).get('severity', 'ERROR')} {out.get('draft', {}).get('source', '')}")

    with session() as db:  # the drafts would show as waiting for these patients: remove them
        n = db.execute(delete(PlanProposal).where(PlanProposal.id.in_(
            [r["draft"]["id"] for r in results if "draft" in r]))).rowcount
    print(f"deleted {n} dry-run drafts; assessments kept (doctor_id={DRY_RUN_DOCTOR})")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, default=str, ensure_ascii=False)
    pool.close()


def _safe(patient_id: str) -> dict:
    try:
        return run_one(patient_id)
    except Exception as exc:  # one bad record shouldn't stop the run
        log.exception("Patient %s failed", patient_id)
        return {"patient_id": patient_id, "error": str(exc)}


if __name__ == "__main__":
    main()
