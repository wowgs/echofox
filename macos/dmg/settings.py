# The window of EchoFox.dmg, for dmgbuild (build-app.sh --dmg passes -D app=, -D icon=, -D background=): the app
# on the left, a link to /Applications on the right, an arrow and "Drag EchoFox to Applications" between them on the
# background (background.svg, made into background.tiff at 1x and 2x). The image is compressed with lzma (ULMO): of
# the formats, it made the smallest dmg, 53 MB against 79 MB for zlib, and opened in 2.8 s (2026-10-26, M5,
# docs/design/7-distribution.md). dmgbuild reads this file as Python, with `defines` set.
import os.path

app = defines["app"]  # noqa: F821
icon = defines["icon"]  # noqa: F821  (the volume's icon: the app's)
background = defines["background"]  # noqa: F821  (dmg/background.tiff)

format = "ULMO"
filesystem = "APFS"
files = [app]
symlinks = {"Applications": "/Applications"}

# The window: the same size as the background; icons 128 pt, where background.svg leaves room for them
window_rect = ((200, 120), (660, 400))
icon_size = 128
text_size = 13
icon_locations = {os.path.basename(app): (170, 175), "Applications": (490, 175)}
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
default_view = "icon-view"
show_icon_preview = False
