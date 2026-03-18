# Shutdown Scheduler

깔끔한 UI로 종료 시간을 고르면, 윈도우가 그 시각에 자동으로 종료되도록 예약해주는 데스크톱 앱입니다.

## 주요 기능

- 날짜와 시간을 직접 고르는 종료 예약
- `30분 뒤`, `1시간 뒤`, `2시간 뒤`, `오늘 23:00` 빠른 예약 버튼
- 강제 종료 옵션 지원
- 앱을 껐다 켜도 예약 상태 복구
- Windows용 실행 파일 제공

## 바로 사용하기

가장 쉬운 방법은 GitHub Releases에서 Windows ZIP 파일을 내려받아 압축을 풀고 실행하는 것입니다.

1. Releases 페이지에서 최신 버전을 다운로드합니다.
2. ZIP 압축을 풉니다.
3. `ShutdownScheduler.exe`를 실행합니다.

주의:

- 폴더형 배포이므로 `_internal` 폴더와 `ShutdownScheduler.exe`를 함께 유지해야 합니다.
- 예약 취소는 앱 안의 `예약 취소` 버튼으로 할 수 있습니다.

## 실행 환경

- Windows 10 / 11

## 소스에서 실행하기

### 1. Python 준비

Python 3.13 기준으로 개발되었습니다.

### 2. 가상환경 생성

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. 앱 실행

```powershell
python .\shutdown_scheduler.py
```

## 빌드 방법

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

빌드 결과물은 아래 경로에 생성됩니다.

```text
dist\ShutdownScheduler\ShutdownScheduler.exe
```

## 프로젝트 구조

```text
shutdown_scheduler.py   # 메인 앱
build.ps1              # Windows 배포 빌드 스크립트
assets/                # 앱 아이콘
requirements.txt       # Python 의존성
```

## 기술 스택

- Python 3.13
- PySide6
- PyInstaller

## 라이선스

MIT License
