# youtube_upload

`~/Desktop/record`에 넣어둔 영상을 **하루에 하나씩**, 가장 오래된 것부터 YouTube에 자동 업로드한다.
매일 09:00에 launchd가 실행하고, 업로드가 끝난 파일은 `~/Desktop/record/uploaded/`로 옮긴다.

## 동작 방식

1. `state.json`을 보고 오늘 이미 올렸으면 바로 종료한다. 하루에 여러 번 실행돼도 업로드는 1개뿐이다.
2. 감시 폴더에서 수정 시각이 가장 오래된 영상을 고른다. 마지막 수정이 10분 이내인 파일은 녹화나 복사가 아직 안 끝났을 수 있어서 건너뛴다.
3. 제목은 파일명에서 확장자와 `_compressed`를 떼고 `_`를 공백으로 바꿔 만든다. 예: `충만주의_compressed.mp4` → `충만주의`
4. 업로드에 성공하면 파일을 `uploaded/`로 옮기고 `state.json`에 기록한다. 실패하면 파일을 그대로 두므로 다음 실행 때 다시 시도한다.

### 영상별 메타데이터 지정 (선택)

영상 옆에 같은 이름의 `.json` 파일을 두면 기본값 대신 그 값을 쓴다.

```
~/Desktop/record/충만주의_compressed.mp4
~/Desktop/record/충만주의_compressed.json
```

```json
{
  "title": "충만주의에 대하여",
  "description": "오늘의 이야기",
  "tags": ["vlog", "생각"],
  "privacy_status": "public"
}
```

## 최초 설정

### 1. Google Cloud 설정

1. [Google Cloud Console](https://console.cloud.google.com/)에서 새 프로젝트를 만든다.
2. **API 및 서비스 → 라이브러리**에서 **YouTube Data API v3**를 사용 설정한다.
3. **OAuth 동의 화면**을 설정한다.
   - 사용자 유형: 외부(External)
   - 테스트 사용자에 업로드할 채널의 Google 계정을 추가한다.
   - 게시 상태를 **"프로덕션으로 푸시"**로 바꾼다. 테스트 상태로 두면 refresh token이 7일마다 만료돼서 매주 다시 로그인해야 한다. 앱 인증(verification)은 받지 않아도 된다. 로그인할 때 "확인되지 않은 앱" 경고가 뜨면 **고급 → 이동**을 누르면 된다.
4. **사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**에서 애플리케이션 유형을 **데스크톱 앱**으로 만든다.
5. JSON을 다운로드해서 이 폴더에 `client_secret.json`이라는 이름으로 저장한다.

### 2. 설치 및 로그인

```bash
./install.sh                 # venv 생성, 패키지 설치, config.json 생성, launchd 등록
.venv/bin/python auth.py     # 브라우저 로그인 → token.json 생성
```

### 3. macOS 권한 (중요)

launchd로 실행된 프로그램은 macOS 보호 정책 때문에 `~/Desktop`에 접근하지 못한다.
**시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한**에 아래 두 개를 추가한다.
`+` 버튼을 누른 뒤 `Cmd+Shift+G`로 경로를 입력하면 된다.

- `/bin/bash`
- `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12`

권한이 없으면 `logs/upload.log`에 `Operation not permitted` 오류가 남는다.

### 4. (선택) 09:00에 맥 깨우기

맥이 잠자기 상태였다면 깨어날 때 실행된다. 전원이 꺼져 있었다면 그날은 건너뛴다.
정시에 올리고 싶으면 예약 기상을 설정한다.

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 08:55:00
```

`pmset repeat`는 반복 일정을 하나만 저장한다. 이미 등록된 일정(예: 18:55 기상)이 있으면 덮어쓰니 주의한다.

## 공개 상태 관련 주의

YouTube는 **감사(audit)를 받지 않은 API 프로젝트로 올린 영상을 강제로 비공개로 잠근다.**
`config.json`의 `privacy_status`를 `public`으로 해도 비공개로 올라간다. 방법은 둘 중 하나다.

- YouTube Studio에서 직접 공개로 바꾼다.
- [YouTube API 감사 신청 양식](https://support.google.com/youtube/contact/yt_api_form)을 제출한다. 승인되면 설정값대로 공개된다.

일일 API 쿼터(10,000 units)는 하루 1개 업로드에 충분하다.

## 설정 (`config.json`)

| 키 | 기본값 | 설명 |
|---|---|---|
| `watch_dir` | `~/Desktop/record` | 감시 폴더 |
| `uploaded_dir` | `~/Desktop/record/uploaded` | 업로드 완료 파일 이동 위치 |
| `privacy_status` | `private` | `private` / `unlisted` / `public` |
| `category_id` | `22` | YouTube 카테고리 (22 = People & Blogs) |
| `title_template` | `{title}` | `{title}`, `{date}`, `{filename}` 사용 가능 |
| `description_template` | `{title}\n\n업로드 날짜: {date}` | 위와 같음 |
| `tags` | `[]` | 기본 태그 |
| `title_strip_suffixes` | `["_compressed"]` | 제목에서 뗄 파일명 접미사 |
| `min_age_minutes` | `10` | 이 시간 안에 수정된 파일은 건너뜀 |
| `made_for_kids` | `false` | 아동용 콘텐츠 여부 |

## 사용법

```bash
./run.sh --dry-run    # 다음에 올라갈 영상과 메타데이터만 확인
./run.sh              # 지금 실행 (오늘 이미 올렸으면 종료)
./run.sh --force      # 오늘 이미 올렸어도 하나 더 업로드

launchctl kickstart -k gui/$(id -u)/com.jaewook.youtube-upload   # launchd 경로로 즉시 실행
tail -f logs/upload.log                                          # 로그 확인
cat state.json                                                   # 업로드 기록 (videoId, URL)
```

자동 실행 해제:

```bash
launchctl bootout gui/$(id -u)/com.jaewook.youtube-upload
rm ~/Library/LaunchAgents/com.jaewook.youtube-upload.plist
```
