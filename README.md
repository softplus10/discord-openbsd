# Discord for OpenBSD

OpenBSD용 비공식 Discord 웹 앱 wrapper입니다. Qt6 WebEngine의 Chromium 엔진을
사용하며 Electron/Discord 데스크톱 바이너리는 사용하지 않습니다.
기본 대상은 **OpenBSD 8.0 amd64**입니다. 다른 OS 릴리스는 workflow의 `release`와
해당 OS에서의 테스트를 함께 변경해야 합니다.

## 동작

- `https://discord.com/channels/@me`를 독립 창에서 실행하고 로그인 상태를 보존합니다.
- 정확한 `https://discord.com`의 `/app`, `/channels`, `/login`, `/register`,
  `/invite`, `/verify`, `/reset`, `/reset-password`, `/claim` 경로만 창 안에서 엽니다.
- 마케팅 페이지, 개발자 포털, OAuth 승인 페이지, 외부 링크와 다운로드는 기본
  브라우저로 보냅니다. 팝업과 History API를 통한 주소 변경도 처리합니다.
- `file:`, `javascript:`, 임의의 OS 명령 프로토콜은 외부 실행하지 않습니다.
- Discord의 API·CDN·gateway·iframe 요청은 이 **최상위 탐색** 정책의 대상이 아닙니다.
- 마이크/카메라는 Discord origin에 한해 사용자 확인 후 허용합니다. F5로 새로고침합니다.

외부 브라우저에서 처리하는 OAuth 흐름은 wrapper와 쿠키를 공유하지 않습니다.
일반 Discord 로그인은 wrapper 안에서 진행하십시오. `discord.gg` 초대는 외부
브라우저에서 열립니다. wrapper 안에 초대를 열려면 `discord.com/invite/...`를 사용합니다.
로그인, MFA, 음성/영상, 화면 공유, 알림은 실제 OpenBSD 데스크톱에서 검증해야 합니다.
화면 공유와 데스크톱 알림은 이 wrapper에서 별도 구현하지 않았습니다.

## Tauri를 선택하지 않은 이유

OpenBSD는 Tauri 공식 지원 플랫폼이 아닙니다. OpenBSD의 WebKitGTK 제공 여부와
Tauri의 `wry`/`tao` 빌드·런타임 지원은 별개입니다. 이 프로젝트는 OpenBSD ports에
있는 Qt6 WebEngine을 사용해 별도의 Tauri 포팅 작업 없이 네이티브 빌드를 구성합니다.
Qt 엔진에는 OpenBSD 패치가 포함되므로, Chrome의 Linux 바이너리를 배포하지 않습니다.

## 빌드

OpenBSD에서 실행합니다. 일반 사용자로 앱을 실행하고, 엔진 sandbox를 끄지 마십시오.

```sh
doas pkg_add cmake ninja qt6-qtwebengine python3
sh scripts/build.sh
./out/discord-openbsd
```

`build/engine-version`이 실제 링크한 Qt/Chromium 버전을 조회합니다.
wrapper와 `release.json`, 배포 태그는 동일한
`CHROMIUM-qtQT-rACTION_RUN.ATTEMPT` 버전을 사용합니다. OpenBSD의 정확한 엔진
패키지 이름(`qt6-qtwebengine-...pN`)도 기록하여 보안 패치 재빌드를 감지합니다.

## 공개 Release와 서명키 설정

소스와 배포 파일을 **softplus10/discord-openbsd 한 저장소**에서 관리합니다.
저장소를 Public으로 설정하면 앱은 인증 키 없이 버전별 GitHub Release에서 업데이트를
내려받습니다. 별도 배포 저장소, PAT, 앱에 포함할 접근 키는 필요하지 않습니다.

1. GitHub의 Settings → General → Danger Zone → Change repository visibility에서
   저장소를 **Public**으로 바꿉니다.
2. OpenBSD에서 서명키를 만듭니다. 비밀키는 소스에 커밋하지 마십시오.

   ```sh
   signify -G -n -p update.pub -s update.sec
   ```

3. 이 저장소의 Settings → Secrets and variables → Actions에 두 secret을 등록합니다.

| Secret | 값 |
| --- | --- |
| `UPDATE_PUBLIC_KEY` | `update.pub` 전체 내용 |
| `UPDATE_SIGNING_KEY` | `update.sec` 전체 내용 |

`-n`은 CI에서 비밀번호 입력 없이 서명할 수 있게 합니다. 공개키는 따로 보관하고
최초 설치 시 신뢰할 수 있는 경로로 전달합니다. GitHub CLI 사용 예시는 다음과 같습니다.

```sh
gh secret set UPDATE_PUBLIC_KEY --repo softplus10/discord-openbsd < update.pub
gh secret set UPDATE_SIGNING_KEY --repo softplus10/discord-openbsd < update.sec
gh workflow run build.yml --repo softplus10/discord-openbsd
```

Secret에는 파일명 `update.sec`가 아닌 **파일 내용 전체**를 등록해야 합니다.
signify 키 파일은 `untrusted comment: ...` 첫 줄과 Base64 키 둘째 줄로 구성됩니다.
코드는 누락된 주석 줄과 문자로 붙여넣은 `\\n` 줄바꿈을 정규화하고,
실제 서명·검증으로 키 쌍을 확인한 후에만 Release를 생성합니다.

Release 작성은 Actions가 제공하는 `GITHUB_TOKEN`과 `contents: write` 권한을
사용합니다. 빌드/PR job에는 읽기 권한만 부여하고, main에서 빌드를 통과한 경우에만
별도의 publish job에 쓰기 권한과 서명키를 제공합니다. 토큰·비밀키는 앱에 포함하지
않습니다. 앱에는 업데이트 서명을 확인하는 **공개키**만 포함됩니다.

Actions variable `UPDATE_KEY_REVISION`을 증가시키면 소스/엔진 변경이 없어도 다시
배포합니다. 서명 공개키가 달라지는 교체는 자동으로 신뢰하지 않으며 별도의 수동
신뢰 이전이 필요합니다. GitHub 공개 배포 파일은 누구나 내려받을 수 있습니다.

## 주간 Action과 브라우저 업데이트

매주 월요일 **14:23 JST (05:23 UTC)**, main push, 수동 실행에 OpenBSD VM을 새로 띄우고 해당
릴리스 저장소의 최신 `qt6-qtwebengine` 패키지를 설치해 wrapper를 빌드합니다.
탐색 정책 C++ 테스트와 Python 업데이트 테스트가 통과한 경우에만 배포합니다.
엔진 패키지, Qt/Chromium 버전, 소스 commit, 키 revision이 그대로면 배포를 생략합니다.
빌드 결과는 Actions artifact로 저장됩니다. 배포 secrets가 아직 설정되지 않았으면
안내 메시지와 함께 서명된 Release 생성을 건너뛰며, 빌드/테스트는 계속 수행합니다.

OpenBSD가 배포하는 **엔진 패키지**를 확인하는 방식입니다. upstream Chromium의
신규 버전이 OpenBSD Qt WebEngine에 반영되기 전에는 그 버전으로 전환하지 않습니다.
Qt WebEngine/Chromium 전체 소스를 매주 컴파일하거나 엔진 공유 라이브러리를 앱에
묶는 workflow는 아닙니다. 엔진과 의존성은 OpenBSD 패키지 관리자가 관리합니다.

설치한 앱은 실행 시 하루에 한 번 공개 Release 채널을 백그라운드 확인합니다.
서명, SHA-256, OS/아키텍처, 증가하는 배포 순번, 엔진 패키지를 검증한 뒤 버전별
디렉터리에 설치하고 `current` symlink를 원자적으로 교체합니다. 새 wrapper는 다음
실행부터 적용되며 기존 버전과 로그인 데이터는 보존됩니다.

새 wrapper가 더 새 엔진 패키지를 요구하면 기존 앱을 유지합니다. 시스템 엔진은
관리자가 `doas pkg_add -u`로 갱신해야 합니다. 엔진을 먼저 갱신했다면 launcher가
최신 wrapper를 동기 확인하여 버전을 맞춥니다. OS 업그레이드는 자동으로 수행하지
않습니다. 업데이트 오류는 설치 경로의 `update.log`에서 확인합니다.

## 최초 설치

이 저장소의 [버전별 Release](https://github.com/softplus10/discord-openbsd/releases)에서 `discord-openbsd.tgz`, `manifest.json`,
`manifest.json.sig`를 내려받습니다. `openbsd-8.0-amd64` release는 최신 채널 포인터이며
manifest만 제공합니다. 공개키는 배포 파일과 별도로 신뢰한 키를 사용하십시오.

```sh
doas pkg_add qt6-qtwebengine python3
python3 scripts/install.py \
  --archive /path/to/discord-openbsd.tgz \
  --manifest /path/to/manifest.json \
  --signature /path/to/manifest.json.sig \
  --public-key /path/to/trusted-update.pub
~/.local/bin/discord-openbsd
```

앱은 `~/.local/share/discord-openbsd`에 설치됩니다. 업데이트는 공개 Release에서
인증 없이 받으므로 GitHub 로그인은 필요 없습니다. Discord 로그인은 별도입니다.
수동 업데이트 확인:

```sh
python3 ~/.local/share/discord-openbsd/current/update.py \
  --root ~/.local/share/discord-openbsd --force
```

## 검증 상태

첫 [OpenBSD Action](https://github.com/softplus10/discord-openbsd/actions/runs/40505546027)에서
OpenBSD 네이티브 빌드, 탐색 정책 C++ 테스트와 Python 업데이트 테스트가 통과했습니다.
서명키 형식 검사와 공개 배포 전환 후 로컬 Python 테스트는 21개를 통과했습니다.
실제 OpenBSD 데스크톱에서 Discord 로그인·MFA·음성/영상 동작은 아직 검증하지 못했습니다.
