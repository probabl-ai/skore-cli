#!/usr/bin/env bash
# Install every skore-cli harness using vendor artifacts (never PATH stubs), so
# `is_harness_installed` is exercised against the command names the vendors
# really ship. Every step must run without a TTY: the Claude, OpenCode and Pi
# shell installers prompt for a package manager on /dev/tty, which no runner
# provides, so the npm packages are used instead.
set -euo pipefail

OS="${RUNNER_OS:-$(uname -s)}"

# Pinned so a vendor release cannot change what CI tests. Bump deliberately.
CLAUDE_VERSION="2.1.263"
OPENCODE_VERSION="1.18.29"
PI_VERSION="0.85.1"
CODEX_VERSION="0.153.4"
VSCODE_VERSION="1.136.1"
BOB_SHELL_VERSION="2.0.2"
BOB_IDE_VERSION="1.126.0+bob2.1.0"

CURL=(curl -fsSL --retry 3 --retry-delay 2)
NPM=(npm install -g --no-fund --no-audit)
# Inno Setup flags shared by the VS Code and Cursor user installers.
INNO_FLAGS="/VERYSILENT /NORESTART /MERGETASKS=!runcode"

append_path() {
  local dir="$1"
  if [[ -d "$dir" ]]; then
    echo "$dir" >> "${GITHUB_PATH:-/dev/null}"
    export PATH="$dir:$PATH"
  fi
}

# The Windows user installers each nest their CLI shim differently, so find it
# rather than encode a per-vendor layout that only fails once CI runs.
append_shim_dir() {
  local shim="$1" root="$2" found
  found="$(find "$root" -maxdepth 6 -name "$shim" -print -quit 2>/dev/null || true)"
  if [[ -n "$found" ]]; then
    append_path "$(dirname "$found")"
  else
    echo "warning: no $shim found under $root" >&2
  fi
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

apt_install() {
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

run_inno_installer() {
  local exe="$1"
  # -PassThru plus an explicit exit is what surfaces a failed install: a bare
  # Start-Process reports success no matter what the installer did.
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command \
    "\$p = Start-Process -FilePath '$(cygpath -w "$exe")' -ArgumentList '${INNO_FLAGS}' -Wait -PassThru; exit \$p.ExitCode"
}

# Resolve a download URL from Cursor's release API. Cursor publishes no
# version-pinned endpoint, so the current stable build is what CI gets.
cursor_download_url() {
  local platform="$1" key="$2"
  "${CURL[@]}" -A "Mozilla/5.0 (compatible; skore-cli-ci)" \
    "https://cursor.com/api/download?platform=${platform}&releaseTrack=stable" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['$key'])"
}

install_npm_harnesses() {
  "${NPM[@]}" "@anthropic-ai/claude-code@${CLAUDE_VERSION}"
  "${NPM[@]}" "opencode-ai@${OPENCODE_VERSION}"
  "${NPM[@]}" "@openai/codex@${CODEX_VERSION}"
  # Pi documents --ignore-scripts for npm installs.
  "${NPM[@]}" --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}"
}

install_vscode() {
  case "$OS" in
    Linux)
      "${CURL[@]}" "https://update.code.visualstudio.com/${VSCODE_VERSION}/linux-deb-x64/stable" \
        -o /tmp/vscode.deb
      sudo apt-get update
      apt_install /tmp/vscode.deb
      ;;
    macOS)
      "${CURL[@]}" "https://update.code.visualstudio.com/${VSCODE_VERSION}/darwin-universal/stable" \
        -o /tmp/vscode.zip
      sudo unzip -q -o /tmp/vscode.zip -d /Applications
      ;;
    Windows)
      "${CURL[@]}" "https://update.code.visualstudio.com/${VSCODE_VERSION}/win32-x64-user/stable" \
        -o /tmp/vscode-setup.exe
      run_inno_installer /tmp/vscode-setup.exe
      ;;
  esac
}

install_cursor() {
  case "$OS" in
    Linux)
      # The CDN rejects python-urllib with HTTP 403; curl with a UA works.
      "${CURL[@]}" -A "Mozilla/5.0 (compatible; skore-cli-ci)" \
        "$(cursor_download_url linux-x64 debUrl)" -o /tmp/cursor.deb
      apt_install /tmp/cursor.deb
      ;;
    macOS)
      "${CURL[@]}" -A "Mozilla/5.0 (compatible; skore-cli-ci)" \
        "$(cursor_download_url darwin-universal downloadUrl)" -o /tmp/cursor.dmg
      hdiutil attach -nobrowse -quiet -mountpoint /Volumes/cursor-ci /tmp/cursor.dmg
      sudo cp -R "/Volumes/cursor-ci/Cursor.app" /Applications/
      hdiutil detach -quiet /Volumes/cursor-ci
      ;;
    Windows)
      "${CURL[@]}" -A "Mozilla/5.0 (compatible; skore-cli-ci)" \
        "$(cursor_download_url win32-x64-user downloadUrl)" -o /tmp/cursor-setup.exe
      run_inno_installer /tmp/cursor-setup.exe
      ;;
  esac
}

# Bob IDE publishes no static download URL. The releases page POSTs these form
# fields and the endpoint 302s to a presigned object-storage link that expires
# after 60 seconds, so the artifact has to be fetched in one shot. The method
# stays implicit: forcing it with -X POST would also apply to the redirect, and
# the presigned link is signed for GET, which answers 403 to anything else.
bob_ide_download() {
  local platform="$1" arch="$2" out="$3"
  shift 3
  "${CURL[@]}" \
    --data-urlencode "platform=${platform}" \
    --data-urlencode "architecture=${arch}" \
    --data-urlencode "version=${BOB_IDE_VERSION}" \
    "$@" "https://bob.ibm.com/api/download/bobide" -o "$out"
}

install_bob_ide() {
  case "$OS" in
    Linux)
      bob_ide_download linux amd64 /tmp/bobide.deb --data-urlencode "packageType=deb"
      apt_install /tmp/bobide.deb
      ;;
    macOS)
      bob_ide_download darwin arm64 /tmp/bobide.pkg
      sudo installer -pkg /tmp/bobide.pkg -target /
      ;;
    Windows)
      bob_ide_download windows x64 /tmp/bobide-setup.exe
      run_inno_installer /tmp/bobide-setup.exe
      ;;
  esac
}

install_bob_shell() {
  # Preselecting the package manager is mandatory, not a nicety: with more than
  # one manager on PATH the installer loops on an empty read until the job is
  # killed (the PowerShell variant raises ContainsKey(null) on every pass).
  case "$OS" in
    Windows)
      powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command \
        "& ([scriptblock]::Create((irm https://bob.ibm.com/download/bobshell.ps1))) -pm npm -v ${BOB_SHELL_VERSION}"
      ;;
    *)
      "${CURL[@]}" https://bob.ibm.com/download/bobshell.sh \
        | bash -s -- --pm npm --version "${BOB_SHELL_VERSION}"
      ;;
  esac
}

install_npm_harnesses
install_vscode
install_cursor
install_bob_shell
install_bob_ide

if command -v npm >/dev/null 2>&1; then
  npm_bin="$(npm prefix -g)"
  [[ "$OS" == "Windows" ]] || npm_bin="${npm_bin}/bin"
  append_path "$npm_bin"
fi
append_path "$HOME/.local/bin"
case "$OS" in
  macOS)
    append_path "/Applications/Visual Studio Code.app/Contents/Resources/app/bin"
    append_path "/Applications/Cursor.app/Contents/Resources/app/bin"
    ;;
  Windows)
    programs="$(cygpath -u "${LOCALAPPDATA}")/Programs"
    echo "installed under $programs:" && ls -1 "$programs" || true
    append_shim_dir code.cmd "$programs"
    append_shim_dir cursor.cmd "$programs"
    append_shim_dir bobide.cmd "$programs"
    ;;
esac

for name in claude opencode pi codex cursor bob; do
  need_cmd "$name"
  command -v "$name"
done

# Bob IDE ships no command on macOS, where skore-cli detects the bundle instead.
if [[ "$OS" == "macOS" ]]; then
  if [[ ! -d "/Applications/IBM Bob.app" ]]; then
    echo "missing Bob IDE bundle: /Applications/IBM Bob.app" >&2
    exit 1
  fi
else
  need_cmd bobide
  command -v bobide
fi
if command -v code >/dev/null 2>&1; then
  command -v code
elif command -v code-insiders >/dev/null 2>&1; then
  command -v code-insiders
else
  echo "missing required command: code or code-insiders" >&2
  exit 1
fi
