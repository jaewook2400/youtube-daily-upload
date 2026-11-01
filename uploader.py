#!/usr/bin/env python3
"""감시 폴더에서 가장 오래된 영상 1개를 골라 YouTube에 업로드한다 (하루 1회)."""

import argparse
import datetime as dt
import fcntl
import json
import logging
import random
import shutil
import sys
import time
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
TOKEN_PATH = BASE_DIR / "token.json"
LOG_DIR = BASE_DIR / "logs"
LOCK_PATH = BASE_DIR / ".uploader.lock"

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
RETRIABLE_STATUS = {500, 502, 503, 504}
MAX_RETRIES = 10
CHUNK_SIZE = 8 * 1024 * 1024

DEFAULT_CONFIG = {
    "watch_dir": "~/Desktop/record",
    "uploaded_dir": None,  # None이면 watch_dir/uploaded
    "privacy_status": "private",
    "category_id": "22",
    "title_template": "{title}",
    "description_template": "{title}\n\n업로드 날짜: {date}",
    "tags": [],
    "title_strip_suffixes": ["_compressed"],
    "extensions": [".mp4", ".mov", ".m4v", ".mkv"],
    "min_age_minutes": 10,
    "made_for_kids": False,
}

log = logging.getLogger("uploader")


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(LOG_DIR / "upload.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    log.addHandler(file_handler)
    log.addHandler(stream_handler)
    log.setLevel(logging.INFO)


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    else:
        log.warning("config.json 없음 — 기본 설정 사용")
    config["watch_dir"] = Path(config["watch_dir"]).expanduser()
    uploaded = config.get("uploaded_dir")
    config["uploaded_dir"] = (
        Path(uploaded).expanduser() if uploaded else config["watch_dir"] / "uploaded"
    )
    config["extensions"] = {e.lower() for e in config["extensions"]}
    return config


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"last_upload_date": None, "history": []}


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def pick_next_video(config: dict) -> Path | None:
    watch_dir: Path = config["watch_dir"]
    if not watch_dir.is_dir():
        log.error("감시 폴더가 없음: %s", watch_dir)
        return None
    cutoff = time.time() - config["min_age_minutes"] * 60
    candidates = []
    for p in watch_dir.iterdir():
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in config["extensions"]:
            continue
        mtime = p.stat().st_mtime
        if mtime > cutoff:
            log.info("최근 수정된 파일이라 건너뜀(녹화/복사 중일 수 있음): %s", p.name)
            continue
        candidates.append((mtime, p))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def clean_title(raw: str) -> str:
    # YouTube는 제목에 <, > 를 허용하지 않고 100자 제한이 있다
    title = raw.replace("<", "").replace(">", "").strip()
    return title[:100] or "Untitled"


def build_metadata(video: Path, config: dict) -> dict:
    # macOS 파일명은 NFD(자모 분리)라 그대로 쓰면 한글 제목이 깨져 보인다
    stem = unicodedata.normalize("NFC", video.stem)
    for suffix in config["title_strip_suffixes"]:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    base_title = stem.replace("_", " ").strip()
    today = dt.date.today().isoformat()

    fields = {"title": base_title, "date": today, "filename": video.name}
    meta = {
        "title": config["title_template"].format(**fields),
        "description": config["description_template"].format(**fields),
        "tags": list(config["tags"]),
        "privacy_status": config["privacy_status"],
    }

    sidecar = video.with_suffix(".json")
    if sidecar.exists():
        override = json.loads(sidecar.read_text(encoding="utf-8"))
        meta.update({k: v for k, v in override.items() if k in meta})
        log.info("사이드카 메타데이터 적용: %s", sidecar.name)

    meta["title"] = clean_title(meta["title"])
    return meta


def get_youtube_client():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not TOKEN_PATH.exists():
        raise RuntimeError("token.json 없음 — 먼저 `python auth.py`로 로그인하세요")
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("토큰이 유효하지 않음 — `python auth.py`로 다시 로그인하세요")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(youtube, video: Path, meta: dict, config: dict) -> str:
    import httplib2
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": str(config["category_id"]),
        },
        "status": {
            "privacyStatus": meta["privacy_status"],
            "selfDeclaredMadeForKids": bool(config["made_for_kids"]),
        },
    }
    media = MediaFileUpload(str(video), chunksize=CHUNK_SIZE, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    retry = 0
    last_logged = -1
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct // 10 != last_logged // 10:
                    log.info("업로드 진행: %d%%", pct)
                    last_logged = pct
            retry = 0
        except HttpError as e:
            if e.resp.status not in RETRIABLE_STATUS:
                raise
            error = f"HTTP {e.resp.status}"
        except (httplib2.HttpLib2Error, OSError) as e:
            error = repr(e)
        else:
            continue

        retry += 1
        if retry > MAX_RETRIES:
            raise RuntimeError(f"재시도 한도 초과: {error}")
        wait = min(2**retry, 300) + random.random()
        log.warning("일시적 오류(%s), %.0f초 후 재시도 (%d/%d)", error, wait, retry, MAX_RETRIES)
        time.sleep(wait)

    if "id" not in response:
        raise RuntimeError(f"예상치 못한 응답: {response}")
    return response["id"]


def move_to_uploaded(video: Path, config: dict) -> Path:
    dest_dir: Path = config["uploaded_dir"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / video.name
    if dest.exists():
        dest = dest_dir / f"{video.stem}_{int(time.time())}{video.suffix}"
    shutil.move(str(video), dest)
    sidecar = video.with_suffix(".json")
    if sidecar.exists():
        shutil.move(str(sidecar), dest.with_suffix(".json"))
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="업로드할 영상과 메타데이터만 출력")
    parser.add_argument("--force", action="store_true", help="오늘 이미 업로드했어도 실행")
    args = parser.parse_args()

    setup_logging()

    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("다른 업로드가 진행 중이라 종료")
        return 0

    config = load_config()
    state = load_state()
    today = dt.date.today().isoformat()

    if state.get("last_upload_date") == today and not args.force and not args.dry_run:
        log.info("오늘(%s) 이미 업로드함 — 종료", today)
        return 0

    video = pick_next_video(config)
    if video is None:
        log.info("업로드할 영상 없음 (%s)", config["watch_dir"])
        return 0

    meta = build_metadata(video, config)
    log.info("선택된 영상: %s", video.name)
    log.info("제목: %s | 공개: %s", meta["title"], meta["privacy_status"])

    if args.dry_run:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    try:
        youtube = get_youtube_client()
        video_id = upload(youtube, video, meta, config)
    except Exception:
        log.exception("업로드 실패: %s (파일은 그대로 두고 다음 실행 때 재시도)", video.name)
        return 1

    dest = move_to_uploaded(video, config)
    state["last_upload_date"] = today
    state.setdefault("history", []).append(
        {
            "date": today,
            "file": video.name,
            "title": meta["title"],
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
        }
    )
    save_state(state)
    log.info("업로드 완료: https://youtu.be/%s → %s", video_id, dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
