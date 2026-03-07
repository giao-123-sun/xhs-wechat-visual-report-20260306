import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import requests

# Patch default timeout for all requests calls (including Spider_XHS internals).
_orig_request = requests.sessions.Session.request


def _request_with_timeout(self, method, url, **kwargs):
    if "timeout" not in kwargs:
        kwargs["timeout"] = 30
    return _orig_request(self, method, url, **kwargs)


requests.sessions.Session.request = _request_with_timeout


PROJECT_ROOT = Path(__file__).resolve().parent
SPIDER_DIR = PROJECT_ROOT.parent / "Spider_XHS"
NOTES_PATH = PROJECT_ROOT / "data" / "notes.json"
OUT_DIR = PROJECT_ROOT / "data" / "note_pipeline"
DETAILS_PATH = OUT_DIR / "note_details.jsonl"
OCR_PATH = OUT_DIR / "note_ocr.jsonl"
DOWNLOAD_PATH = OUT_DIR / "note_downloads.jsonl"
UNITS_JSONL_PATH = OUT_DIR / "note_units.jsonl"
UNITS_JSON_PATH = OUT_DIR / "note_units.json"
FAIL_PATH = OUT_DIR / "failures.jsonl"
IMG_DIR = OUT_DIR / "note_images"


def ensure_dirs() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_cookie() -> str:
    cookie_path = PROJECT_ROOT.parent / "xhs-cookie.txt"
    cookie = cookie_path.read_text(encoding="utf-8").strip()
    if not cookie:
        raise RuntimeError(f"Cookie is empty: {cookie_path}")
    return cookie


def load_notes() -> List[dict]:
    rows = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    dedup = {}
    for r in rows:
        nid = r.get("note_id")
        if nid and nid not in dedup:
            dedup[nid] = r
    return list(dedup.values())


def init_spider():
    # Spider_XHS reads static js by relative path, so cwd must be Spider_XHS.
    os.chdir(str(SPIDER_DIR))
    if str(SPIDER_DIR) not in sys.path:
        sys.path.insert(0, str(SPIDER_DIR))
    from main import Data_Spider  # type: ignore

    return Data_Spider()


def build_detail_row(src: dict, note_info: dict) -> dict:
    image_urls = note_info.get("image_list", []) or []
    return {
        "note_id": note_info.get("note_id", src.get("note_id", "")),
        "note_url": note_info.get("note_url", src.get("note_url", "")),
        "account_name": src.get("account_name", ""),
        "red_id": src.get("red_id", ""),
        "category": src.get("category", ""),
        "user_id": note_info.get("user_id", src.get("user_id", "")),
        "note_type": note_info.get("note_type", ""),
        "title": note_info.get("title", ""),
        "desc": note_info.get("desc", ""),
        "liked_count": note_info.get("liked_count", src.get("liked_count", 0)),
        "collected_count": note_info.get("collected_count", 0),
        "comment_count": note_info.get("comment_count", 0),
        "share_count": note_info.get("share_count", 0),
        "tags": note_info.get("tags", []),
        "upload_time": note_info.get("upload_time", ""),
        "ip_location": note_info.get("ip_location", ""),
        "video_addr": note_info.get("video_addr"),
        "video_cover": note_info.get("video_cover"),
        "image_urls": image_urls,
        "image_count": len(image_urls),
        "source_note_url": src.get("note_url", ""),
        "processed_at": int(time.time()),
    }


def download_images(note_id: str, image_urls: List[str]) -> List[str]:
    if not image_urls:
        return []
    note_dir = IMG_DIR / note_id
    note_dir.mkdir(parents=True, exist_ok=True)
    out = []
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.xiaohongshu.com/",
    }
    for idx, url in enumerate(image_urls, start=1):
        try:
            r = requests.get(url, headers=headers, timeout=60)
            r.raise_for_status()
        except Exception:
            continue
        ct = (r.headers.get("Content-Type") or "").lower()
        ext = ".jpg"
        if "png" in ct:
            ext = ".png"
        elif "webp" in ct:
            ext = ".webp"
        elif "gif" in ct:
            ext = ".gif"
        p = note_dir / f"img_{idx:02d}{ext}"
        p.write_bytes(r.content)
        out.append(str(p.relative_to(PROJECT_ROOT)).replace("\\", "/"))
    return out


def extract_text_from_choice_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif "text" in item:
                    parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join([p for p in parts if p])
    return str(content)


def try_parse_json_text(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s).strip()
        s = re.sub(r"```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {"images": [], "merged_text": text.strip(), "notes": "non_json_response"}


def call_openrouter_ocr(
    image_urls: List[str], api_key: str, model: str, max_retries: int = 5
) -> dict:
    prompt = (
        "你是OCR提取器。请读取这些图片中的可见文字，按图片顺序输出。"
        "仅返回JSON，不要返回其他内容。JSON格式为："
        '{"images":[{"index":1,"text":"..."}],"merged_text":"...","language":"zh|en|mixed|unknown","notes":"..."}。'
        "如果某张图无文字，text置空字符串。merged_text为所有图片文字合并后的结果。"
    )
    content = [{"type": "text", "text": prompt}]
    for u in image_urls:
        content.append({"type": "image_url", "image_url": {"url": u}})

    body = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/giao-123-sun/xhs-wechat-visual-report-20260306",
        "X-OpenRouter-Title": "xhs-note-ocr-pipeline",
    }

    wait = 2
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=body,
                timeout=180,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                raise RuntimeError(f"openrouter_status_{resp.status_code}:{resp.text[:400]}")
            resp.raise_for_status()
            data = resp.json()
            choice = ((data.get("choices") or [{}])[0]).get("message", {})
            text = extract_text_from_choice_content(choice.get("content", ""))
            parsed = try_parse_json_text(text)
            parsed["_model"] = data.get("model", model)
            parsed["_usage"] = data.get("usage", {})
            return parsed
        except Exception as e:
            if attempt == max_retries:
                return {
                    "images": [],
                    "merged_text": "",
                    "language": "unknown",
                    "notes": f"ocr_failed:{e}",
                }
            time.sleep(wait)
            wait = min(wait * 2, 30)
    return {"images": [], "merged_text": "", "language": "unknown", "notes": "ocr_failed"}


def process_details(
    notes: List[dict],
    cookie: str,
    limit: Optional[int],
    start: int,
    download: bool,
    workers: int,
) -> None:
    spider = init_spider()
    local_ctx = threading.local()
    done_ids = {r.get("note_id") for r in iter_jsonl(DETAILS_PATH)}
    total = len(notes)
    picked = notes[start : (start + limit if limit else None)]
    targets = [src for src in picked if src.get("note_id", "") not in done_ids]

    def task(src: dict) -> dict:
        local_spider = getattr(local_ctx, "spider", None)
        if local_spider is None:
            local_spider = spider.__class__()
            local_ctx.spider = local_spider
        note_id = src.get("note_id", "")
        note_url = src.get("note_url", "")
        success = False
        msg = ""
        note_info = None
        for _ in range(3):
            try:
                success, msg, note_info = local_spider.spider_note(note_url, cookie)
            except Exception as e:
                success, msg, note_info = False, str(e), None
            if success and note_info:
                break
            time.sleep(0.8)

        if not success or not note_info:
            return {
                "ok": False,
                "note_id": note_id,
                "note_url": note_url,
                "msg": msg,
            }
        row = build_detail_row(src, note_info)
        if download:
            row["local_images"] = download_images(note_id=row["note_id"], image_urls=row["image_urls"])
        else:
            row["local_images"] = []
        return {"ok": True, "row": row}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = [ex.submit(task, src) for src in targets]
        done = 0
        for fut in as_completed(futures):
            res = fut.result()
            done += 1
            if res.get("ok"):
                append_jsonl(DETAILS_PATH, res["row"])
            else:
                append_jsonl(
                    FAIL_PATH,
                    {
                        "stage": "detail",
                        "note_id": res.get("note_id", ""),
                        "note_url": res.get("note_url", ""),
                        "message": res.get("msg", ""),
                        "ts": int(time.time()),
                    },
                )
            if done % 20 == 0:
                print(f"[detail] {done}/{len(targets)}")


def process_ocr(api_key: str, model: str, max_images: int, workers: int, limit: Optional[int], start: int) -> None:
    details = list(iter_jsonl(DETAILS_PATH))
    done_ids = {r.get("note_id") for r in iter_jsonl(OCR_PATH)}
    pending = [d for d in details if d.get("note_id") not in done_ids]
    pending = pending[start : (start + limit if limit else None)]
    total = len(pending)

    def task(detail: dict) -> dict:
        note_id = detail.get("note_id", "")
        imgs = (detail.get("image_urls") or [])[:max_images]
        truncated = max(0, len(detail.get("image_urls") or []) - len(imgs))
        if not imgs:
            return {
                "note_id": note_id,
                "ocr": {"images": [], "merged_text": "", "language": "unknown", "notes": "no_images"},
                "image_count_used": 0,
                "image_count_total": len(detail.get("image_urls") or []),
                "truncated_images": 0,
                "ts": int(time.time()),
            }
        ocr = call_openrouter_ocr(imgs, api_key=api_key, model=model)
        return {
            "note_id": note_id,
            "ocr": ocr,
            "image_count_used": len(imgs),
            "image_count_total": len(detail.get("image_urls") or []),
            "truncated_images": truncated,
            "ts": int(time.time()),
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(task, d): d.get("note_id", "") for d in pending}
        done = 0
        for fut in as_completed(futures):
            result = fut.result()
            append_jsonl(OCR_PATH, result)
            done += 1
            if done % 20 == 0:
                print(f"[ocr] {done}/{total}")


def process_download(workers: int, limit: Optional[int], start: int) -> None:
    details = list(iter_jsonl(DETAILS_PATH))
    done_ids = {r.get("note_id") for r in iter_jsonl(DOWNLOAD_PATH)}
    pending = [d for d in details if d.get("note_id") not in done_ids]
    pending = pending[start : (start + limit if limit else None)]
    total = len(pending)

    def task(detail: dict) -> dict:
        note_id = detail.get("note_id", "")
        imgs = detail.get("image_urls") or []
        locals_ = download_images(note_id=note_id, image_urls=imgs)
        return {
            "note_id": note_id,
            "image_count_total": len(imgs),
            "image_count_downloaded": len(locals_),
            "local_images": locals_,
            "ts": int(time.time()),
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(task, d): d.get("note_id", "") for d in pending}
        done = 0
        for fut in as_completed(futures):
            result = fut.result()
            append_jsonl(DOWNLOAD_PATH, result)
            done += 1
            if done % 20 == 0:
                print(f"[download] {done}/{total}")


def merge_units() -> None:
    details_map: Dict[str, dict] = {}
    for r in iter_jsonl(DETAILS_PATH):
        nid = r.get("note_id")
        if nid:
            details_map[nid] = r
    ocr_map: Dict[str, dict] = {}
    for r in iter_jsonl(OCR_PATH):
        nid = r.get("note_id")
        if nid:
            ocr_map[nid] = r
    download_map: Dict[str, dict] = {}
    for r in iter_jsonl(DOWNLOAD_PATH):
        nid = r.get("note_id")
        if nid:
            download_map[nid] = r

    units = []
    for nid, d in details_map.items():
        o = ocr_map.get(nid, {})
        ocr = o.get("ocr", {})
        merged_text = (ocr.get("merged_text") or "").strip()
        full_text = "\n".join(
            [
                f"标题: {d.get('title','')}",
                f"正文: {d.get('desc','')}",
                f"图片OCR: {merged_text}",
            ]
        ).strip()
        local_images = d.get("local_images", []) or []
        if not local_images:
            local_images = (download_map.get(nid) or {}).get("local_images", []) or []
        unit = {
            "note_id": nid,
            "note_url": d.get("note_url", ""),
            "account_name": d.get("account_name", ""),
            "red_id": d.get("red_id", ""),
            "category": d.get("category", ""),
            "user_id": d.get("user_id", ""),
            "note_type": d.get("note_type", ""),
            "title": d.get("title", ""),
            "desc": d.get("desc", ""),
            "liked_count": d.get("liked_count", 0),
            "collected_count": d.get("collected_count", 0),
            "comment_count": d.get("comment_count", 0),
            "share_count": d.get("share_count", 0),
            "tags": d.get("tags", []),
            "upload_time": d.get("upload_time", ""),
            "ip_location": d.get("ip_location", ""),
            "image_urls": d.get("image_urls", []),
            "local_images": local_images,
            "ocr_images": ocr.get("images", []),
            "ocr_merged_text": merged_text,
            "ocr_language": ocr.get("language", "unknown"),
            "ocr_notes": ocr.get("notes", ""),
            "full_text_merged": full_text,
            "ocr_meta": {
                "image_count_used": o.get("image_count_used", 0),
                "image_count_total": o.get("image_count_total", 0),
                "truncated_images": o.get("truncated_images", 0),
                "model": ocr.get("_model", ""),
                "usage": ocr.get("_usage", {}),
            },
        }
        units.append(unit)

    units.sort(key=lambda x: int(x.get("liked_count") or 0), reverse=True)
    with UNITS_JSONL_PATH.open("w", encoding="utf-8") as f:
        for u in units:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
    UNITS_JSON_PATH.write_text(json.dumps(units, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "detail_count": len(details_map),
                "ocr_count": len(ocr_map),
                "unit_count": len(units),
                "output_json": str(UNITS_JSON_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["all", "detail", "ocr", "download", "merge"], default="all")
    parser.add_argument("--model", default="google/gemini-2.5-flash-lite")
    parser.add_argument("--max-images-per-note", type=int, default=6)
    parser.add_argument("--ocr-workers", type=int, default=2)
    parser.add_argument("--detail-workers", type=int, default=4)
    parser.add_argument("--download-workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    ensure_dirs()
    limit = args.limit if args.limit > 0 else None

    if args.stage in ("all", "detail"):
        notes = load_notes()
        cookie = read_cookie()
        process_details(
            notes=notes,
            cookie=cookie,
            limit=limit,
            start=args.start,
            download=(not args.no_download),
            workers=args.detail_workers,
        )

    if args.stage in ("all", "ocr"):
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for OCR stage")
        process_ocr(
            api_key=api_key,
            model=args.model,
            max_images=args.max_images_per_note,
            workers=args.ocr_workers,
            limit=limit,
            start=args.start,
        )

    if args.stage in ("all", "download"):
        process_download(workers=args.download_workers, limit=limit, start=args.start)

    if args.stage in ("all", "merge"):
        merge_units()


if __name__ == "__main__":
    main()
