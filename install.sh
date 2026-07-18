#!/bin/sh
set -eu

REPOSITORY_ARCHIVE="${BHAJAN_INSTALL_SOURCE:-https://github.com/rithamnatani/bhajan/archive/refs/heads/main.zip}"

say() {
    printf '%s\n' "$*"
}

run_as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        say "This step needs administrator access, but sudo is unavailable."
        exit 1
    fi
}

install_ffmpeg() {
    if command -v ffmpeg >/dev/null 2>&1 &&
       command -v ffprobe >/dev/null 2>&1; then
        return
    fi

    say "Installing FFmpeg..."
    if command -v brew >/dev/null 2>&1; then
        brew install ffmpeg
    elif command -v apt-get >/dev/null 2>&1; then
        run_as_root apt-get update
        run_as_root apt-get install -y ffmpeg
    elif command -v dnf >/dev/null 2>&1; then
        run_as_root dnf install -y ffmpeg
    elif command -v pacman >/dev/null 2>&1; then
        run_as_root pacman -Sy --needed --noconfirm ffmpeg
    else
        say "Could not identify a supported package manager."
        say "Install ffmpeg and ffprobe, then run this installer again."
        exit 1
    fi
}

say "Installing bhajan and its system dependencies..."
install_ffmpeg

if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv with Astral's official installer..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        say "curl or wget is required to install uv."
        exit 1
    fi
fi

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    say "uv was installed but is not available in this shell."
    say "Open a new terminal and run this installer again."
    exit 1
fi

say "Installing bhajan as an isolated uv tool..."
uv tool install --force --python 3.12 "$REPOSITORY_ARCHIVE"
uv tool update-shell >/dev/null 2>&1 || true

say ""
say "bhajan installed successfully."
TOOL_BIN="$(uv tool dir --bin)"
"$TOOL_BIN/bhajan" --version
say ""
say 'Try: bhajan "INSERT_LINK_HERE" --gui -v'
say "If bhajan is not found by name yet, open a new terminal."
