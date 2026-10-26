# The versions that a bundled EchoFox.app carries (build-app.sh --bundle), each pinned with its checksum or commit,
# so that a build is the same everywhere (docs/design/7-distribution.md).

# The oldest macOS that the app runs on. build-app.sh builds llama-server and the app's Info.plist for it and refuses a
# bundle with any executable or library that needs a newer one; Package.swift says the same (.macOS(.v14)).
MACOS_MIN=14.0

# CPython from python-build-standalone (Astral): relocatable, for Apple Silicon. The SHA-256 is the release's own
# (SHA256SUMS and the asset's digest agree, 2026-10-25).
PYTHON_RELEASE=20261021
PYTHON_FILE=cpython-3.14.9+20261021-aarch64-apple-darwin-install_only_stripped.tar.gz
PYTHON_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20261021/cpython-3.14.9%2B20261021-aarch64-apple-darwin-install_only_stripped.tar.gz
PYTHON_SHA256=9f8c3480b8f0db553c270db548e8a21ae8e39df412e5661d66e8050c5c6ed2a8

# llama.cpp: the commit of the llama-server that the dictation runs on (0.6.0, build 11429, 2026-10-05), built with
# Metal into one binary without shared libraries.
LLAMA_REPO=https://github.com/ggml-org/llama.cpp
LLAMA_COMMIT=d81235049384534c167caea52b85a694f6103d14
