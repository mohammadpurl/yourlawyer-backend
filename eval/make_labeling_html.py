"""
ابزار ساده برچسب‌گذاری: JSONL را به یک HTML محلی تبدیل می‌کند
تا بتوان relevant/irrelevant را راحت‌تر زد، سپس دوباره JSONL می‌نویسد.

Usage:
  python eval/make_labeling_html.py
  # فایل eval/results/relevance_labeling.html را در مرورگر باز کن،
  # برچسب بزن، دکمه Export را بزن و فایل دانلودشده را جای jsonl بگذار
  # یا از --apply-export استفاده کن بعد از ذخیره export.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

INPUT = (
    Path(__file__).resolve().parent / "results" / "relevance_scores_for_labeling.jsonl"
)
HTML_OUT = Path(__file__).resolve().parent / "results" / "relevance_labeling.html"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=INPUT)
    parser.add_argument("--html", type=Path, default=HTML_OUT)
    args = parser.parse_args()

    if not args.path.exists():
        print(f"Missing {args.path}; run collect_relevance_scores.py first")
        return 1

    rows = [
        json.loads(line)
        for line in args.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    data_json = json.dumps(rows, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"/>
<title>Relevance labeling</title>
<style>
body {{ font-family: sans-serif; margin: 1rem 2rem; background: #f7f5f0; }}
.card {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
.q {{ color: #444; font-size: 0.95rem; margin-bottom: 0.5rem; }}
.meta {{ color: #666; font-size: 0.85rem; }}
.preview {{ margin: 0.5rem 0; line-height: 1.5; }}
.score {{ font-weight: bold; }}
button {{ margin-left: 0.4rem; padding: 0.35rem 0.7rem; cursor: pointer; }}
button.rel {{ background: #d4edda; }}
button.irr {{ background: #f8d7da; }}
button.active-rel {{ outline: 2px solid #28a745; }}
button.active-irr {{ outline: 2px solid #dc3545; }}
#bar {{ position: sticky; top: 0; background: #f7f5f0; padding: 0.5rem 0; z-index: 2; }}
</style>
</head>
<body>
<div id="bar">
  <span id="progress"></span>
  <button onclick="exportJsonl()">Export JSONL</button>
</div>
<div id="list"></div>
<script>
const rows = {data_json};
const list = document.getElementById('list');
function refreshProgress() {{
  const labeled = rows.filter(r => r.label === 'relevant' || r.label === 'irrelevant').length;
  document.getElementById('progress').textContent = labeled + ' / ' + rows.length + ' labeled';
}}
function setLabel(i, label) {{
  rows[i].label = label;
  render();
}}
function render() {{
  list.innerHTML = '';
  rows.forEach((r, i) => {{
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `
      <div class="meta">${{r.eval_id}} · <span class="score">${{r.rerank_score}}</span> · ${{r.source || ''}}</div>
      <div class="q">${{r.question}}</div>
      <div class="preview">${{r.text_preview || ''}}</div>
      <div>
        <button class="rel ${{r.label==='relevant'?'active-rel':''}}" onclick="setLabel(${{i}},'relevant')">relevant</button>
        <button class="irr ${{r.label==='irrelevant'?'active-irr':''}}" onclick="setLabel(${{i}},'irrelevant')">irrelevant</button>
        <span class="meta">current: ${{r.label ?? 'null'}}</span>
      </div>`;
    list.appendChild(div);
  }});
  refreshProgress();
}}
function exportJsonl() {{
  const text = rows.map(r => JSON.stringify(r)).join('\\n') + '\\n';
  const blob = new Blob([text], {{type: 'application/jsonl'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'relevance_scores_for_labeling.jsonl';
  a.click();
}}
render();
</script>
</body>
</html>
"""
    args.html.write_text(html, encoding="utf-8")
    print(f"Wrote {args.html} ({len(rows)} rows). Open in browser, label, Export JSONL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
