"""Writes the dark variant of each diagram: img/<name>.svg -> img/<name>-dark.svg.

The light SVG is the source. The dark one is the same drawing with its colors swapped for GitHub's dark theme;
the docs show the right one with <picture> and prefers-color-scheme. Run it after a change to a diagram:
python3 img/dark.py
"""
import pathlib
import re

# The light color -> its dark one. The page background is #0d1117 (GitHub's dark page); a white box on the page
# becomes #161b22, a little lighter than the page.
COLORS = {
    "#111827": "#e6edf3",  # text
    "#374151": "#c9d1d9",  # arrows, axis, the key's border
    "#4b5563": "#9da7b3",  # secondary text
    "#6b7280": "#8b949e",  # window borders, notes
    "#9ca3af": "#6e7681",  # lifelines, the empty text box
    "#e5e7eb": "#30363d",  # grey chat messages
    "#f3f4f6": "#21262d",  # window title bars
    "#f9fafb": "#161b22",  # the key's panel
    "#ffffff": "#161b22",  # boxes
    "#dbeafe": "#1c3557",  # blue fills: your message, speech
    "#eff6ff": "#0f2238",  # the EchoFox block, the client
    "#2563eb": "#58a6ff",  # blue borders, cursors
    "#ecfdf5": "#11281d",  # green fills: pieces
    "#f0fdf4": "#11281d",  # the server
    "#059669": "#3fb950",  # green borders
    "#047857": "#56d364",  # green text
    "#ffedd5": "#3a2a12",  # orange fills: the model works
    "#d97706": "#d29922",  # orange borders
    "#b91c1c": "#f85149",  # red: stop
    "#f87171": "#f87171",  # window buttons stay
    "#fbbf24": "#fbbf24",
    "#34d399": "#34d399",
}
# The page: the first rect of the drawing, white
PAGE = re.compile(r'<rect [^>]*fill="#ffffff"/>')


def dark(svg):
    page = PAGE.search(svg)
    if page is None or svg.find("<rect") != page.start():
        raise ValueError("the first rect is not a white page")
    svg = svg[:page.start()] + page.group(0).replace("#ffffff", "#0d1117") + svg[page.end():]

    def swap(m):
        color = m.group(0).lower()
        if color not in COLORS:
            raise ValueError(f"no dark color for {color}")
        return COLORS[color]
    # The page's own new color is not in the table, so skip it
    return re.sub(r"#(?!0d1117)[0-9a-fA-F]{6}\b", swap, svg)


here = pathlib.Path(__file__).parent
for light in sorted(here.glob("*.svg")):
    if light.stem.endswith("-dark"):
        continue
    out = light.with_name(f"{light.stem}-dark.svg")
    out.write_text(dark(light.read_text()))
    print(out.name)
