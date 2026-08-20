"""
Second pass over data/rag_chunks/medquad_chunks.jsonl: manually trims medication
content out of the chunks that got flagged, sentence-by-sentence (not whole-chunk
deletion) per Ayush's decision.

Each entry in TRIMS is a hand-reviewed (old_text -> new_text) pair for one chunk_id.
Where a sentence was a mixed list ("rest, pain medicines, or ice"), only the
medication clause was removed, so exercise/self-care/rest content that happened to
share a sentence with a drug name is kept.

Untouched chunks (not in TRIMS) pass through unchanged.

Output: data/rag_chunks/medquad_chunks_reviewed.jsonl
Each record gets:
  - trimmed: bool, whether this chunk was edited
  - medication_flagged: re-run against the NEW text (should be empty or near-empty)
  - token_count: recomputed for the new text
The original medquad_chunks.jsonl is left untouched as the raw/audit copy.
"""

import json
import re
from pathlib import Path

import tiktoken

RAW_PATH = Path(__file__).resolve().parent.parent / "data" / "rag_chunks" / "medquad_chunks.jsonl"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "rag_chunks" / "medquad_chunks_reviewed.jsonl"

ENCODING = tiktoken.get_encoding("cl100k_base")

MEDICATION_KEYWORDS = [
    "allopurinol", "febuxostat", "probenecid", "colchicine", "pegloticase",
    "nsaid", "nsaids", "corticosteroid", "corticosteroids", "steroid injection",
    "ibuprofen", "naproxen", "acetaminophen", "aspirin", "diuretic", "diuretics",
    "cyclosporine", "levodopa", "niacin", "anti-inflammatory medic", "pain reliever",
    "pain medicine", "medication", "medicine", "drug", "injection", "prescri",
]

# Hand-reviewed trims: only the medication-mentioning clause/sentence is removed;
# everything else in the chunk is preserved exactly as-is.
TRIMS = {
    "medquad__arthritis_hip__chunk1": (
        "Management strategies encompass exercise (strengthening, aerobic, range-of-motion activities), weight control, medications (acetaminophen or NSAIDs), heat/cold therapy, and surgical interventions when necessary.",
        "Management strategies encompass exercise (strengthening, aerobic, range-of-motion activities), weight control, heat/cold therapy, and surgical interventions when necessary.",
    ),
    "medquad__bursitis__chunk0": (
        "Treatment of bursitis includes rest, pain medicines, or ice.",
        "Treatment of bursitis includes rest or ice.",
    ),
    "medquad__bursitis__chunk1": (
        "Treatment of bursitis includes rest, pain medicines, or ice. If there is no improvement, your doctor may inject a drug into the area around the swollen bursa.",
        "Treatment of bursitis includes rest or ice.",
    ),
    "medquad__carpal_tunnel__chunk1": (
        "Initial management typically involves immobilizing the wrist with a splint, nonsteroidal anti-inflammatory drugs to reduce swelling, and corticosteroid injections.",
        "Initial management typically involves immobilizing the wrist with a splint.",
    ),
    "medquad__chronic_back_pain__chunk0": (
        "- Over-the-counter pain relievers and anti-inflammatory medications - Hot or cold compresses to reduce pain and inflammation - Limited bed rest (maximum 1-2 days; prolonged rest can worsen symptoms) - Exercise to strengthen back and abdominal muscles - Physical therapy and medications - In severe cases, surgical intervention",
        "- Hot or cold compresses to reduce pain and inflammation - Limited bed rest (maximum 1-2 days; prolonged rest can worsen symptoms) - Exercise to strengthen back and abdominal muscles - Physical therapy - In severe cases, surgical intervention",
    ),
    "medquad__chronic_back_pain__chunk1": (
        "- Physical therapy and medications - In severe cases, surgical intervention",
        "- Physical therapy - In severe cases, surgical intervention",
    ),
    "medquad__degenerative_disc__chunk1": (
        "In the absence of red flags, the initial approach to treatment is typically conservative and includes physical therapy and pain medications.",
        "In the absence of red flags, the initial approach to treatment is typically conservative and includes physical therapy.",
    ),
    "medquad__gout__chunk1": (
        "- Medical conditions: kidney disease, high blood pressure, hypothyroidism, rapid cell turnover conditions - Medications: diuretics, aspirin, niacin, cyclosporine, levodopa ## Treatments For acute attacks, doctors typically prescribe high-dose NSAIDs or corticosteroids. Patients often begin to improve within a few hours of treatment, and the attack usually goes away completely within a week or so. For recurring attacks, medications like allopurinol, febuxostat, or probenecid lower uric acid levels. In severe cases, pegloticase via intravenous infusion may be prescribed.",
        "- Medical conditions: kidney disease, high blood pressure, hypothyroidism, rapid cell turnover conditions ## Treatments Acute attacks are usually managed under a doctor's care and often go away completely within a week or so. Ask your doctor about long-term ways to lower uric acid levels and prevent future flares.",
    ),
    "medquad__herniated_disk__chunk0": (
        "Treatment options include rest, pain management with anti-inflammatory medicines, physical therapy, and sometimes surgery.",
        "Treatment options include rest, physical therapy, and sometimes surgery.",
    ),
    "medquad__spinal_stenosis__chunk0": (
        "Treatments include medications, physical therapy, braces, and surgery.",
        "Treatments include physical therapy, braces, and surgery.",
    ),
    "medquad__sprain_strain__chunk0": (
        "At first, treatment of both sprains and strains usually involves resting the injured area, icing it, wearing a bandage or device that compresses the area, and medicines.",
        "At first, treatment of both sprains and strains usually involves resting the injured area, icing it, and wearing a bandage or device that compresses the area.",
    ),
    "medquad__sprain_strain__chunk1": (
        "At first, treatment of both sprains and strains usually involves resting the injured area, icing it, wearing a bandage or device that compresses the area, and medicines.",
        "At first, treatment of both sprains and strains usually involves resting the injured area, icing it, and wearing a bandage or device that compresses the area.",
    ),
}


def token_len(text: str) -> int:
    return len(ENCODING.encode(text))


def flag_medications(text: str):
    lowered = text.lower()
    return sorted({kw for kw in MEDICATION_KEYWORDS if kw in lowered})


def main():
    if not RAW_PATH.exists():
        print("Run scripts/chunk_medquad.py first.")
        return

    records = []
    with RAW_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    trimmed_count = 0
    thin_warnings = []

    for record in records:
        chunk_id = record["chunk_id"]
        if chunk_id in TRIMS:
            old_fragment, new_fragment = TRIMS[chunk_id]
            if old_fragment not in record["text"]:
                raise ValueError(f"Expected fragment not found in {chunk_id} — chunk text may have changed.")
            record["text"] = record["text"].replace(old_fragment, new_fragment)
            record["trimmed"] = True
            trimmed_count += 1
        else:
            record["trimmed"] = False

        record["token_count"] = token_len(record["text"])
        record["medication_flagged"] = flag_medications(record["text"])

        if record["trimmed"] and record["token_count"] < 40:
            thin_warnings.append(chunk_id)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    remaining_flags = sum(1 for r in records if r["medication_flagged"])
    print(f"Reviewed {len(records)} chunks ({trimmed_count} trimmed) -> {OUTPUT_PATH}")
    print(f"Chunks still carrying a medication-keyword hit after trimming: {remaining_flags}")
    for r in records:
        if r["medication_flagged"]:
            print(f"  - {r['chunk_id']}: {r['medication_flagged']}")
    if thin_warnings:
        print()
        print("Chunks that got noticeably short after trimming (worth a manual glance):")
        for cid in thin_warnings:
            print(f"  - {cid}")


if __name__ == "__main__":
    main()
