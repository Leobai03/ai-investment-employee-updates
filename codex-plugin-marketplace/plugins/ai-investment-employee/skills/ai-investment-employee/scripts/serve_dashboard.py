#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import threading
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse


PROFILE_FILE = "00_老板投资说明书.md"
WATCHLIST_FILE = "01_自选公司.md"
SECTOR_FILE = "02_重点板块.md"
DECISION_FILE = "04_决策日志.md"
PENDING_FILE = "05_待确认记忆.md"
FEEDBACK_FILE = "06_老板纠正与反馈.md"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def strip_markdown(value: str) -> str:
    value = re.sub(r"[`*_>#]", "", value)
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    return value.strip()


def profile_value(text: str, label: str, default: str = "待确认") -> str:
    match = re.search(rf"^-\s*{re.escape(label)}[：:]\s*(.+)$", text, re.MULTILINE)
    return strip_markdown(match.group(1)) if match else default


def markdown_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noreferrer">\1</a>',
        escaped,
    )
    escaped = re.sub(
        r"(?<![\"'=])(https?://[^\s<]+)",
        r'<a href="\1" target="_blank" rel="noreferrer">\1</a>',
        escaped,
    )
    return escaped


def render_markdown(text: str) -> str:
    if not text.strip():
        return '<div class="empty">暂时没有内容</div>'

    output: list[str] = []
    in_list = False
    in_quote = False
    in_code = False
    code_lines: list[str] = []

    def close_blocks() -> None:
        nonlocal in_list, in_quote
        if in_list:
            output.append("</ul>")
            in_list = False
        if in_quote:
            output.append("</blockquote>")
            in_quote = False

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            close_blocks()
            if in_code:
                output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            close_blocks()
            continue
        if line.startswith("### "):
            close_blocks()
            output.append(f"<h4>{markdown_inline(line[4:])}</h4>")
        elif line.startswith("## "):
            close_blocks()
            output.append(f"<h3>{markdown_inline(line[3:])}</h3>")
        elif line.startswith("# "):
            close_blocks()
            output.append(f"<h2>{markdown_inline(line[2:])}</h2>")
        elif line.startswith("> "):
            if in_list:
                output.append("</ul>")
                in_list = False
            if not in_quote:
                output.append("<blockquote>")
                in_quote = True
            output.append(f"<p>{markdown_inline(line[2:])}</p>")
        elif re.match(r"^[-*]\s+", line):
            if in_quote:
                output.append("</blockquote>")
                in_quote = False
            if not in_list:
                output.append("<ul>")
                in_list = True
            item = re.sub(r"^[-*]\s+", "", line)
            output.append(f"<li>{markdown_inline(item)}</li>")
        elif line.startswith("|"):
            close_blocks()
            output.append(f'<div class="mono-row">{markdown_inline(line)}</div>')
        else:
            close_blocks()
            output.append(f"<p>{markdown_inline(line)}</p>")

    close_blocks()
    if in_code:
        output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(output)


def parse_table(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return [], []
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    headers = rows[0]
    data = [
        row
        for row in rows[1:]
        if row and not all(re.fullmatch(r"[-: ]+", cell or "-") for cell in row)
    ]
    return headers, data


def render_table(text: str) -> str:
    headers, rows = parse_table(text)
    if not headers or not rows:
        return '<div class="empty">还没有内容。回到 Codex 说“加入自选”即可。</div>'
    head = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{markdown_inline(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def meaningful_count(text: str) -> int:
    ignored = {"待确认", "系统推测但老板尚未确认的偏好只能放在这里。"}
    count = 0
    for line in text.splitlines():
        stripped = strip_markdown(line.lstrip("- ").strip())
        if stripped and not line.startswith("#") and stripped not in ignored:
            count += 1
    return count


class Dashboard:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.report_dir = self.data_dir / "reports"

    def state(self) -> dict[str, object]:
        profile = read_text(self.data_dir / PROFILE_FILE)
        watchlist = read_text(self.data_dir / WATCHLIST_FILE)
        sectors = read_text(self.data_dir / SECTOR_FILE)
        decisions = read_text(self.data_dir / DECISION_FILE)
        pending = read_text(self.data_dir / PENDING_FILE)
        feedback = read_text(self.data_dir / FEEDBACK_FILE)

        _, watch_rows = parse_table(watchlist)
        _, sector_rows = parse_table(sectors)
        reports = sorted(
            self.report_dir.rglob("*.md") if self.report_dir.exists() else [],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return {
            "profile": profile,
            "watchlist": watchlist,
            "sectors": sectors,
            "decisions": decisions,
            "pending": pending,
            "feedback": feedback,
            "watch_count": len(watch_rows),
            "sector_count": len(sector_rows),
            "report_count": len(reports),
            "pending_count": meaningful_count(pending),
            "reports": reports,
            "primary_markets": profile_value(profile, "重点市场"),
            "horizon": profile_value(profile, "投资周期"),
            "updated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        }

    def report_link(self, path: Path) -> str:
        relative = path.relative_to(self.data_dir).as_posix()
        return f"/report?path={quote(relative)}"

    def page(self) -> str:
        state = self.state()
        reports: list[Path] = state["reports"]  # type: ignore[assignment]
        recent_reports = reports[:8]
        if recent_reports:
            report_items = "".join(
                f"""
                <a class="report-item" href="{self.report_link(path)}">
                  <span class="report-type">{html.escape(path.parent.name)}</span>
                  <span class="report-name">{html.escape(path.stem)}</span>
                  <span class="report-time">{datetime.fromtimestamp(path.stat().st_mtime).strftime('%m-%d %H:%M')}</span>
                </a>
                """
                for path in recent_reports
            )
        else:
            report_items = '<div class="empty">还没有研究报告。去 Codex 说“生成今天的投研晨报”。</div>'

        prompts = [
            ("生成晨报", "根据我的偏好和自选公司，生成今天的投研晨报，保存后告诉我三个最重要的变化。"),
            ("研究公司", "研究腾讯，并和上一次判断做对比。先给结论，再给证据、反方观点和待核验项。"),
            ("记住偏好", "记住：我重点看A股和港股，科技和消费是长期关注板块。"),
            ("本周复盘", "汇总我本周的研究、判断变化和下周需要继续核验的事项。"),
        ]
        prompt_buttons = "".join(
            f'<button class="prompt" data-copy="{html.escape(value, quote=True)}"><b>{html.escape(title)}</b><span>{html.escape(value)}</span></button>'
            for title, value in prompts
        )

        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 投研数字员工</title>
  <style>
    :root {{
      --bg: #071019;
      --panel: rgba(15, 26, 38, .88);
      --panel-2: rgba(10, 20, 31, .95);
      --line: rgba(155, 180, 205, .17);
      --text: #eff4f8;
      --muted: #91a2b4;
      --gold: #d6a84f;
      --blue: #4d8dff;
      --green: #54c6a5;
      --purple: #9d7df5;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at 12% 4%, rgba(214, 168, 79, .14), transparent 28%),
        radial-gradient(circle at 86% 8%, rgba(77, 141, 255, .16), transparent 30%),
        linear-gradient(150deg, #071019 0%, #07111d 55%, #050b12 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image: linear-gradient(rgba(255,255,255,.022) 1px, transparent 1px),
                        linear-gradient(90deg, rgba(255,255,255,.022) 1px, transparent 1px);
      background-size: 40px 40px;
    }}
    .shell {{ display: grid; grid-template-columns: 245px minmax(0, 1fr); min-height: 100vh; }}
    aside {{
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 32px 22px;
      border-right: 1px solid var(--line);
      background: rgba(4, 10, 16, .76);
      backdrop-filter: blur(18px);
    }}
    .brand {{ display: flex; gap: 13px; align-items: center; margin-bottom: 44px; }}
    .logo {{
      width: 43px; height: 43px; border-radius: 14px;
      display: grid; place-items: center; color: #08111a; font-weight: 900;
      background: linear-gradient(135deg, #f4d990, #c38c2f);
      box-shadow: 0 8px 24px rgba(214, 168, 79, .22);
    }}
    .brand strong {{ display: block; font-size: 17px; }}
    .brand small {{ color: var(--muted); }}
    nav a {{
      display: block; color: var(--muted); text-decoration: none;
      padding: 11px 13px; border-radius: 11px; margin: 4px 0; font-size: 14px;
    }}
    nav a:hover {{ color: var(--text); background: rgba(255,255,255,.055); }}
    .local {{
      position: absolute; left: 22px; right: 22px; bottom: 25px;
      padding: 14px; border: 1px solid var(--line); border-radius: 14px;
      color: var(--muted); font-size: 12px; line-height: 1.7;
    }}
    .dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--green); margin-right: 6px; }}
    main {{ padding: 42px 46px 70px; max-width: 1500px; width: 100%; margin: 0 auto; }}
    header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(30px, 4vw, 48px); letter-spacing: -.04em; }}
    .subtitle {{ color: var(--muted); font-size: 15px; }}
    .stamp {{ text-align: right; color: var(--muted); font-size: 12px; line-height: 1.7; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px; }}
    .metric, .panel {{
      background: linear-gradient(145deg, rgba(18, 31, 45, .92), rgba(9, 19, 29, .92));
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 18px 45px rgba(0,0,0,.18);
    }}
    .metric {{ padding: 20px; min-height: 116px; }}
    .metric small {{ color: var(--muted); }}
    .metric strong {{ display: block; font-size: 28px; margin-top: 13px; }}
    .gold strong {{ color: #eccb7f; }} .blue strong {{ color: #79a8ff; }}
    .green strong {{ color: #77d7bd; }} .purple strong {{ color: #b59cff; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(320px, .8fr); gap: 18px; margin-bottom: 18px; align-items: start; }}
    .panel {{ padding: 25px; overflow: hidden; }}
    .panel h2.section {{
      font-size: 18px; margin: 0 0 20px; display: flex; justify-content: space-between; align-items: center;
    }}
    #profile {{ max-height: 650px; overflow: auto; }}
    .tag {{ font-size: 11px; color: var(--gold); background: rgba(214,168,79,.1); padding: 5px 9px; border-radius: 99px; }}
    .markdown {{ color: #cbd5df; line-height: 1.8; font-size: 14px; }}
    .markdown h2 {{ color: var(--text); font-size: 20px; margin: 6px 0 14px; }}
    .markdown h3 {{ color: #e7edf3; font-size: 15px; margin: 20px 0 8px; }}
    .markdown h4 {{ color: #e7edf3; }}
    .markdown p {{ margin: 8px 0; }}
    .markdown ul {{ padding-left: 19px; }}
    .markdown blockquote {{ margin: 12px 0; padding: 10px 15px; border-left: 3px solid var(--gold); background: rgba(214,168,79,.06); }}
    code {{ color: #c7e1ff; background: rgba(77,141,255,.11); padding: 2px 5px; border-radius: 5px; }}
    pre {{ white-space: pre-wrap; background: #060d14; border: 1px solid var(--line); padding: 14px; border-radius: 12px; }}
    .prompt {{
      width: 100%; text-align: left; color: var(--text); cursor: pointer;
      border: 1px solid var(--line); border-radius: 14px; padding: 14px 15px; margin-bottom: 10px;
      background: rgba(255,255,255,.025); transition: .2s ease;
    }}
    .prompt:hover {{ transform: translateY(-1px); border-color: rgba(214,168,79,.45); background: rgba(214,168,79,.06); }}
    .prompt b {{ display: block; margin-bottom: 5px; }}
    .prompt span {{ display: block; color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th {{ color: var(--muted); text-align: left; font-weight: 500; border-bottom: 1px solid var(--line); padding: 11px; }}
    td {{ color: #d8e0e8; border-bottom: 1px solid rgba(155,180,205,.09); padding: 13px 11px; min-width: 90px; }}
    .reports {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }}
    .report-item {{
      display: grid; grid-template-columns: 68px 1fr auto; gap: 10px; align-items: center;
      color: var(--text); text-decoration: none; padding: 13px; border-radius: 12px; border: 1px solid var(--line);
      background: rgba(255,255,255,.02);
    }}
    .report-item:hover {{ border-color: rgba(77,141,255,.42); background: rgba(77,141,255,.055); }}
    .report-type {{ color: #7daaff; font-size: 11px; text-transform: uppercase; }}
    .report-name {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px; }}
    .report-time {{ color: var(--muted); font-size: 11px; }}
    .empty {{ color: var(--muted); padding: 22px 0; font-size: 13px; }}
    .dual {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .mono-row {{ color: var(--muted); font-family: ui-monospace, monospace; overflow-x: auto; white-space: nowrap; }}
    .toast {{
      position: fixed; right: 28px; bottom: 28px; padding: 13px 17px; border-radius: 12px;
      background: #e9c577; color: #0b1219; font-weight: 700; opacity: 0; transform: translateY(10px);
      transition: .2s ease; pointer-events: none;
    }}
    .toast.show {{ opacity: 1; transform: translateY(0); }}
    @media (max-width: 980px) {{
      .shell {{ display: block; }} aside {{ position: relative; width: 100%; height: auto; padding: 18px; }}
      nav, .local {{ display: none; }} .brand {{ margin: 0; }} main {{ padding: 28px 18px 50px; }}
      .metrics {{ grid-template-columns: repeat(2, 1fr); }} .grid, .dual {{ grid-template-columns: 1fr; }}
      .reports {{ grid-template-columns: 1fr; }} header {{ display: block; }} .stamp {{ text-align: left; margin-top: 12px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand"><div class="logo">AI</div><div><strong>投研数字员工</strong><small>老板研究驾驶舱</small></div></div>
      <nav>
        <a href="#overview">今日总览</a>
        <a href="#profile">老板投资说明书</a>
        <a href="#watchlist">自选公司</a>
        <a href="#reports">研究档案</a>
        <a href="#memory">判断与纠正</a>
      </nav>
      <div class="local"><span class="dot"></span>本机运行<br>只读取当前工作区文件<br>网页本身不会修改数据</div>
    </aside>
    <main>
      <header id="overview">
        <div>
          <h1>老板，今天看什么？</h1>
          <div class="subtitle">让 Codex 负责研究，让工作区负责记忆，让驾驶舱负责看清全局。</div>
        </div>
        <div class="stamp">资料更新时间<br><b>{state["updated_at"]}</b></div>
      </header>

      <section class="metrics">
        <div class="metric gold"><small>重点市场</small><strong>{html.escape(str(state["primary_markets"]))}</strong></div>
        <div class="metric blue"><small>自选公司</small><strong>{state["watch_count"]}</strong></div>
        <div class="metric green"><small>研究报告</small><strong>{state["report_count"]}</strong></div>
        <div class="metric purple"><small>待确认记忆</small><strong>{state["pending_count"]}</strong></div>
      </section>

      <section class="grid">
        <article class="panel" id="profile">
          <h2 class="section">老板投资说明书 <span class="tag">长期记忆</span></h2>
          <div class="markdown">{render_markdown(str(state["profile"]))}</div>
        </article>
        <article class="panel">
          <h2 class="section">回到 Codex 继续工作 <span class="tag">点击复制</span></h2>
          {prompt_buttons}
        </article>
      </section>

      <section class="panel" id="watchlist" style="margin-bottom:18px">
        <h2 class="section">自选公司 <span class="tag">{state["watch_count"]} 家</span></h2>
        {render_table(str(state["watchlist"]))}
      </section>

      <section class="panel" id="reports" style="margin-bottom:18px">
        <h2 class="section">最新研究档案 <span class="tag">最近 8 份</span></h2>
        <div class="reports">{report_items}</div>
      </section>

      <section class="dual" id="memory">
        <article class="panel">
          <h2 class="section">历史判断变化 <span class="tag">可复盘</span></h2>
          <div class="markdown">{render_markdown(str(state["decisions"]))}</div>
        </article>
        <article class="panel">
          <h2 class="section">老板纠正与反馈 <span class="tag">持续校准</span></h2>
          <div class="markdown">{render_markdown(str(state["feedback"]))}</div>
        </article>
      </section>
    </main>
  </div>
  <div class="toast" id="toast">已复制，粘贴到 Codex 即可</div>
  <script>
    const toast = document.getElementById("toast");
    document.querySelectorAll("[data-copy]").forEach((button) => {{
      button.addEventListener("click", async () => {{
        await navigator.clipboard.writeText(button.dataset.copy);
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 1600);
      }});
    }});
  </script>
</body>
</html>"""

    def report_page(self, relative: str) -> str:
        candidate = (self.data_dir / relative).resolve()
        try:
            candidate.relative_to(self.data_dir)
        except ValueError:
            raise FileNotFoundError(relative)
        if candidate.suffix.lower() != ".md" or not candidate.is_file():
            raise FileNotFoundError(relative)
        content = read_text(candidate)
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(candidate.stem)}</title>
<style>
body{{margin:0;background:#071019;color:#eaf0f5;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}
main{{max-width:900px;margin:0 auto;padding:50px 24px 90px}}
a{{color:#e7bd63}} .back{{display:inline-block;margin-bottom:25px;text-decoration:none;color:#9fb0c1}}
.paper{{background:#0d1925;border:1px solid rgba(155,180,205,.18);border-radius:20px;padding:34px;line-height:1.85}}
h2{{font-size:28px}}h3{{margin-top:28px}}blockquote{{border-left:3px solid #d6a84f;margin:15px 0;padding:8px 15px;background:rgba(214,168,79,.06)}}
code{{background:#12263a;padding:2px 5px;border-radius:4px}}pre{{white-space:pre-wrap;background:#050b11;padding:15px;border-radius:12px}}
</style></head><body><main><a class="back" href="/">← 返回驾驶舱</a><article class="paper">{render_markdown(content)}</article></main></body></html>"""


def build_handler(dashboard: Dashboard):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/":
                    content = dashboard.page()
                elif parsed.path == "/report":
                    relative = parse_qs(parsed.query).get("path", [""])[0]
                    content = dashboard.report_page(relative)
                elif parsed.path == "/health":
                    payload = json.dumps({"ok": True, "data_dir": str(dashboard.data_dir)}, ensure_ascii=False)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload.encode("utf-8"))))
                    self.end_headers()
                    self.wfile.write(payload.encode("utf-8"))
                    return
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
            except FileNotFoundError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 AI 投研数字员工本地驾驶舱")
    parser.add_argument("--data-dir", required=True, help="投研数字员工数据目录")
    parser.add_argument("--port", type=int, default=8776)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--export", help="只导出静态首页 HTML，不启动服务器")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser().resolve()
    if not (data_dir / PROFILE_FILE).exists():
        raise SystemExit(f"没有找到投研工作区：{data_dir}")
    dashboard = Dashboard(data_dir)

    if args.export:
        output = Path(args.export).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dashboard.page(), encoding="utf-8")
        print(output)
        return

    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(dashboard))
    url = f"http://127.0.0.1:{args.port}"
    print(f"AI 投研数字员工驾驶舱：{url}")
    print("只监听本机。关闭此终端窗口即可停止。")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
