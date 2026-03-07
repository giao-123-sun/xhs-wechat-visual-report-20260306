import csv
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT.parent / "xhs_collection_output"
SRC_USERS = SRC / "users"
SRC_IMAGES = SRC / "wechat_images"

DATA = ROOT / "data"
RAW_USERS = DATA / "raw_users"
OUT_IMAGES = DATA / "wechat_images"
PIPELINE = DATA / "note_pipeline"


def parse_like_count(v: str) -> int:
    s = (v or "").strip()
    if not s:
        return 0
    s = s.replace(",", "")
    try:
        if s.endswith("万"):
            return int(float(s[:-1]) * 10000)
        return int(float(s))
    except ValueError:
        return 0


def excerpt(text: str, limit: int) -> str:
    value = (text or "").replace("```json", "").replace("```", "")
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def read_jsonl_unique_ids(path: Path) -> set[str]:
    ids = set()
    if not path.exists():
        return ids
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            note_id = row.get("note_id")
            if note_id:
                ids.add(note_id)
    return ids


def build_pipeline_summary(notes: list[dict]) -> dict:
    source_ids = {row["note_id"] for row in notes if row.get("note_id")}
    detail_ids = read_jsonl_unique_ids(PIPELINE / "note_details.jsonl")
    ocr_ids = read_jsonl_unique_ids(PIPELINE / "note_ocr.jsonl")

    units = []
    if (PIPELINE / "note_units.json").exists():
        units = json.loads((PIPELINE / "note_units.json").read_text(encoding="utf-8"))

    featured = []
    for row in units[:18]:
        featured.append(
            {
                "note_id": row.get("note_id", ""),
                "title": row.get("title", "") or "无标题",
                "account_name": row.get("account_name", ""),
                "category": row.get("category", ""),
                "liked_count": parse_like_count(str(row.get("liked_count", 0))),
                "note_type": row.get("note_type", ""),
                "upload_time": row.get("upload_time", ""),
                "note_url": row.get("note_url", ""),
                "cover_image": (row.get("local_images") or [None])[0],
                "desc_excerpt": excerpt(row.get("desc", ""), 150),
                "ocr_excerpt": excerpt(row.get("ocr_merged_text", ""), 180),
            }
        )

    processed_categories = {}
    for row in units:
        category = row.get("category") or "未分类"
        processed_categories[category] = processed_categories.get(category, 0) + 1

    progress = {
        "source_unique_notes": len(source_ids),
        "detail_count": len(detail_ids),
        "ocr_count": len(ocr_ids),
        "detail_remaining": len(source_ids - detail_ids),
        "ocr_remaining_after_detail": len(detail_ids - ocr_ids),
        "featured_count": len(featured),
        "processed_categories": processed_categories,
        "current_ocr_model": "google/gemini-2.5-flash-lite",
    }
    (PIPELINE / "progress.json").write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "progress": progress,
        "featured_notes": featured,
    }


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    RAW_USERS.mkdir(parents=True, exist_ok=True)
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)

    notes = []
    accounts = []

    for csv_file in sorted(SRC_USERS.glob("*.csv")):
        shutil.copy2(csv_file, RAW_USERS / csv_file.name)
        with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue

        account_name = rows[0].get("resolved_name") or rows[0].get("seed_name") or csv_file.stem
        red_id = rows[0].get("resolved_red_id") or rows[0].get("seed_red_id") or ""
        category = rows[0].get("category") or "未分类"
        user_id = rows[0].get("user_id") or ""

        total_likes = 0
        for r in rows:
            likes = parse_like_count(r.get("liked_count", ""))
            total_likes += likes
            notes.append(
                {
                    "account_name": account_name,
                    "red_id": red_id,
                    "category": category,
                    "user_id": user_id,
                    "note_id": r.get("note_id", ""),
                    "note_type": r.get("note_type", ""),
                    "display_title": r.get("display_title", ""),
                    "liked_count": likes,
                    "note_url": r.get("note_url", ""),
                }
            )

        accounts.append(
            {
                "account_name": account_name,
                "red_id": red_id,
                "category": category,
                "user_id": user_id,
                "note_count": len(rows),
                "total_likes": total_likes,
                "avg_likes": int(total_likes / len(rows)) if rows else 0,
                "source_csv": f"data/raw_users/{csv_file.name}",
            }
        )

    notes.sort(key=lambda x: x["liked_count"], reverse=True)
    accounts.sort(key=lambda x: x["note_count"], reverse=True)

    categories = {}
    for a in accounts:
        categories[a["category"]] = categories.get(a["category"], 0) + a["note_count"]

    stats = {
        "account_count": len(accounts),
        "note_count": len(notes),
        "categories": categories,
    }

    # Copy all article images for browsing in the static site.
    for img in sorted(SRC_IMAGES.glob("*")):
        if img.is_file():
            shutil.copy2(img, OUT_IMAGES / img.name)

    pipeline_summary = build_pipeline_summary(notes)

    (DATA / "accounts.json").write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "notes.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "note_pipeline_summary.json").write_text(
        json.dumps(pipeline_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "stats": stats,
                "pipeline_progress": pipeline_summary["progress"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
