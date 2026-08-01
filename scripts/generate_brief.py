#!/usr/bin/env python3
"""
Alvarez Comprehensive Intelligence Brief — generator
Runs every 2 days via GitHub Actions. Pulls 3-5 stories from all 20
registered sources (15 Gmail feeds + 5 web-search trade/local sources),
summarizes with Claude, renders branded HTML, and saves/sends the output.

Env vars required:
  ANTHROPIC_API_KEY
  GMAIL_CREDENTIALS_JSON   (service account or OAuth token blob)
  OUTPUT_MODE = "drive" | "email" | "local"   (default: local)
"""
import json
import os
import datetime
from pathlib import Path

import anthropic
# gmail_client is your existing helper module from the current repo —
# reuse whatever you already have wired for Gmail API auth/search/fetch.
from gmail_client import search_messages, fetch_message_body  # existing module

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config" / "sources.json").read_text())
LOOKBACK_DAYS = 1
STORIES_PER_SOURCE = "3 to 5"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def fetch_gmail_source(source: dict) -> str:
    """Pull raw text for one Gmail-based source over the lookback window."""
    query = f'from:{source["sender"]} newer_than:{LOOKBACK_DAYS}d'
    if source.get("subject_filter"):
        query += f' subject:"{source["subject_filter"]}"'
    messages = search_messages(query, max_results=5)
    if not messages:
        return ""  # triggers web fallback in build_source_block()
    bodies = [fetch_message_body(m["id"]) for m in messages]
    return "\n\n---\n\n".join(bodies)


def build_source_block(source: dict, raw_text: str) -> dict:
    """Package one source's raw content (or fallback flag) for the prompt."""
    return {
        "id": source["id"],
        "name": source["name"],
        "category": source["category"],
        "raw_text": raw_text,
        "needs_web_fallback": raw_text == "",
    }


def gather_all_sources() -> list:
    blocks = []
    for s in CONFIG["gmail_sources"]:
        raw = fetch_gmail_source(s)
        blocks.append(build_source_block(s, raw))
    for s in CONFIG["web_sources"]:
        # Web sources always go through Claude's web_search tool at
        # summarization time — no raw_text to pre-fetch here.
        blocks.append({
            "id": s["id"], "name": s["name"], "category": s["category"],
            "raw_text": "", "needs_web_fallback": True, "web_query": s["query"],
        })
    return blocks


SYSTEM_PROMPT = """You are building Michael O'Mara's bi-weekly Alvarez Intelligence Brief.

For EACH of the 20 sources provided, extract exactly 3 to 5 stories with:
- Headline (paraphrased, not copied verbatim)
- 1-sentence summary
- Direct source link
- One-line "Alvarez Signal": how it connects to HVAC/plumbing/construction
  operations, competitors (always pair Red Cap with Home Therapist if either
  appears), Florida regulation, labor market, financing, or AI tooling.

If a source's raw_text is empty, use the web_search tool with the provided
web_query (or the source name + "news") to find 3-5 recent stories instead.
If truly nothing recent exists, write "No new content this cycle" for that
source — do not fabricate stories.

End with a Strategic Flash table: Priority (🔴/🟡/🟢) | Action | Owner.

Output as clean structured JSON matching this shape:
{
  "brief_date": "...",
  "sources": [
    {"name": "...", "category": "...", "stories": [
      {"headline": "...", "summary": "...", "link": "...", "alvarez_signal": "..."}
    ]}
  ],
  "strategic_flash": [{"priority": "red|yellow|green", "action": "...", "owner": "..."}]
}
"""


def summarize_with_claude(blocks: list) -> dict:
    user_content = json.dumps(blocks, indent=2)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=32000,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_content}],
    )
    print(f"stop_reason: {response.stop_reason}")
    text_parts = [b.text for b in response.content if b.type == "text"]
    raw = "\n".join(text_parts).strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    if not raw:
        block_types = [b.type for b in response.content]
        print(f"WARNING: empty text response. Content block types: {block_types}")
        raise RuntimeError(
            f"Claude returned no text content (stop_reason={response.stop_reason}, "
            f"block_types={block_types}). Likely hit max_tokens before finishing — "
            f"consider raising max_tokens further or reducing sources per run."
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("---RAW RESPONSE (first 2000 chars)---")
        print(raw[:2000])
        raise


def render_html(brief: dict) -> str:
    template = (ROOT / "templates" / "brief_template.html").read_text()
    rows = []
    for src in brief["sources"]:
        rows.append(f'<h2 class="source-heading">{src["name"]} <span class="cat">{src["category"]}</span></h2>')
        if not src["stories"]:
            rows.append('<p class="no-content">No new content this cycle.</p>')
        for st in src["stories"]:
            rows.append(f'''
            <div class="story">
              <p class="headline"><a href="{st['link']}">{st['headline']}</a></p>
              <p class="summary">{st['summary']}</p>
              <p class="signal"><strong>Alvarez Signal:</strong> {st['alvarez_signal']}</p>
            </div>''')
    flash_rows = "".join(
        f'<tr><td class="pri-{f["priority"]}">{f["priority"].upper()}</td>'
        f'<td>{f["action"]}</td><td>{f["owner"]}</td></tr>'
        for f in brief["strategic_flash"]
    )
    return (template
            .replace("{{BRIEF_DATE}}", brief["brief_date"])
            .replace("{{SOURCE_BLOCKS}}", "\n".join(rows))
            .replace("{{FLASH_ROWS}}", flash_rows))


def main():
    blocks = gather_all_sources()
    brief = summarize_with_claude(blocks)
    html = render_html(brief)

    date_str = datetime.date.today().isoformat()
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    html_path = out_dir / f"Alvarez-Intel-Brief-{date_str}.html"
    json_path = out_dir / f"Alvarez-Intel-Brief-{date_str}.json"
    html_path.write_text(html)
    json_path.write_text(json.dumps(brief, indent=2))

    mode = os.environ.get("OUTPUT_MODE", "email")
    if mode in ("email", "both"):
        from gmail_client import send_html_email
        send_html_email(
            to="mgomara01@gmail.com",
            subject=f"Alvarez Intelligence Brief — {date_str}",
            html_body=html,
        )
    if mode in ("drive", "both"):
        # Requires a Drive-scoped credential in GMAIL_CREDENTIALS_JSON and
        # DRIVE_FOLDER_ID secret. Not wired yet — current token only has
        # gmail.readonly + gmail.send scopes. Add drive_client.py and the
        # drive.file scope later if Drive archiving is wanted alongside email.
        print("Drive delivery requested but not yet configured — skipping.")

    print(f"Brief generated: {html_path}")


if __name__ == "__main__":
    main()
