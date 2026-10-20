# Research Radar Watchdog

`https://korean.streamlit.app/`의 공개 메인 화면만 확인하는 독립 Watchdog입니다. 사이트가 Streamlit 절전 화면일 때만 `Yes, get this app back up!` 버튼을 클릭하며, 검색·분석·업로드·저장 기능은 실행하지 않습니다.

## 안전 범위

- 정상 판별: `Research Radar`, `문장 분석 검색 시스템`, `개인 연구 자료 검색을 위한 사이트입니다.`가 모두 표시됨
- 구분 상태: `normal`, `sleeping`, `loading`, `app_error`, `unknown`
- 허용된 클릭: 정확한 이름의 Streamlit 깨우기 버튼 하나뿐
- 로그: UTC 점검 시각, 결과, 절전 여부, 깨우기 시도 여부, 총 소요시간만 출력
- 기존 Research Radar 및 GOKPOP 저장소와 코드·배포·예약을 공유하지 않음

## macOS 개발 환경

시스템 Python을 교체하지 않고 프로젝트 내부 Python 3.13 가상환경을 사용합니다.

```bash
cd "$HOME/Documents/Research_Radar_Watchdog"
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --requirement requirements.txt
python -m playwright install chromium
```

테스트와 실제 읽기 전용 확인:

```bash
python -m pytest -q
python -m watchdog.check_site --read-only
```

운영 모드에서는 절전 버튼이 실제로 확인된 경우에만 클릭합니다.

```bash
python -m watchdog.check_site
```

정상은 종료 코드 0, 절전 또는 로딩은 2, 앱 오류는 3, 확인 불가는 4를 반환합니다.

## GitHub Actions

`.github/workflows/research-radar-watchdog.yml`은 6시간마다 UTC `02:43`, `08:43`, `14:43`, `20:43`(KST `11:43`, `17:43`, `23:43`, `05:43`)에 예약되어 있습니다. 기존 GOKPOP watchdog의 UTC `00:17`, `06:17`, `12:17`, `18:17` 예약과 분리한 시각입니다. 저장소 변수 `RESEARCH_RADAR_WATCHDOG_ENABLED`가 정확히 `true`가 아니면 예약 job은 실행되지 않습니다. `workflow_dispatch` 수동 실행은 변수와 무관하게 사용할 수 있습니다.

이 Watchdog는 `schoolparkai/research-radar-watchdog` 독립 저장소에서 운영합니다. 예약 활성화는 수동 시험과 별도 승인 후 `RESEARCH_RADAR_WATCHDOG_ENABLED=true`로 변경할 때만 이루어집니다.
