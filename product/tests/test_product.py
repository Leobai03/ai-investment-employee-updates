from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


TEST_DB = Path(f"/tmp/ai_research_product_test_{os.getpid()}.db")
TEST_WORKSPACE = Path(f"/tmp/ai_research_product_workspace_{os.getpid()}")
PRODUCT_ROOT = Path(__file__).resolve().parents[1]
for suffix in ("", "-shm", "-wal"):
    Path(f"{TEST_DB}{suffix}").unlink(missing_ok=True)

os.environ["AI_RESEARCH_DEMO"] = "1"
os.environ["AI_RESEARCH_DB"] = str(TEST_DB)
os.environ["AI_RESEARCH_WORKSPACE"] = str(TEST_WORKSPACE)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
import app.main as main_module  # noqa: E402
from app.codex_engine import CodexResearchClient  # noqa: E402
from app.config import codex_app_server_command  # noqa: E402
from app.codex_sync import CodexArchiveSync  # noqa: E402
from app.database import (  # noqa: E402
    claim_due_job,
    connection,
    create_conversation,
    finish_job_run,
    get_conversation,
    get_job,
    init_db,
    list_job_runs,
)
from app.memory import build_memory_context, memory_overview  # noqa: E402
from app.prompts import BASE_INSTRUCTIONS, company_prompt, daily_brief_prompt  # noqa: E402
from app.research import ResearchClient, ResearchResult, _replace_citations  # noqa: E402
from app.safety import (  # noqa: E402
    attach_explicit_table_sources,
    audit_investment_output,
    strip_research_preamble,
)
from app.source_quality import align_sources_with_content, assess_source, audit_sources  # noqa: E402


def test_health_and_default_profile() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["demo_mode"] is True
        assert health.json()["version"] == "0.11.0"
        assert "platform" in health.json()
        assert set(health.json()["engines"]) == {"default", "codex", "api", "demo"}
        profile = client.get("/api/profile").json()
        assert profile["primary_markets"] == ["A股", "港股"]
        assert profile["analysis_framework"].startswith("全球局势")
        assert "不读取微信和通讯录" in profile["privacy_boundaries"]
        assert profile["auto_brief_enabled"] is False
        launch = client.get("/api/codex/launch").json()
        assert launch["url"].startswith("codex://new?")
        assert "%24ai-investment-employee" in launch["url"]
        assert launch["workspace"]
        assert launch["platform"]
        memory = client.get("/api/memory/overview").json()
        assert "memory_files" in memory
        data_sources = client.get("/api/data-sources", params=[("markets", "A股"), ("markets", "港股")])
        assert data_sources.status_code == 200
        assert {"A股", "港股"} == {item["market"] for item in data_sources.json()["providers"]}
        assert all(item["quality"] == "一手来源" for item in data_sources.json()["providers"])
        safety = client.get("/api/safety-policy").json()
        assert safety["trading_permissions"] is False
        assert safety["output_gate"] is True
        jobs = client.get("/api/jobs").json()
        assert next(job for job in jobs if job["job_type"] == "daily_brief")["enabled"] is True
        updates = client.get("/api/updates/status")
        assert updates.status_code == 200
        assert updates.json()["current_version"] == "0.11.0"
        assert updates.json()["repository"]
        assert client.post("/api/updates/install").status_code == 403


def test_update_install_is_blocked_outside_windows(monkeypatch) -> None:
    import app.update_service as update_service

    monkeypatch.setattr(update_service.platform, "system", lambda: "Darwin")
    with TestClient(app) as client:
        unsupported = client.post(
            "/api/updates/install",
            headers={"X-AI-Research-Action": "install-update"},
        )
        assert unsupported.status_code == 409


def test_windows_codex_cmd_uses_comspec() -> None:
    command = codex_app_server_command(
        r"C:\Users\Boss Name\AppData\Roaming\npm\codex.cmd",
        platform_name="win32",
        comspec=r"C:\Windows\System32\cmd.exe",
    )
    assert command[:4] == [
        r"C:\Windows\System32\cmd.exe",
        "/d",
        "/s",
        "/c",
    ]
    assert '"C:\\Users\\Boss Name\\AppData\\Roaming\\npm\\codex.cmd"' in command[4]
    assert "app-server --listen stdio://" in command[4]


def test_native_codex_executable_is_launched_directly() -> None:
    command = codex_app_server_command(
        r"C:\Tools\codex.exe",
        platform_name="win32",
    )
    assert command == [r"C:\Tools\codex.exe", "app-server", "--listen", "stdio://"]


def test_windows_entrypoints_reference_existing_powershell_scripts() -> None:
    expected = {
        "Windows_首次配置.cmd": "scripts\\windows\\setup.ps1",
        "Windows_启动研究台.cmd": "scripts\\windows\\start.ps1",
        "Windows_停止研究台.cmd": "scripts\\windows\\stop.ps1",
        "Windows_查看运行日志.cmd": "scripts\\windows\\logs.ps1",
        "Windows_演示研究台.cmd": "scripts\\windows\\start.ps1",
        "Windows_安装开机自启.cmd": "scripts\\windows\\install-autostart.ps1",
        "Windows_卸载开机自启.cmd": "scripts\\windows\\uninstall-autostart.ps1",
        "Windows_系统自检.cmd": "scripts\\windows\\doctor.ps1",
    }
    for entrypoint, script in expected.items():
        content = (PRODUCT_ROOT / entrypoint).read_text(encoding="utf-8")
        assert script in content
        assert (PRODUCT_ROOT / Path(script.replace("\\", "/"))).exists()
        assert "-ExecutionPolicy Bypass" in content


def test_windows_scripts_keep_local_security_boundary() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PRODUCT_ROOT / "scripts" / "windows").glob("*.ps1"))
    )
    assert '--host", "127.0.0.1"' in combined
    assert "Invoke-Expression" not in combined
    assert "EncodedCommand" not in combined
    assert "Remove-Item -Recurse" not in combined
    assert "Start-ResearchDesk -NoBrowser" in combined


def test_database_backup_is_consistent_and_visible() -> None:
    with TestClient(app) as client:
        created = client.post("/api/backups")
        assert created.status_code == 201
        backup = created.json()
        backup_path = Path(backup["path"])
        assert backup_path.exists()
        assert backup_path.parent == TEST_WORKSPACE / "backups"

        with sqlite3.connect(backup_path) as conn:
            assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert conn.execute(
                "SELECT COUNT(*) FROM settings WHERE key='profile'"
            ).fetchone()[0] == 1

        listed = client.get("/api/backups")
        assert listed.status_code == 200
        assert listed.json()["retention"] == 14
        assert any(item["path"] == str(backup_path) for item in listed.json()["items"])


def test_profile_watchlist_and_reports_flow() -> None:
    with TestClient(app) as client:
        profile = client.get("/api/profile").json()
        profile["owner_name"] = "测试老板"
        profile["focus_sectors"] = ["科技", "消费"]
        saved = client.put("/api/profile", json=profile)
        assert saved.status_code == 200
        assert saved.json()["owner_name"] == "测试老板"

        created = client.post(
            "/api/watchlist",
            json={"symbol": "0700", "name": "腾讯控股", "market": "港股", "thesis": "现金流与生态", "notes": ""},
        )
        assert created.status_code == 201
        item_id = created.json()["id"]
        duplicate = client.post(
            "/api/watchlist",
            json={"symbol": "0700", "name": "腾讯控股", "market": "港股", "thesis": "", "notes": ""},
        )
        assert duplicate.status_code == 409

        daily = client.post("/api/research/daily", json={"question": "今日简报", "context": "重点看科技"})
        assert daily.status_code == 200
        assert daily.json()["report_type"] == "daily"
        assert daily.json()["engine"] == "demo"
        assert "演示模式" in daily.json()["content"]

        company = client.post(
            "/api/research/company",
            json={
                "company": "腾讯控股",
                "symbol": "0700",
                "market": "港股",
                "context": "研究现金流",
                "review_mode": "team",
            },
        )
        assert company.status_code == 200
        assert company.json()["report_type"] == "company"
        assert company.json()["review_mode"] == "team"

        qa = client.post(
            "/api/research/ask", json={"question": "什么信息可能影响我的自选股？", "context": ""}
        )
        assert qa.status_code == 200
        reports = client.get("/api/reports?limit=10").json()
        assert len(reports) >= 3

        removed = client.delete(f"/api/watchlist/{item_id}")
        assert removed.status_code == 200


def test_web_and_codex_share_markdown_memory() -> None:
    with TestClient(app) as client:
        profile = client.get("/api/profile").json()
        profile["owner_name"] = "网页老板"
        profile["focus_sectors"] = ["半导体", "消费"]
        saved = client.put("/api/profile", json=profile)
        assert saved.status_code == 200

        profile_file = TEST_WORKSPACE / "00_老板投资说明书.md"
        assert "- 称呼：网页老板" in profile_file.read_text(encoding="utf-8")
        assert "- 重点板块：半导体、消费" in profile_file.read_text(encoding="utf-8")

        profile_file.write_text(
            profile_file.read_text(encoding="utf-8").replace("网页老板", "Codex老板"),
            encoding="utf-8",
        )
        synced = client.get("/api/profile")
        assert synced.status_code == 200
        assert synced.json()["owner_name"] == "Codex老板"

        created = client.post(
            "/api/watchlist",
            json={
                "symbol": "600519",
                "name": "贵州茅台",
                "market": "A股",
                "thesis": "品牌与现金流",
                "notes": "",
            },
        )
        assert created.status_code == 201
        watchlist_file = TEST_WORKSPACE / "01_自选公司.md"
        assert "贵州茅台" in watchlist_file.read_text(encoding="utf-8")

        with watchlist_file.open("a", encoding="utf-8") as handle:
            handle.write("| 美团 | 3690 | 港股 | 2026-07-24 | 本地生活网络效应 | 跟踪中 |\n")
        synced_watchlist = client.get("/api/watchlist")
        assert synced_watchlist.status_code == 200
        assert any(item["symbol"] == "3690" for item in synced_watchlist.json())


def test_citation_annotation_becomes_clickable_markdown() -> None:
    text = "这是事实（来源）。"
    start = text.index("（")
    end = text.index("）") + 1
    converted, sources = _replace_citations(
        text,
        [{"type": "url_citation", "start_index": start, "end_index": end, "url": "https://example.com/a", "title": "官方公告"}],
    )
    assert "[〔来源：官方公告〕](https://example.com/a)" in converted
    assert sources[0]["url"] == "https://example.com/a"


def test_source_quality_is_conservative_and_auditable() -> None:
    hkex = assess_source(
        {
            "title": "上市公司公告",
            "url": "https://www1.hkexnews.hk/listedco/listconews/index/lci.html",
            "kind": "citation",
        }
    )
    repost = assess_source(
        {
            "title": "Reuters 官方公告转载",
            "url": "https://example.com/reuters-repost",
            "kind": "consulted",
        }
    )
    community = assess_source(
        {
            "title": "投资者讨论",
            "url": "https://xueqiu.com/123/456",
            "kind": "consulted",
        }
    )

    assert hkex["is_primary"] is True
    assert hkex["publisher"] == "港交所披露易"
    assert repost["is_primary"] is False
    assert repost["quality_label"] == "待核验"
    assert community["quality_label"] == "聚合/社区"

    audit = audit_sources([hkex, repost, community])
    assert audit["primary_count"] == 1
    assert audit["cited_count"] == 1
    assert audit["unique_domains"] == 3
    assert audit["coverage_level"] == "adequate"
    assert any("聚合或社区" in warning for warning in audit["warnings"])

    content_audit = audit_sources(
        [hkex, repost, community],
        "公司 2025 年收入为 100 亿元。\n"
        "利润率为 12%[〔来源：上市公司公告〕](https://www1.hkexnews.hk/a.pdf)。",
    )
    assert content_audit["numeric_claim_count"] == 2
    assert content_audit["cited_numeric_claim_count"] == 1
    assert content_audit["numeric_citation_ratio"] == 0.5
    assert any("数字事实" in warning for warning in content_audit["warnings"])

    aligned = align_sources_with_content(
        [
            {
                "title": "国家统计局检索结果",
                "url": "https://www.stats.gov.cn/example",
                "kind": "consulted",
            }
        ],
        "GDP 同比增长 5%。[国家统计局](https://www.stats.gov.cn/example)",
    )
    assert aligned[0]["citation_role"] == "正文引用"
    aligned_audit = audit_sources(aligned, "数据截至：2026年7月24日。\nGDP 同比增长 5%。[国家统计局](https://www.stats.gov.cn/example)")
    assert aligned_audit["cited_count"] == 1
    assert aligned_audit["numeric_claim_count"] == 1
    assert aligned_audit["numeric_citation_ratio"] == 1.0
    compact_chinese = audit_sources(
        aligned,
        "截至2026年一季度，自由现金流为人民币567亿元。"
        "[国家统计局](https://www.stats.gov.cn/example)",
    )
    assert compact_chinese["numeric_claim_count"] == 1
    assert compact_chinese["cited_numeric_claim_count"] == 1


def test_team_review_runs_two_independent_reviews_then_synthesis(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_research_result(
        prompt: str,
        depth: str = "balanced",
        *,
        engine: str = "auto",
        use_web: bool = True,
    ) -> ResearchResult:
        calls.append(prompt)
        if "主研究员" in prompt:
            return ResearchResult(
                content="最终报告[〔来源：SEC〕](https://www.sec.gov/final)",
                sources=[
                    {
                        "title": "SEC final",
                        "url": "https://www.sec.gov/final",
                        "kind": "citation",
                    }
                ],
                model="test-model",
                engine="api",
            )
        label = "核验" if "事实核验员" in prompt else "反方"
        return ResearchResult(
            content=f"{label}记录",
            sources=[
                {
                    "title": f"{label}来源",
                    "url": f"https://www.sec.gov/{label}",
                    "kind": "citation",
                }
            ],
            model="test-model",
            engine="api",
        )

    monkeypatch.setattr(main_module, "_research_result", fake_research_result)
    draft = ResearchResult(
        content="原始草稿",
        sources=[{"title": "草稿来源", "url": "https://www.sec.gov/draft", "kind": "citation"}],
        model="test-model",
        engine="api",
    )
    result = asyncio.run(
        main_module._team_review_result(
            draft,
            original_prompt="研究示例公司",
            engine="api",
            use_web=True,
        )
    )

    assert len(calls) == 3
    assert result.content.startswith("最终报告")
    final_source = next(item for item in result.sources if item["url"].endswith("/final"))
    draft_source = next(item for item in result.sources if item["url"].endswith("/draft"))
    assert final_source["citation_role"] == "正文引用"
    assert draft_source["citation_role"] == "检索参考"


def test_company_hypothesis_ledger_crud() -> None:
    with TestClient(app) as client:
        company = client.post(
            "/api/watchlist",
            json={
                "symbol": "1810-HYP",
                "name": "假设测试公司",
                "market": "港股",
                "thesis": "测试可证伪研究流程",
                "notes": "",
            },
        ).json()
        created = client.post(
            "/api/hypotheses",
            json={
                "watchlist_id": company["id"],
                "title": "新业务能形成稳定现金流",
                "statement": "未来三个年度自由现金流持续为正。",
                "status": "tracking",
                "support_evidence": ["经营现金流改善"],
                "counter_evidence": ["资本开支仍高"],
                "validation_signals": ["自由现金流转正"],
                "invalidation_signals": ["连续两年经营现金流恶化"],
                "next_review_at": "2026-08-31",
            },
        )
        assert created.status_code == 201
        hypothesis = created.json()
        assert hypothesis["support_evidence"] == ["经营现金流改善"]

        workspace = client.get(f"/api/watchlist/{company['id']}/workspace").json()
        assert workspace["hypotheses"][0]["id"] == hypothesis["id"]
        assert workspace["collection_plan"]["markets"] == ["港股"]
        assert workspace["collection_plan"]["providers"][0]["id"] == "hkexnews"

        updated = client.put(
            f"/api/hypotheses/{hypothesis['id']}",
            json={
                "title": hypothesis["title"],
                "statement": hypothesis["statement"],
                "status": "challenged",
                "support_evidence": hypothesis["support_evidence"],
                "counter_evidence": ["资本开支仍高", "毛利率下滑"],
                "validation_signals": hypothesis["validation_signals"],
                "invalidation_signals": hypothesis["invalidation_signals"],
                "next_review_at": "2026-09-30",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "challenged"
        assert "毛利率下滑" in updated.json()["counter_evidence"]
        memory_context = build_memory_context("假设测试公司现金流")
        assert "新业务能形成稳定现金流" in memory_context
        assert "假设不是事实" in memory_context

        removed = client.delete(f"/api/hypotheses/{hypothesis['id']}")
        assert removed.status_code == 200
        assert client.get(
            "/api/hypotheses",
            params={"watchlist_id": company["id"]},
        ).json() == []


def test_prompt_keeps_research_and_trading_boundary() -> None:
    assert "不给出“买入、卖出" in BASE_INSTRUCTIONS
    prompt = company_prompt(
        {"primary_markets": ["A股", "港股"]},
        [],
        "示例公司",
        "000001",
        "A股",
        "",
    )
    assert "三个反对理由或风险" in prompt
    assert "不得给出交易指令或目标价" in prompt
    framework_prompt = daily_brief_prompt(
        {"reference_investors": ["段永平公开方法"]},
        [],
    )
    assert "不代表该投资人本人对当前事件的真实看法" in framework_prompt
    assert "浙江大学" in framework_prompt


def test_output_gate_red_team_cases() -> None:
    unsafe_cases = [
        "建议买入腾讯。",
        "应该分批卖出这家公司。",
        "现在可以考虑加仓。",
        "股价跌到 300 港元就买入。",
        "突破 50 元后加仓。",
        "目标价为 88 港元。",
        "止损价设在 10 元。",
        "建议买入价：25.5 元。",
        "仓位控制在 30%。",
        "该策略保证获得收益。",
        "这笔投资稳赚。",
        "公司股价一定上涨。",
    ]
    safe_cases = [
        "本报告不建议买入或卖出任何证券。",
        "需要验证自由现金流是否改善。",
        "公司创始人持仓比例为 20%。",
        "某机构曾下调其目标价，但本报告不采用该结论。",
        "若需求走弱，收入增速可能承压。",
        "反方证据是资本开支继续上升。",
        "尚缺少最新年度报告，不能把推测写成事实。",
        "公司正在执行股份回购计划。",
        "应关注交易所后续公告。",
        "本报告只整理公开信息，不构成投资建议。",
        "ROIC 的口径需要和公司年报核对。",
        "估值变化是观察项，不是交易指令。",
    ]

    assert len(unsafe_cases) + len(safe_cases) >= 20
    for case in unsafe_cases:
        audit = audit_investment_output(case)
        assert audit["compliant"] is False, case
    for case in safe_cases:
        audit = audit_investment_output(case)
        assert audit["compliant"] is True, case

    cleaned = strip_research_preamble(
        "我会使用投研 Skill，先联网检索并核对来源。\n\n# 今日结论\n\n没有未核实数字。"
    )
    assert cleaned.startswith("# 今日结论")

    table = attach_explicit_table_sources(
        "分部数据如下：[公司公告](https://example.com/filing.pdf)\n\n"
        "| 业务 | 收入 |\n|---|---:|\n| 云服务 | 100亿元 |"
    )
    assert "| 云服务 | 100亿元 [表格来源](https://example.com/filing.pdf) |" in table


def test_output_gate_rewrites_before_archiving(monkeypatch) -> None:
    async def fake_rewrite(
        prompt: str,
        depth: str = "balanced",
        *,
        engine: str = "auto",
        use_web: bool = True,
    ) -> ResearchResult:
        assert "严格的“公开信息研究与汇报”" in prompt
        assert use_web is False
        return ResearchResult(
            content="事实：公司现金流改善。反方证据：需求仍可能走弱。",
            sources=[],
            model="rewrite-model",
            engine="api",
        )

    monkeypatch.setattr(main_module, "_research_result", fake_rewrite)
    original = ResearchResult(
        content="建议买入示例公司。",
        sources=[
            {
                "title": "公司公告",
                "url": "https://www.sec.gov/example",
                "kind": "citation",
            }
        ],
        model="draft-model",
        engine="api",
    )
    rewritten = asyncio.run(
        main_module._enforce_output_boundary(original, engine="api")
    )
    assert audit_investment_output(rewritten.content)["compliant"] is True
    assert rewritten.sources[0]["url"] == "https://www.sec.gov/example"


def test_openai_research_contract_and_source_parsing() -> None:
    class FakeResponse:
        output_text = ""

        def model_dump(self, mode: str = "json") -> dict:
            assert mode == "json"
            return {
                "model": "gpt-5.6-terra",
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {
                            "type": "search",
                            "sources": [{"type": "url", "title": "交易所公告", "url": "https://example.com/exchange"}],
                        },
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "已核实事实〔1〕",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "start_index": 5,
                                        "end_index": 8,
                                        "title": "公司公告",
                                        "url": "https://example.com/company",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }

    class FakeResponses:
        def __init__(self) -> None:
            self.kwargs = None

        async def create(self, **kwargs):
            self.kwargs = kwargs
            return FakeResponse()

    class FakeOpenAI:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    import asyncio

    fake = FakeOpenAI()
    client = ResearchClient(client=fake, api_key="sk-test", model="gpt-5.6-terra", demo_mode=False)
    result = asyncio.run(client.run("研究纪律", "生成报告", depth="deep"))

    assert fake.responses.kwargs["tools"] == [{"type": "web_search", "search_context_size": "high"}]
    assert fake.responses.kwargs["include"] == ["web_search_call.action.sources"]
    assert fake.responses.kwargs["reasoning"] == {"effort": "medium"}
    assert "[〔来源：公司公告〕](https://example.com/company)" in result.content
    assert {source["url"] for source in result.sources} == {
        "https://example.com/company",
        "https://example.com/exchange",
    }
    assert fake.responses.kwargs["store"] is False
    assert result.engine == "api"


def test_codex_subscription_engine_contract() -> None:
    import asyncio

    fake_server = Path(__file__).with_name("fake_codex_app_server.py")
    client = CodexResearchClient(
        command=[sys.executable, str(fake_server)],
        cwd=TEST_WORKSPACE,
        timeout_seconds=5,
    )

    status = asyncio.run(client.status(force=True))
    assert status.available is True
    assert status.logged_in is True
    assert status.auth_type == "chatgpt"
    assert status.plan_type == "plus"

    result = asyncio.run(
        client.run(
            "只做公开信息研究。",
            "测试 Codex 订阅引擎",
            depth="balanced",
            use_web=True,
        )
    )
    assert result.engine == "codex"
    assert result.model == "gpt-codex-test"
    assert result.sources[0]["url"] == "https://example.com/source"

    threads = asyncio.run(client.read_workspace_threads(TEST_WORKSPACE))
    assert len(threads) == 1
    assert threads[0]["cwd"] == str(TEST_WORKSPACE.resolve())
    assert threads[0]["turns"][0]["items"][0]["type"] == "userMessage"


def test_codex_archive_sync_and_layered_memory() -> None:
    import asyncio

    init_db()
    fake_server = Path(__file__).with_name("fake_codex_app_server.py")
    codex = CodexResearchClient(
        command=[sys.executable, str(fake_server)],
        cwd=TEST_WORKSPACE,
        timeout_seconds=5,
    )
    archive = CodexArchiveSync(codex, workspace=TEST_WORKSPACE)
    first = asyncio.run(archive.sync())
    second = asyncio.run(archive.sync())

    assert first["last_threads"] == 1
    assert first["last_imported"] == 2
    assert second["last_imported"] == 0
    conversation = get_conversation("codex-thread-archive-test")
    assert conversation is not None
    assert [item["role"] for item in conversation["messages"]] == ["user", "assistant"]
    assert conversation["messages"][1]["sources"][0]["url"] == "https://example.com/tencent"

    context = build_memory_context("腾讯现金流")
    assert "长期关注腾讯现金流" in context
    overview = memory_overview()
    assert overview["by_source"]["codex"] >= 1
    assert overview["messages"] >= 2


def test_conversation_is_persisted_and_searchable() -> None:
    with TestClient(app) as client:
        created = client.post("/api/conversations", json={"title": "新对话"})
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        replied = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请研究腾讯的现金流", "use_web": True},
        )
        assert replied.status_code == 200
        conversation = replied.json()["conversation"]
        assert [item["role"] for item in conversation["messages"]] == ["user", "assistant"]
        assert "演示模式" in conversation["messages"][1]["content"]

        searched = client.get("/api/conversations", params={"query": "腾讯"})
        assert searched.status_code == 200
        assert any(item["id"] == conversation_id for item in searched.json())


def test_scheduled_job_configuration_and_manual_run() -> None:
    with TestClient(app) as client:
        jobs = client.get("/api/jobs").json()
        assert len(jobs) == 3
        job = jobs[0]
        updated = client.put(
            f"/api/jobs/{job['id']}",
            json={
                "name": job["name"],
                "frequency": "interval",
                "interval_minutes": 60,
                "time_of_day": "08:00",
                "weekday": 0,
                "active_start": "07:00",
                "active_end": "23:00",
                "enabled": True,
                "engine": "auto",
                "prompt": "只扫描新增重要消息",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is True

        run = client.post(f"/api/jobs/{job['id']}/run")
        assert run.status_code == 200
        assert run.json()["report_type"] == "hourly"
        conversations = client.get("/api/conversations", params={"source": "scheduler"}).json()
        assert conversations


def test_scheduler_claims_once_recovers_interruption_and_keeps_manual_plan() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/jobs",
            json={
                "name": "可靠性测试晨报",
                "job_type": "daily_brief",
                "frequency": "daily",
                "interval_minutes": 1440,
                "time_of_day": "08:00",
                "weekday": -1,
                "active_start": "00:00",
                "active_end": "23:59",
                "enabled": False,
                "engine": "auto",
                "frameworks": [],
                "prompt": "测试正式调度防重与恢复",
            },
        ).json()
        job_id = created["id"]
        fixed_now = datetime.now().astimezone().replace(microsecond=0)
        scheduled_for = (fixed_now - timedelta(minutes=5)).isoformat(timespec="seconds")
        with connection() as conn:
            conn.execute(
                "UPDATE scheduled_jobs SET enabled=1, next_run_at=? WHERE id=?",
                (scheduled_for, job_id),
            )

        first_run_id = claim_due_job(job_id, fixed_now)
        assert first_run_id is not None
        next_after_claim = get_job(job_id)["next_run_at"]
        assert next_after_claim > fixed_now.isoformat(timespec="seconds")

        init_db()
        recovered_job = get_job(job_id)
        assert recovered_job["next_run_at"] == scheduled_for
        interrupted = list_job_runs(job_id)[0]
        assert interrupted["status"] == "interrupted"

        recovered_run_id = claim_due_job(job_id, fixed_now)
        assert recovered_run_id == first_run_id
        assert claim_due_job(job_id, fixed_now) is None
        recovered = list_job_runs(job_id)[0]
        assert recovered["attempt_count"] == 2
        finish_job_run(recovered_run_id, status="completed")

        plan_before_manual = get_job(job_id)["next_run_at"]
        manual = client.post(f"/api/jobs/{job_id}/run")
        assert manual.status_code == 200
        assert get_job(job_id)["next_run_at"] == plan_before_manual

        runs = client.get(f"/api/jobs/{job_id}/runs").json()
        assert runs[0]["trigger_type"] == "manual"
        assert runs[1]["trigger_type"] == "scheduled"
        assert runs[1]["attempt_count"] == 2


def test_background_research_and_custom_job_crud() -> None:
    with TestClient(app) as client:
        queued = client.post(
            "/api/background-research/daily",
            json={"question": "生成今日简报", "context": "后台测试", "engine": "auto"},
        )
        assert queued.status_code == 202
        task_id = queued.json()["id"]
        task = {}
        for _ in range(20):
            task = client.get(f"/api/background-research/{task_id}").json()
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert task["status"] == "completed"
        assert task["report_id"]

        created = client.post(
            "/api/jobs",
            json={
                "name": "每天收盘复盘",
                "job_type": "weekly_review",
                "frequency": "daily",
                "interval_minutes": 1440,
                "time_of_day": "17:00",
                "weekday": -1,
                "active_start": "00:00",
                "active_end": "23:59",
                "enabled": False,
                "engine": "auto",
                "frameworks": ["段永平公开方法"],
                "prompt": "复盘当天基本面变化",
            },
        )
        assert created.status_code == 201
        assert created.json()["weekday"] == -1
        assert created.json()["frameworks"] == ["段永平公开方法"]
        deleted = client.delete(f"/api/jobs/{created.json()['id']}")
        assert deleted.status_code == 200


def test_company_workspace_tracking_and_export_flow() -> None:
    with TestClient(app) as client:
        queued = client.post(
            "/api/background-research/company",
            json={
                "company": "小米集团",
                "symbol": "1810",
                "market": "港股",
                "context": "跟踪汽车和手机业务",
                "engine": "auto",
            },
        )
        assert queued.status_code == 202
        watchlist_id = queued.json()["request"]["watchlist_id"]
        task_id = queued.json()["id"]
        task = {}
        for _ in range(30):
            task = client.get(f"/api/background-research/{task_id}").json()
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert task["status"] == "completed"

        workspace = client.get(f"/api/watchlist/{watchlist_id}/workspace")
        assert workspace.status_code == 200
        assert workspace.json()["company"]["name"] == "小米集团"
        assert workspace.json()["reports"][0]["watchlist_id"] == watchlist_id

        tracking = client.put(
            f"/api/watchlist/{watchlist_id}/tracking",
            json={
                "enabled": True,
                "frequency": "monthly",
                "time_of_day": "09:30",
                "weekday": 0,
                "day_of_month": 8,
                "month_of_year": 1,
                "engine": "auto",
                "frameworks": ["段永平公开方法"],
            },
        )
        assert tracking.status_code == 200
        assert tracking.json()["company"]["tracking_enabled"] is True
        assert tracking.json()["tracking_job"]["frequency"] == "monthly"
        assert tracking.json()["tracking_job"]["watchlist_id"] == watchlist_id

        report_id = workspace.json()["reports"][0]["id"]
        for file_format in ("md", "docx", "pdf"):
            downloaded = client.get(
                f"/api/reports/{report_id}/download",
                params={"format": file_format},
            )
            assert downloaded.status_code == 200
            assert len(downloaded.content) > 30

        deleted = client.delete(f"/api/reports/{report_id}")
        assert deleted.status_code == 200
        assert client.get(f"/api/reports/{report_id}").status_code == 404


def test_background_conversation_keeps_same_window_and_exports() -> None:
    with TestClient(app) as client:
        external = create_conversation("外部同步对话", source="codex", conversation_id="codex-local-test")
        queued = client.post(
            f"/api/conversations/{external['id']}/messages/enqueue",
            json={"content": "继续研究同一个问题", "use_web": True, "engine": "auto"},
        )
        assert queued.status_code == 202
        task_id = queued.json()["id"]
        task = {}
        for _ in range(30):
            task = client.get(f"/api/background-research/{task_id}").json()
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert task["status"] == "completed"
        conversation = client.get(f"/api/conversations/{external['id']}").json()
        assert conversation["source"] == "codex"
        assert [message["role"] for message in conversation["messages"]] == ["user", "assistant"]
        assert not any(
            item["title"] == "继续研究同一个问题" and item["id"] != external["id"]
            for item in client.get("/api/conversations").json()
        )

        markdown_files = list((TEST_WORKSPACE / "conversations").glob(f"{external['id']}_*.md"))
        assert markdown_files
        downloaded = client.get(
            f"/api/conversations/{external['id']}/download",
            params={"format": "docx"},
        )
        assert downloaded.status_code == 200
        assert len(downloaded.content) > 30
