"""Static HTML contact-sheet report — useful for sharing keepers with a client."""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

from . import thumb


def _img_data_uri(path: Path, content_hash: str) -> str:
    thumb_path = thumb.get_or_build(path, content_hash, long_edge=320)
    return "data:image/jpeg;base64," + base64.b64encode(thumb_path.read_bytes()).decode()


def render(conn: sqlite3.Connection, out_html: Path, verdict: str | None = "keeper") -> int:
    sql = (
        "SELECT i.path, i.content_hash, v.verdict, v.stars, v.label, v.reasons "
        "FROM images i JOIN verdicts v ON v.image_id = i.id"
    )
    params: tuple = ()
    if verdict:
        sql += " WHERE v.verdict = ?"
        params = (verdict,)
    sql += " ORDER BY i.capture_time NULLS LAST, i.id"
    rows = conn.execute(sql, params).fetchall()

    cards: list[str] = []
    for r in rows:
        path = Path(r["path"])
        if not path.exists():
            continue
        reasons = json.loads(r["reasons"]) if r["reasons"] else []
        try:
            data = _img_data_uri(path, r["content_hash"])
        except Exception:
            continue
        cards.append(
            f'''
            <figure class="card">
              <img src="{data}" alt="" />
              <figcaption>
                <div class="name">{path.name}</div>
                <div class="meta">{"★" * int(r["stars"] or 0)} · {r["verdict"]}</div>
                <div class="reasons">{", ".join(reasons)}</div>
              </figcaption>
            </figure>
            '''
        )

    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(
        f"""<!doctype html><html><head><meta charset="utf-8" />
<title>SnapGrade report</title>
<style>
body{{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:1rem}}
h1{{margin:0 0 1rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.75rem}}
.card{{background:#1c1c1c;border-radius:6px;overflow:hidden;margin:0}}
.card img{{width:100%;height:160px;object-fit:cover;display:block}}
.card figcaption{{padding:.4rem .6rem;font-size:.8rem}}
.name{{font-family:ui-monospace,monospace;color:#bbb;word-break:break-all}}
.meta{{color:#7c7;margin-top:.2rem}}
.reasons{{color:#fa3;font-size:.7rem;margin-top:.2rem}}
</style></head>
<body>
<h1>SnapGrade — {verdict or "all"} ({len(cards)} images)</h1>
<div class="grid">{"".join(cards)}</div>
</body></html>""",
        encoding="utf-8",
    )
    return len(cards)
