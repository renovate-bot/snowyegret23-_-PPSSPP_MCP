# PPSSPP MCP

**[ENGLISH](README.md) | KOREAN**

PPSSPP MCP는 [PPSSPP](https://www.ppsspp.org/)를 제어하고 조사하는 Windows 중심의 Model Context Protocol 서버입니다. PPSSPP의 WebSocket 원격 디버거와 Windows 프로세스 메모리 조사, 입력 자동화, 프로세스 실행, 비활성 창 스크린샷 기능을 결합합니다.

> [!IMPORTANT]
> 네이티브 디버거 입력과 렌더 프레임 캡처를 사용하려면 PPSSPP의 원격 디버거를 활성화하고 게임을 불러와야 합니다. XInput 및 패치된 키보드 입력, Windows 프로세스 메모리 조사, 비활성 창 캡처는 로컬에서 동작합니다.

## 주요 기능

- 디버거, 게임, CPU, 스레드 상태 조사
- 에뮬레이션 일시 정지 및 재개
- 디버거 표현식 평가 및 PSP 코드 디스어셈블
- 고급 작업을 위한 PPSSPP 디버거 이벤트 직접 전송
- 디지털 버튼 누르기, 여러 버튼 상태 설정, 아날로그 스틱 입력 전송
- 네이티브 WebSocket 입력에서 선택적 XInput, 패치된 비활성 키보드 입력 순으로 자동 폴백
- PPSSPP 프로세스 탐색 및 실행
- PPSSPP 창 열거 및 비활성 창 이미지 캡처
- PPSSPP 프로세스의 Windows 가상 메모리 영역 열거
- 프로세스 메모리 읽기 및 와일드카드 바이트 패턴 검색
- 지정한 인코딩으로 문자열을 검색 패턴으로 변환

## 요구 사항

- Windows
- Python 3.10 이상
- **Allow remote debugger**가 활성화된 PPSSPP
- 로컬 stdio 서버를 지원하는 MCP 클라이언트

기본 원격 디버거 연결 주소는 `127.0.0.1:7378`입니다.

## PPSSPP 설정

PPSSPP에서 **Settings > Tools > Developer tools**를 열고 **Allow remote debugger**를 활성화합니다. 기본 포트는 `7378`입니다.

디버거, 디스어셈블, 표현식, 입력 도구를 사용하기 전에 게임을 불러옵니다. PPSSPP에서 포트를 변경했다면 MCP 도구에도 같은 `host`와 `port` 값을 전달합니다.

## 설치

PowerShell에서 저장소 폴더로 이동한 뒤 실행합니다.

```powershell
python -m pip install -e .
```

선택적인 ViGEm/XInput 지원을 설치하려면 다음 명령을 사용합니다.

```powershell
python -m pip install -e ".[xinput]"
```

서버를 직접 실행하려면 다음 명령을 사용합니다.

```powershell
python -m ppsspp_mcp
```

서버는 stdio로 통신하므로 일반적으로 독립형 대화형 터미널이 아니라 MCP 클라이언트에서 실행합니다.

## Codex MCP 설정

PPSSPP MCP를 Codex의 로컬 stdio 서버로 등록하려면 `%USERPROFILE%\.codex\config.toml`에 다음 블록을 추가합니다. `C:\path\to\PPSSPP_MCP`는 이 저장소를 복제한 실제 경로로 변경하십시오.

```toml
[mcp_servers.ppsspp]
command = "python"
args = ["-m", "ppsspp_mcp"]
cwd = 'C:\path\to\PPSSPP_MCP'

[mcp_servers.ppsspp.env]
PYTHONPATH = 'C:\path\to\PPSSPP_MCP\src'
```

`python` 명령은 프로젝트 의존성을 설치한 Python 인터프리터를 가리켜야 합니다. `config.toml`을 변경한 뒤 Codex를 다시 시작합니다.

## 일반적인 작업 순서

1. PPSSPP 원격 디버거를 활성화하고 게임을 불러옵니다.
2. `debugger_status`, `game_status`, `cpu_status`로 연결 및 현재 상태를 확인합니다.
3. 스레드, 표현식, 디스어셈블을 안정적으로 조사하기 전에 `pause`를 사용합니다.
4. 필요에 따라 `thread_list`, `evaluate`, `disassemble`을 호출합니다.
5. `input_button_press`, `input_buttons_send`, `input_analog_send`로 입력을 자동화합니다.
6. 조사가 끝나면 `resume`을 호출합니다.

화면을 조사할 때는 잠시 디버거 stepping 상태로 전환해 PPSSPP WebSocket 디버거에서 렌더 프레임을 직접 읽고 원래 실행 상태를 복원하는 `take_screenshot`을 우선 사용합니다. 폴백 및 `capture_ppsspp_window`는 PPSSPP 창을 복원하거나 활성화하거나 포커스하지 않고 `PrintWindow`로 캡처합니다.

입력 도구의 `backend`에는 `auto`, `native`, `xinput`, `keyboard`를 지정할 수 있습니다. `auto`는 WebSocket 디버거, 선택적 ViGEm/XInput, 패치된 PPSSPP 빌드의 `PPSSPP.MCP.BackgroundKey` 순서로 시도합니다. `configure_background_input`을 한 번 실행하면 포커스 상실 시 일시 정지와 포커스 창 전용 게임패드 제한을 끕니다. 키보드 경로는 전경 창 API를 호출하지 않습니다.

호스트 프로세스 메모리를 조사하려면 Windows 가상 주소로 `read_process_memory`를 호출하기 전에 `list_ppsspp_processes`, `list_process_regions`, `find_process_pattern`을 사용합니다.

## 디버거 도구

| 영역 | 도구 |
| --- | --- |
| 상태 | `debugger_status`, `game_status`, `cpu_status`, `thread_list` |
| 코드 조사 | `evaluate`, `disassemble` |
| 실행 제어 | `pause`, `resume` |
| 고급 프로토콜 | `debugger_request` |
| 입력 | `input_button_press`, `input_buttons_send`, `input_analog_send`, `input_reset` |
| 백그라운드 설정 | `configure_background_input`, `background_input_status` |

`debugger_request`는 이벤트와 매개변수 객체를 PPSSPP에 직접 전송합니다. 전용 도구가 있다면 해당 도구를 우선 사용하고, 이벤트 계약을 알고 있을 때만 직접 요청을 사용하십시오.

## Windows 프로세스 및 캡처 도구

| 영역 | 도구 |
| --- | --- |
| 프로세스 제어 | `list_ppsspp_processes`, `launch_ppsspp` |
| 캡처 | `take_screenshot`, `list_ppsspp_windows`, `capture_ppsspp_window` |
| 메모리 영역 | `list_process_regions` |
| 메모리 접근 | `read_process_memory`, `find_process_pattern`, `pattern_from_text` |

프로세스 메모리 주소는 선택한 PPSSPP 프로세스의 Windows 가상 주소이며 PSP 에뮬레이션 주소로 자동 변환되지 않습니다. 프로세스 권한, 아키텍처, 활성 PPSSPP 인스턴스에 따라 메모리 접근 결과가 달라질 수 있습니다.

## 안전 주의사항

이 서버는 게임 입력 제어, 에뮬레이션 일시 정지 및 재개, PPSSPP 프로세스 조사, 대용량 메모리 읽기, 실행 파일 시작, 임의 경로에 스크린샷 저장을 수행할 수 있습니다. 로컬 MCP 클라이언트에서만 사용하고 민감한 작업을 승인하기 전에 도구 인수를 확인하십시오.

생성된 로그, 스크린샷, 가상 환경, 바이트코드, 빌드 결과물은 버전 관리에서 제외해야 합니다.

## 라이선스

이 프로젝트에는 [LICENSE](LICENSE)에 명시된 라이선스가 적용됩니다.
