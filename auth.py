#!/usr/bin/env python3
"""최초 1회 실행: 브라우저로 Google 로그인 후 token.json을 만든다."""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = Path(__file__).resolve().parent
CLIENT_SECRET_PATH = BASE_DIR / "client_secret.json"
TOKEN_PATH = BASE_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise SystemExit(f"{CLIENT_SECRET_PATH} 가 없습니다. README의 Google Cloud 설정을 먼저 하세요.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    # prompt=consent 로 refresh_token이 항상 발급되도록 한다
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    TOKEN_PATH.chmod(0o600)
    print(f"저장 완료: {TOKEN_PATH}")


if __name__ == "__main__":
    main()
