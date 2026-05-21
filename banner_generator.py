#!/usr/bin/env python3
"""
GitHub profile banner generator.
Edit the CONFIG section, then run: python3 generate_banner.py
Commit the output banner.svg to your repo and reference it in README.md:
  ![banner](./banner.svg)
"""

# ── CONFIG ────────────────────────────────────────────────────────────────────

NAME        = "csheldrick"
SUBTITLE    = ""
OUTPUT      = "banner.svg"

WIDTH       = 1200
HEIGHT      = 260

COL_SPACING = 10        # px between columns; lower = denser
COL_X_START = 5
COL_X_END   = WIDTH - 10

# Fraction of columns that travel upward (0.0 = all down, 0.2 = 1 in 5 up)
UP_FRACTION = 0.0

# ── STREAM DEFINITIONS ───────────────────────────────────────────────────────
# Each stream is (css_class, characters)
# Classes: d=dim (.22 opacity), m=mid (.42), b=bright (.78)

STREAMS = [
    ("d", ["0","1","ア","4","ツ","0","ラ","7","オ","1","ヨ","0","ワ"]),
    ("m", ["ネ","1","0","6","カ","1","ミ","8","コ","0","ム","3","エ"]),
    ("b", ["1","ハ","0","5","シ","1","リ","9","ワ","0","タ","7","ク"]),
]

# Animation variation pools (cycled across columns)
#Y_OFFSETS = [-500,-520,-540,-560,-580,-600,-620,-510,-530,-550,-570,-590,-610]
Y_OFFSETS = list(range(-500, -1000, -20))
Y_OFFSETS += list(range(-990, -1000, 20))

# -1.1 x 4, -.5
BEGINS    = [
	-1.2, -2.3, -3.4, -4.5, -5.6, -6.1,
	-1.8, -2.9, -4.0, -5.1, -6.2, -1.5,
	-3.7, -2.6, -4.8, -5.3, -1.1, -3.2, 
	-6.0, -2.0, -4.3, -1.7, -5.8, -3.6, 
	-6.4, -2.1, -4.6, -1.4, -5.9, -3.0
]
BEGINS += BEGINS[::-1][1:]
DURATIONS = [6.7, 6.8, 6.9, 7.0, 7.1, 7.2, 7.3, 7.4, 7.5]
DURATIONS += DURATIONS[::-1][1:]

# ── TEMPLATE HELPERS ─────────────────────────────────────────────────────────

def stream_def(sid, css_class, chars):
    tspans = "\n        ".join(
        f'<tspan x="0" dy="{"0" if i == 0 else "13"}">{c}</tspan>'
        for i, c in enumerate(chars)
    )
    return f'''    <g id="{sid}">
      <text class="r {css_class}">
        {tspans}
      </text>
    </g>'''


def column(x, sid, y_start, duration, begin, go_up):
    if go_up:
        y_end = -HEIGHT - 100
        values = f"{x} {y_start};{x} {y_end}"
    else:
        y_end = HEIGHT + 60
        values = f"{x} {y_start};{x} {y_end}"
    return (
        f'  <g transform="translate({x} {y_start})">\n'
        f'    <use href="#{sid}"/>\n'
        f'    <animateTransform attributeName="transform" type="translate"'
        f' values="{values}" dur="{duration}s" begin="{begin}s" repeatCount="indefinite"/>\n'
        f'  </g>'
    )


# ── BUILD ─────────────────────────────────────────────────────────────────────

stream_ids = [f"s{i+1}" for i in range(len(STREAMS))]

defs_streams = "\n".join(
    stream_def(stream_ids[i], cls, chars)
    for i, (cls, chars) in enumerate(STREAMS)
)

cols = []
x = COL_X_START
i = 0
while x <= COL_X_END:
    sid      = stream_ids[i % len(stream_ids)]
    y_start  = Y_OFFSETS[i % len(Y_OFFSETS)]
    begin    = BEGINS[i % len(BEGINS)]
    duration = DURATIONS[i % len(DURATIONS)]
    go_up    = (i % round(1 / UP_FRACTION) == 0) if UP_FRACTION > 0 else False
    cols.append(column(x, sid, y_start, duration, begin, go_up))
    x += COL_SPACING
    i += 1

svg = f'''<svg width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#020406"/>
      <stop offset="100%" stop-color="#0d1117"/>
    </linearGradient>
    <filter id="g" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1"/>
    </filter>
    <style>
      .r {{ font-family: monospace; font-size: 13px; fill: #7ee787; filter: url(#g); }}
      .d {{ opacity: .22; }}
      .m {{ opacity: .42; }}
      .b {{ opacity: .78; }}
      .t {{ font-family: monospace; }}
    </style>
{defs_streams}
  </defs>
  <rect width="{WIDTH}" height="{HEIGHT}" fill="url(#bg)"/>
{chr(10).join(cols)}
  <rect width="{WIDTH}" height="{HEIGHT}" fill="#0d1117" opacity=".10"/>
  <g class="t" text-anchor="middle">
    <text x="{WIDTH//2}" y="{HEIGHT//2 - 7}"
      font-size="52" font-weight="700" fill="#f0f6fc" opacity=".96">{NAME}</text>
    <text x="{WIDTH//2}" y="{HEIGHT//2 + 27}"
      font-size="14" font-weight="500" fill="#8b949e" letter-spacing="2" opacity=".95">{SUBTITLE}</text>
  </g>
</svg>'''

with open(OUTPUT, "wb") as f:
    f.write(svg.encode())

print(f"Written {OUTPUT} ({len(cols)} columns, spacing={COL_SPACING}px)")