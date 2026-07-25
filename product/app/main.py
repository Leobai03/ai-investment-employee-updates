from __future__ import annotations

import asyncio
import contextlib
import platform
import secrets
import socket
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .codex_engine import CodexUnavailable
from .codex_sync import CodexArchiveSync
from .config import (
    APP_PORT,
    DEMO_MODE,
    LAN_ACCESS_TOKEN,
    OPENAI_MODEL,
    PRODUCT_DIR,
    STATIC_DIR,
    ensure_runtime_dirs,
)
from .data_sources import build_collection_plan
from .database import (
    add_message,
    add_watchlist,
    attach_job_run_conversation,
    claim_due_job,
    conversation_has_active_task,
    create_conversation,
    create_database_backup,
    create_job,
    create_job_run,
    create_research_task,
    create_hypothesis,
    delete_hypothesis,
    delete_conversation,
    delete_job,
    delete_report,
    delete_watchlist,
    finish_job_run,
    finish_research_task,
    get_conversation,
    get_company_tracking_job,
    get_company_workspace,
    get_job,
    get_hypothesis,
    get_profile,
    get_research_task,
    get_report,
    get_or_add_watchlist,
    get_watchlist,
    init_db,
    increment_job_run_attempt,
    list_conversations,
    list_database_backups,
    list_due_jobs,
    list_jobs,
    list_hypotheses,
    list_job_runs,
    list_research_tasks,
    list_reports,
    list_watchlist,
    save_job,
    save_profile,
    save_report,
    start_research_task,
    sync_memory_files_to_db,
    update_watchlist_tracking,
    update_hypothesis,
)
from .exporter import export_conversation, export_report
from .frameworks import list_frameworks
from .memory import build_memory_context, memory_overview
from .prompts import (
    BASE_INSTRUCTIONS,
    company_prompt,
    conversation_instructions,
    daily_brief_prompt,
    hourly_news_prompt,
    qa_prompt,
    weekly_review_prompt,
)
from .engine import DualResearchClient
from .research import ResearchClient, ResearchResult, ResearchUnavailable
from .safety import (
    OutputSafetyError,
    attach_explicit_table_sources,
    audit_investment_output,
    safety_policy_overview,
    strip_research_preamble,
)
from .schemas import (
    CompanyResearchRequest,
    CompanyTrackingUpdate,
    ConversationCreate,
    ConversationMessageCreate,
    HypothesisCreate,
    HypothesisUpdate,
    Profile,
    ResearchRequest,
    ScheduledJobCreate,
    ScheduledJobUpdate,
    WatchlistCreate,
)
from .source_quality import enrich_sources, source_policy_overview
from .update_service import (
    UpdateServiceError,
    automatic_update_loop,
    check_latest,
    is_update_command,
    launch_updater,
    should_run_automatic_loop,
    update_status,
)


api_research_client = ResearchClient()
research_client = DualResearchClient(api_client=api_research_client)
codex_archive = CodexArchiveSync(research_client.codex, workspace=PRODUCT_DIR)
running_jobs: set[int] = set()
background_tasks: set[asyncio.Task] = set()
running_research_tasks: dict[str, asyncio.Task] = {}
conversation_locks: dict[str, asyncio.Lock] = {}
backup_state: dict[str, str] = {"last_success_at": "", "last_error": ""}
scheduler_state: dict[str, str | bool] = {
    "running": False,
    "last_checked_at": "",
    "last_error": "",
}
APP_VERSION = "0.11.3"


def _friendly_error(exc: Exception) -> str:
    message = str(exc)
    if "api_key" in message.lower() or "authentication" in message.lower():
        return "API Key 无效或没有权限，请重新运行首次配置。"
    return message[:500]


async def _research_result(
    prompt: str,
    depth: str = "balanced",
    *,
    engine: str = "auto",
    use_web: bool = True,
):
    try:
        return await research_client.run(
            BASE_INSTRUCTIONS,
            prompt,
            depth=depth,
            engine=engine,
            use_web=use_web,
        )
    except (ResearchUnavailable, CodexUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"研究生成失败：{_friendly_error(exc)}") from exc


async def _run_research(
    report_type: str,
    title: str,
    query: str,
    prompt: str,
    depth: str,
    *,
    conversation_id: str | None = None,
    job_run_id: int | None = None,
    source: str = "web",
    engine: str = "auto",
    use_web: bool = True,
    watchlist_id: int | None = None,
    review_mode: str = "single",
):
    draft_depth = "balanced" if review_mode == "team" else depth
    result = await _research_result(prompt, draft_depth, engine=engine, use_web=use_web)
    if review_mode == "team" and result.engine != "demo":
        result = await _team_review_result(
            result,
            original_prompt=prompt,
            engine=engine,
            use_web=use_web,
        )
    result = await _enforce_output_boundary(result, engine=engine)
    return save_report(
        report_type,
        title,
        query,
        result.content,
        result.sources,
        result.model,
        result.engine,
        conversation_id=conversation_id,
        job_run_id=job_run_id,
        source=source,
        watchlist_id=watchlist_id,
        review_mode=review_mode,
    )


async def _enforce_output_boundary(
    result: ResearchResult,
    *,
    engine: str,
) -> ResearchResult:
    cleaned_content = attach_explicit_table_sources(
        strip_research_preamble(result.content)
    )
    if cleaned_content != result.content:
        result = ResearchResult(
            content=cleaned_content,
            sources=result.sources,
            model=result.model,
            engine=result.engine,
        )
    first_audit = audit_investment_output(result.content)
    if first_audit["compliant"]:
        return result

    labels = "、".join(
        item["label"] for item in first_audit["violations"]
    )
    rewrite_prompt = f"""
请把下面研究草稿改写为严格的“公开信息研究与汇报”，保留有用的事实、来源链接、反方证据和验证信号。

必须删除或改写：
- 具体买入、卖出、加仓、减仓、建仓、清仓或持有指令；
- 任何仓位比例、目标价、止盈价、止损价；
- 保证收益、稳赚或确定性涨跌承诺。

可以保留：
- 有来源的事实和数字；
- 条件化影响分析；
- 反方证据、风险、缺失信息和后续验证信号。

不得解释内部安全检查，也不得冒充任何投资人。检测到的边界类型：{labels}

待改写草稿：
{result.content[:18000]}
""".strip()
    try:
        rewritten = await _research_result(
            rewrite_prompt,
            "balanced",
            engine=engine,
            use_web=False,
        )
    except Exception as exc:
        raise OutputSafetyError(
            "本次生成触发交易指令边界，安全改写未完成，因此没有归档或展示该草稿。"
        ) from exc

    second_audit = audit_investment_output(rewritten.content)
    if not second_audit["compliant"]:
        raise OutputSafetyError(
            "本次生成在安全改写后仍包含交易指令、仓位、目标价或收益承诺，已阻止归档。"
        )
    return ResearchResult(
        content=rewritten.content,
        sources=enrich_sources(result.sources),
        model=rewritten.model,
        engine=rewritten.engine,
    )


async def _team_review_result(
    draft: ResearchResult,
    *,
    original_prompt: str,
    engine: str,
    use_web: bool,
) -> ResearchResult:
    bounded_draft = draft.content[:14000]
    verifier_prompt = f"""
你是独立的事实核验员，不是投资决策者。请联网逐条检查下面研究草稿中最关键的事实和数字。

要求：
- 优先监管、交易所、公司原始公告/财报、央行和统计机构。
- 对每项写“已证实 / 有冲突 / 未核实”，并给紧邻事实的可点击来源。
- 数字必须核对币种、期间、合并口径、单位和原始文件位置。
- 不评价是否值得买卖，不给目标价。

原始任务：
{original_prompt[-6000:]}

待核验草稿：
{bounded_draft}
""".strip()
    counter_prompt = f"""
你是独立的反方研究员，不是做空者，也不提供交易建议。请联网寻找可能推翻下面草稿结论的公开证据。

要求：
- 优先原始披露，区分事实、合理反方解释和仍缺失的信息。
- 检查竞争、监管、需求、资本配置、现金流、负债、会计口径和管理层执行。
- 给出哪些信号会使原判断失效；没有可靠反证时明确说没有找到。
- 每个关键事实紧跟可点击来源，不给买卖、仓位或目标价。

待挑战草稿：
{bounded_draft}
""".strip()
    reviewed = await asyncio.gather(
        _research_result(verifier_prompt, "balanced", engine=engine, use_web=use_web),
        _research_result(counter_prompt, "balanced", engine=engine, use_web=use_web),
        return_exceptions=True,
    )
    verifier = reviewed[0] if isinstance(reviewed[0], ResearchResult) else None
    counter = reviewed[1] if isinstance(reviewed[1], ResearchResult) else None
    if verifier is None and counter is None:
        return draft

    synthesis_prompt = f"""
你是主研究员。根据原草稿和独立复核，重写一份可直接交付老板的最终报告。

硬要求：
- 保留原任务要求的章节结构。
- 事实核验员指出冲突或未核实时，必须纠正或降级为“未核实”。
- 纳入最重要的反方证据和失效信号，不把反方意见写成已证实事实。
- 对当前事实和数字重新联网确认；关键事实必须有同一行可点击引用。
- Markdown 表格中每一条含数字的数据行也必须在同一行保留来源链接。
- 标明币种、期间、口径和资料截至时间。
- 不提内部工作流，不冒充投资名人，不给买卖、加减仓、仓位或目标价。

原草稿：
{bounded_draft}

事实核验员记录：
{verifier.content[:8000] if verifier else '本轮事实核验员未成功返回，必须明确保留该缺口。'}

反方研究员记录：
{counter.content[:8000] if counter else '本轮反方研究员未成功返回，必须明确保留该缺口。'}
""".strip()
    try:
        final = await _research_result(
            synthesis_prompt,
            "balanced",
            engine=engine,
            use_web=use_web,
        )
    except Exception:
        appendix = (
            f"{draft.content.rstrip()}\n\n# 独立复核附录\n\n"
            f"## 事实核验员\n\n"
            f"{verifier.content.strip() if verifier else '本轮未成功返回，数字与来源核验仍是缺失信息。'}\n\n"
            f"## 反方研究员\n\n"
            f"{counter.content.strip() if counter else '本轮未成功返回，反方核验仍是缺失信息。'}"
        )
        return ResearchResult(
            content=appendix,
            sources=enrich_sources(
                [
                    *draft.sources,
                    *(verifier.sources if verifier else []),
                    *(counter.sources if counter else []),
                ]
            ),
            model=draft.model,
            engine=draft.engine,
        )

    consulted = [
        {**source, "kind": "consulted"}
        for source in [
            *draft.sources,
            *(verifier.sources if verifier else []),
            *(counter.sources if counter else []),
        ]
    ]
    return ResearchResult(
        content=final.content,
        sources=enrich_sources([*final.sources, *consulted]),
        model=final.model,
        engine=final.engine,
    )


def _with_memory(prompt: str, query: str) -> str:
    return (
        f"{prompt}\n\n# 老板长期记忆与相关历史\n"
        f"{build_memory_context(query)}"
    )


def _job_prompt(job: dict, profile: dict, watchlist: list[dict]) -> tuple[str, str, str]:
    now = datetime.now().astimezone()
    if job["job_type"] == "company_tracking":
        company = get_watchlist(int(job.get("watchlist_id") or 0))
        if not company:
            raise ValueError("关联的自选公司已经不存在。")
        frequency_name = {
            "daily": "每日",
            "weekly": "每周",
            "monthly": "每月",
            "yearly": "每年",
        }.get(job.get("frequency"), "定期")
        context = (
            f"{job['prompt']}\n"
            "重点比较上一次公司研究之后的新变化，只写新增事实、影响、反方证据和待核验信号。"
        )
        return (
            "company",
            f"{company['name']} · {frequency_name}公司跟踪",
            company_prompt(
                profile,
                watchlist,
                company["name"],
                company["symbol"],
                company["market"],
                context,
                job.get("frameworks"),
            ),
        )
    if job["job_type"] == "hourly_news":
        return (
            "hourly",
            f"{now:%Y-%m-%d %H:%M} 消息面扫描",
            hourly_news_prompt(profile, watchlist, job["prompt"], job.get("frameworks")),
        )
    if job["job_type"] == "weekly_review":
        return (
            "weekly",
            f"{now:%Y-%m-%d} 每周基本面复盘",
            weekly_review_prompt(profile, watchlist, job["prompt"], job.get("frameworks")),
        )
    return (
        "daily",
        f"{now:%Y-%m-%d} 每日市场晨报",
        daily_brief_prompt(profile, watchlist, job["prompt"], job.get("frameworks")),
    )


async def _execute_job(job_id: int, *, scheduled: bool = False) -> dict | None:
    if job_id in running_jobs:
        return None
    job = get_job(job_id)
    if not job:
        return None
    running_jobs.add(job_id)
    run_id: int | None = None
    conversation: dict | None = None
    try:
        if scheduled:
            run_id = claim_due_job(job_id)
            if run_id is None:
                return None
        conversation = create_conversation(
            f"{job['name']} · {datetime.now().astimezone():%Y-%m-%d %H:%M}",
            source="scheduler",
            watchlist_id=job.get("watchlist_id"),
        )
        if run_id is None:
            run_id = create_job_run(job_id, conversation["id"], trigger_type="manual")
        else:
            attach_job_run_conversation(run_id, conversation["id"])
        sync_memory_files_to_db()
        profile = get_profile()
        watchlist = list_watchlist()
        report_type, title, prompt = _job_prompt(job, profile, watchlist)
        prompt = _with_memory(prompt, f"{job['name']} {job['prompt']}")
        add_message(
            conversation["id"],
            "user",
            f"定时任务：{job['name']}\n\n{job['prompt']}",
            metadata={
                "job_id": job_id,
                "job_run_id": run_id,
                "engine": job.get("engine", "auto"),
            },
        )
        max_attempts = 2 if scheduled else 1
        attempt = 1
        while True:
            try:
                report = await _run_research(
                    report_type,
                    title,
                    job["prompt"],
                    prompt,
                    "balanced",
                    conversation_id=conversation["id"],
                    job_run_id=run_id,
                    source="scheduler",
                    engine=job.get("engine", "auto"),
                    watchlist_id=job.get("watchlist_id"),
                )
                break
            except Exception:
                if attempt >= max_attempts:
                    raise
                attempt += 1
                increment_job_run_attempt(run_id)
                await asyncio.sleep(0 if DEMO_MODE else 30)
        add_message(
            conversation["id"],
            "assistant",
            report["content"],
            sources=report["sources"],
            model=report["model"],
            metadata={
                "report_id": report["id"],
                "job_id": job_id,
                "job_run_id": run_id,
                "engine": report.get("engine", "api"),
            },
        )
        finish_job_run(run_id, status="completed", report_id=report["id"])
        return report
    except Exception as exc:
        message = _friendly_error(exc)
        if run_id is not None:
            finish_job_run(run_id, status="failed", error=message)
        if conversation:
            delete_conversation(conversation["id"])
        return None
    finally:
        running_jobs.discard(job_id)


async def _scheduler() -> None:
    scheduler_state["running"] = True
    try:
        while True:
            try:
                due_jobs = list_due_jobs()
                scheduler_state["last_checked_at"] = (
                    datetime.now().astimezone().isoformat(timespec="seconds")
                )
                scheduler_state["last_error"] = ""
                for job in due_jobs:
                    if job["id"] in running_jobs:
                        continue
                    task = asyncio.create_task(_execute_job(job["id"], scheduled=True))
                    background_tasks.add(task)
                    task.add_done_callback(background_tasks.discard)
            except Exception as exc:
                scheduler_state["last_error"] = _friendly_error(exc)
            await asyncio.sleep(15)
    finally:
        scheduler_state["running"] = False


def _track_background(coro, *, task_id: str | None = None) -> None:
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    if task_id:
        running_research_tasks[task_id] = task

    def _cleanup(completed: asyncio.Task) -> None:
        background_tasks.discard(completed)
        if task_id and running_research_tasks.get(task_id) is completed:
            running_research_tasks.pop(task_id, None)

    task.add_done_callback(_cleanup)


async def _conversation_reply(
    conversation_id: str,
    *,
    content: str,
    use_web: bool,
    engine: str,
    add_user: bool,
) -> dict:
    conversation = get_conversation(conversation_id)
    if not conversation:
        raise ValueError("对话不存在。")
    if add_user:
        add_message(
            conversation_id,
            "user",
            content,
            metadata={"engine": engine, "use_web": use_web},
        )
    if is_update_command(content):
        status = await asyncio.to_thread(check_latest)
        if status.get("state") == "error":
            message = str(status.get("message") or "更新检查失败，请稍后重试。")
        elif not status.get("supported"):
            message = (
                "已经检查版本，但一句话覆盖安装只在 Windows 正式交付版启用。"
                "当前电脑不会修改任何文件。"
            )
        elif not status.get("update_available"):
            message = (
                f"当前 v{status.get('current_version', APP_VERSION)} 已经是最新版，"
                "不需要重复安装。"
            )
        else:
            latest = str(status.get("latest_version") or "").strip()
            message = (
                f"已确认更新到 v{latest}。安全更新器已经启动；"
                "它会先备份老板资料，网页可能短暂断开，完成后自动恢复。"
            )
        assistant = add_message(
            conversation_id,
            "assistant",
            message,
            metadata={"update_action": True},
        )
        if status.get("supported") and status.get("update_available"):
            try:
                await asyncio.to_thread(launch_updater)
            except UpdateServiceError as exc:
                assistant = add_message(
                    conversation_id,
                    "assistant",
                    f"更新程序未能启动：{exc}",
                    metadata={"update_action": True, "error": True},
                )
        return {"conversation": get_conversation(conversation_id), "message": assistant}
    conversation = get_conversation(conversation_id)
    history = [
        {"role": item["role"], "content": item["content"]}
        for item in conversation["messages"]
        if item["role"] in {"user", "assistant"} and not item["metadata"].get("error")
    ]
    sync_memory_files_to_db()
    result = await research_client.chat(
        conversation_instructions(get_profile(), list_watchlist())
        + "\n\n# 老板长期记忆与相关历史\n"
        + build_memory_context(content),
        history,
        engine=engine,
        use_web=use_web,
    )
    result = await _enforce_output_boundary(result, engine=engine)
    assistant = add_message(
        conversation_id,
        "assistant",
        result.content,
        sources=result.sources,
        model=result.model,
        metadata={"engine": result.engine, "use_web": use_web},
    )
    return {"conversation": get_conversation(conversation_id), "message": assistant}


async def _execute_research_task(task_id: str) -> None:
    task = get_research_task(task_id)
    if not task:
        return
    start_research_task(task_id)
    try:
        request = task["request"]
        task_type = task["task_type"]
        if task_type == "scheduled_job":
            report = await _execute_job(int(request["job_id"]))
            if not report:
                raise RuntimeError("定时任务没有成功生成报告，请查看任务状态。")
        else:
            sync_memory_files_to_db()
            profile = get_profile()
            watchlist = list_watchlist()
            engine = request.get("engine", "auto")
            if task_type == "conversation":
                conversation_id = str(request.get("conversation_id") or "")
                lock = conversation_locks.setdefault(conversation_id, asyncio.Lock())
                async with lock:
                    latest = get_research_task(task_id)
                    if latest and latest["status"] == "cancelled":
                        return
                    result = await _conversation_reply(
                        conversation_id,
                        content=request.get("content", ""),
                        use_web=bool(request.get("use_web", True)),
                        engine=engine,
                        add_user=False,
                    )
                finish_research_task(task_id, status="completed")
                return
            if task_type == "daily":
                query = request.get("context") or request.get("question") or "今日市场简报"
                prompt = daily_brief_prompt(profile, watchlist, query)
                prompt = _with_memory(prompt, query)
                report = await _run_research(
                    "daily",
                    f"{datetime.now().astimezone():%Y-%m-%d} 每日简报",
                    request.get("question", ""),
                    prompt,
                    "balanced",
                    engine=engine,
                    review_mode=request.get("review_mode", "single"),
                )
            elif task_type == "company":
                company = request.get("company", "")
                watchlist_id = int(request.get("watchlist_id") or 0)
                watchlist_item = get_watchlist(watchlist_id) if watchlist_id else None
                if not watchlist_item:
                    watchlist_item, _ = get_or_add_watchlist(
                        {
                            "name": company,
                            "symbol": request.get("symbol", ""),
                            "market": request.get("market", "") or "其他",
                            "thesis": request.get("context", ""),
                            "notes": "",
                        }
                    )
                watchlist_id = int(watchlist_item["id"])
                query = " ".join(
                    filter(
                        None,
                        [
                            company,
                            request.get("symbol", ""),
                            request.get("market", ""),
                            request.get("context", ""),
                        ],
                    )
                )
                prompt = company_prompt(
                    profile,
                    watchlist,
                    company,
                    request.get("symbol", ""),
                    request.get("market", ""),
                    request.get("context", ""),
                )
                prompt = _with_memory(prompt, query)
                report = await _run_research(
                    "company",
                    f"{company} 公司研究",
                    query,
                    prompt,
                    "deep",
                    engine=engine,
                    watchlist_id=watchlist_id,
                    review_mode=request.get("review_mode", "single"),
                )
            elif task_type == "qa":
                question = request.get("question", "").strip()
                if not question:
                    raise ValueError("请先写下要研究的问题。")
                prompt = qa_prompt(
                    profile,
                    watchlist,
                    question,
                    request.get("context", ""),
                )
                prompt = _with_memory(prompt, f"{question} {request.get('context', '')}")
                report = await _run_research(
                    "qa",
                    question[:60],
                    question,
                    prompt,
                    "balanced",
                    engine=engine,
                    review_mode=request.get("review_mode", "single"),
                )
            else:
                raise ValueError(f"不支持的后台研究类型：{task_type}")
        finish_research_task(task_id, status="completed", report_id=report["id"])
    except asyncio.CancelledError:
        finish_research_task(task_id, status="cancelled", error="用户已取消。")
        raise
    except Exception as exc:
        if isinstance(exc, HTTPException):
            message = str(exc.detail)
        else:
            message = _friendly_error(exc)
        finish_research_task(task_id, status="failed", error=message)


def _enqueue_research(task_type: str, title: str, payload: dict) -> dict:
    task = create_research_task(task_type, title, payload)
    _track_background(_execute_research_task(task["id"]), task_id=task["id"])
    return task


async def _codex_archive_loop() -> None:
    await asyncio.sleep(2)
    while True:
        await codex_archive.sync()
        await asyncio.sleep(5)


async def _backup_loop() -> None:
    while True:
        try:
            backup = await asyncio.to_thread(create_database_backup)
            if backup:
                backup_state["last_success_at"] = backup["created_at"]
            backup_state["last_error"] = ""
        except Exception as exc:
            backup_state["last_error"] = _friendly_error(exc)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_runtime_dirs()
    init_db()
    sync_memory_files_to_db()
    scheduler_task = asyncio.create_task(_scheduler())
    backup_task = asyncio.create_task(_backup_loop())
    codex_sync_task = None if DEMO_MODE else asyncio.create_task(_codex_archive_loop())
    update_task = (
        asyncio.create_task(automatic_update_loop())
        if should_run_automatic_loop()
        else None
    )
    try:
        yield
    finally:
        scheduler_task.cancel()
        backup_task.cancel()
        if codex_sync_task:
            codex_sync_task.cancel()
        if update_task:
            update_task.cancel()
        for task in list(background_tasks):
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
        with contextlib.suppress(asyncio.CancelledError):
            await backup_task
        if codex_sync_task:
            with contextlib.suppress(asyncio.CancelledError):
                await codex_sync_task
        if update_task:
            with contextlib.suppress(asyncio.CancelledError):
                await update_task


app = FastAPI(title="天策 AI 投研数字员工", version=APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _is_local_client(host: str | None) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"} or (host or "").startswith("127.")


def _local_lan_ips() -> list[str]:
    candidates: set[str] = set()
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            address = item[4][0]
            if address and not address.startswith("127."):
                candidates.add(address)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if address and not address.startswith("127."):
                candidates.add(address)
    except OSError:
        pass
    return sorted(candidates)


@app.middleware("http")
async def lan_access_guard(request: Request, call_next):
    if LAN_ACCESS_TOKEN:
        client_host = request.client.host if request.client else ""
        if not _is_local_client(client_host):
            token = request.query_params.get("access_token") or request.cookies.get("ai_research_lan_token")
            if not secrets.compare_digest(token or "", LAN_ACCESS_TOKEN):
                return HTMLResponse(
                    "<!doctype html><meta charset='utf-8'>"
                    "<title>需要访问令牌</title>"
                    "<h2>手机访问需要专用链接</h2>"
                    "<p>请在电脑端打开研究台，使用 /api/lan-access 返回的手机访问地址。</p>",
                    status_code=401,
                )
    response = await call_next(request)
    if LAN_ACCESS_TOKEN and request.query_params.get("access_token") == LAN_ACCESS_TOKEN:
        response.set_cookie(
            "ai_research_lan_token",
            LAN_ACCESS_TOKEN,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
        )
    return response


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    jobs = list_jobs()
    backups = list_database_backups()
    engines = await research_client.status()
    codex = engines["codex"]
    api = engines["api"]
    return {
        "ok": True,
        "configured": bool(
            DEMO_MODE
            or (
                codex.get("available")
                and codex.get("logged_in")
                and codex.get("auth_type") == "chatgpt"
            )
            or api.get("available")
        ),
        "demo_mode": DEMO_MODE,
        "model": OPENAI_MODEL,
        "version": APP_VERSION,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "windows": platform.system() == "Windows",
        },
        "engines": engines,
        "codex_archive": codex_archive.status(),
        "active_jobs": sum(1 for job in jobs if job["enabled"]),
        "running_jobs": len(running_jobs),
        "scheduler": dict(scheduler_state),
        "background_research": {
            "running": sum(
                1 for task in list_research_tasks(100) if task["status"] in {"queued", "running"}
            )
        },
        "backups": {
            "count": len(backups),
            "latest": backups[0] if backups else None,
            **backup_state,
        },
    }


@app.get("/api/lan-access")
async def lan_access_get() -> dict:
    query = urlencode({"access_token": LAN_ACCESS_TOKEN}) if LAN_ACCESS_TOKEN else ""
    urls = [
        f"http://{ip}:{APP_PORT}/?{query}" if query else f"http://{ip}:{APP_PORT}/"
        for ip in _local_lan_ips()
    ]
    return {
        "enabled": bool(LAN_ACCESS_TOKEN),
        "host": "0.0.0.0",
        "port": APP_PORT,
        "local_url": f"http://127.0.0.1:{APP_PORT}/",
        "urls": urls,
    }


@app.get("/api/memory/overview")
async def memory_overview_get() -> dict:
    result = memory_overview()
    result["codex_archive"] = codex_archive.status()
    return result


@app.get("/api/updates/status")
async def updates_status_get() -> dict:
    return update_status()


@app.post("/api/updates/check")
async def updates_check_post() -> dict:
    return await asyncio.to_thread(check_latest)


@app.post("/api/updates/install")
async def updates_install_post(
    x_ai_research_action: str = Header(default=""),
) -> dict:
    if x_ai_research_action != "install-update":
        raise HTTPException(status_code=403, detail="缺少本机更新确认标记。")
    try:
        return await asyncio.to_thread(launch_updater)
    except UpdateServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/codex/sync")
async def codex_sync_post() -> dict:
    if DEMO_MODE:
        raise HTTPException(status_code=409, detail="演示模式不会读取本机 Codex 对话。")
    state = await codex_archive.sync()
    if state.get("last_error"):
        raise HTTPException(status_code=503, detail=state["last_error"])
    return state


@app.get("/api/codex/launch")
async def codex_launch_get() -> dict:
    prompt = (
        "请使用 $ai-investment-employee 作为我的投研数字员工。"
        "先读取本项目的老板说明书、自选公司、研究原则、"
        "决策、纠正记录和 conversations 里的最近相关对话，再问我今天想研究什么。"
        "只做公开信息研究和汇报，不给交易指令。"
    )
    return {
        "url": "codex://new?" + urlencode({"path": str(PRODUCT_DIR.resolve()), "prompt": prompt}),
        "workspace": str(PRODUCT_DIR.resolve()),
        "platform": platform.system(),
        "fallback": (
            "如果 Codex 没有自动打开，请先运行 Windows_首次配置.cmd，"
            "再打开 ChatGPT Windows 客户端的 Codex，并选择这个产品文件夹。"
            if platform.system() == "Windows"
            else "如果 Codex 没有自动打开，请打开 Codex 并选择这个产品文件夹。"
        ),
        "note": "只同步在这个产品文件夹中创建的 Codex 投研对话。",
        "sync_explanation": [
            "按钮只负责打开正确的产品文件夹，并把启动语放进输入框；老板仍需自己点击发送。",
            "Codex 在这个文件夹里读取老板说明书、自选公司、决策与纠正记录。",
            "网页约每 5 秒自动导入这个文件夹里的可见问答，不需要手动点击同步。",
            "网页消息每次发送和回复后都会立即写入 conversations 本机共享档案，Codex 下次回答可读取。",
            "网页端和 Codex 共用本机资料库，但不是同一块实时编辑的聊天窗口。",
        ],
    }


@app.get("/api/frameworks")
async def frameworks_get() -> list[dict]:
    return list_frameworks()


@app.get("/api/source-policy")
async def source_policy_get() -> dict:
    return source_policy_overview()


@app.get("/api/safety-policy")
async def safety_policy_get() -> dict:
    return safety_policy_overview()


@app.get("/api/data-sources")
async def data_sources_get(
    markets: list[str] = Query(default=[]),
    company: str = Query(default="", max_length=100),
    symbol: str = Query(default="", max_length=30),
) -> dict:
    requested = markets or [*get_profile()["primary_markets"], *get_profile()["reference_markets"]]
    return build_collection_plan(requested, company=company, symbol=symbol)


@app.get("/api/backups")
async def backups_get() -> dict:
    backups = list_database_backups()
    return {
        "items": backups,
        "retention": 14,
        "latest": backups[0] if backups else None,
        **backup_state,
    }


@app.post("/api/backups", status_code=201)
async def backups_post() -> dict:
    try:
        backup = await asyncio.to_thread(create_database_backup, force=True)
    except Exception as exc:
        backup_state["last_error"] = _friendly_error(exc)
        raise HTTPException(status_code=500, detail=backup_state["last_error"]) from exc
    if not backup:
        raise HTTPException(status_code=409, detail="数据库尚未创建，暂时没有可备份的数据。")
    backup_state["last_success_at"] = backup["created_at"]
    backup_state["last_error"] = ""
    return backup


@app.get("/api/profile")
async def profile_get() -> dict:
    sync_memory_files_to_db()
    return get_profile()


@app.put("/api/profile")
async def profile_put(profile: Profile) -> dict:
    return save_profile(profile.model_dump())


@app.get("/api/watchlist")
async def watchlist_get() -> list[dict]:
    sync_memory_files_to_db()
    return list_watchlist()


@app.post("/api/watchlist", status_code=201)
async def watchlist_post(item: WatchlistCreate) -> dict:
    try:
        return add_watchlist(item.model_dump())
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise HTTPException(status_code=409, detail="这家公司已经在自选列表里。") from exc
        raise


@app.delete("/api/watchlist/{item_id}")
async def watchlist_delete(item_id: int) -> dict:
    if not delete_watchlist(item_id):
        raise HTTPException(status_code=404, detail="没有找到这条自选记录。")
    return {"deleted": True}


@app.get("/api/watchlist/{item_id}/workspace")
async def watchlist_workspace_get(item_id: int) -> dict:
    result = get_company_workspace(item_id)
    if not result:
        raise HTTPException(status_code=404, detail="没有找到这家公司。")
    return result


@app.put("/api/watchlist/{item_id}/tracking")
async def watchlist_tracking_put(item_id: int, request: CompanyTrackingUpdate) -> dict:
    company = get_watchlist(item_id)
    if not company:
        raise HTTPException(status_code=404, detail="没有找到这家公司。")
    payload = {
        "name": f"{company['name']} · 定期公司跟踪",
        "job_type": "company_tracking",
        "frequency": request.frequency,
        "interval_minutes": 1440,
        "time_of_day": request.time_of_day,
        "weekday": request.weekday,
        "day_of_month": request.day_of_month,
        "month_of_year": request.month_of_year,
        "active_start": "00:00",
        "active_end": "23:59",
        "enabled": request.enabled,
        "engine": request.engine,
        "frameworks": request.frameworks,
        "watchlist_id": item_id,
        "prompt": f"持续跟踪{company['name']}的公告、财务、经营、管理层、行业和估值相关变化。",
    }
    job = get_company_tracking_job(item_id)
    job = save_job(job["id"], payload) if job else create_job(payload)
    updated = update_watchlist_tracking(
        item_id,
        enabled=request.enabled,
        frequency=request.frequency,
        time_of_day=request.time_of_day,
    )
    return {"company": updated, "tracking_job": job}


@app.get("/api/hypotheses")
async def hypotheses_get(
    watchlist_id: int | None = None,
    status: str = Query(default="", max_length=30),
) -> list[dict]:
    return list_hypotheses(watchlist_id=watchlist_id, status=status)


@app.post("/api/hypotheses", status_code=201)
async def hypothesis_post(request: HypothesisCreate) -> dict:
    if not get_watchlist(request.watchlist_id):
        raise HTTPException(status_code=404, detail="关联公司不存在。")
    return create_hypothesis(request.model_dump())


@app.put("/api/hypotheses/{hypothesis_id}")
async def hypothesis_put(hypothesis_id: int, request: HypothesisUpdate) -> dict:
    if not get_hypothesis(hypothesis_id):
        raise HTTPException(status_code=404, detail="研究假设不存在。")
    result = update_hypothesis(hypothesis_id, request.model_dump())
    if not result:
        raise HTTPException(status_code=404, detail="研究假设不存在。")
    return result


@app.delete("/api/hypotheses/{hypothesis_id}")
async def hypothesis_delete(hypothesis_id: int) -> dict:
    if not delete_hypothesis(hypothesis_id):
        raise HTTPException(status_code=404, detail="研究假设不存在。")
    return {"deleted": True}


@app.get("/api/reports")
async def reports_get(
    limit: int = Query(default=100, ge=1, le=500),
    report_type: str | None = None,
    watchlist_id: int | None = None,
) -> list[dict]:
    return list_reports(limit, report_type, watchlist_id=watchlist_id)


@app.get("/api/reports/{report_id}")
async def report_get(report_id: int) -> dict:
    report = get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在。")
    return report


@app.delete("/api/reports/{report_id}")
async def report_delete(report_id: int) -> dict:
    if not delete_report(report_id):
        raise HTTPException(status_code=404, detail="报告不存在。")
    return {"deleted": True}


@app.get("/api/reports/{report_id}/download")
async def report_download(report_id: int, format: str = Query(default="md")) -> FileResponse:
    report = get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在。")
    try:
        path = export_report(report, format.lower())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name)


@app.get("/api/conversations")
async def conversations_get(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    query: str = Query(default="", max_length=100),
    source: str = Query(default="", max_length=30),
    watchlist_id: int | None = None,
) -> list[dict]:
    return list_conversations(
        limit,
        offset,
        query=query.strip(),
        source=source.strip(),
        watchlist_id=watchlist_id,
    )


@app.post("/api/conversations", status_code=201)
async def conversation_post(request: ConversationCreate) -> dict:
    if request.watchlist_id is not None and not get_watchlist(request.watchlist_id):
        raise HTTPException(status_code=404, detail="关联公司不存在。")
    return create_conversation(request.title, source="web", watchlist_id=request.watchlist_id)


@app.get("/api/conversations/{conversation_id}")
async def conversation_get(conversation_id: str) -> dict:
    conversation = get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在。")
    return conversation


@app.delete("/api/conversations/{conversation_id}")
async def conversation_delete(conversation_id: str) -> dict:
    if conversation_has_active_task(conversation_id):
        raise HTTPException(status_code=409, detail="这条对话仍有任务在执行，请先等待完成或取消任务。")
    if not delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="对话不存在。")
    return {"deleted": True}


@app.get("/api/conversations/{conversation_id}/download")
async def conversation_download(
    conversation_id: str,
    format: str = Query(default="md"),
) -> FileResponse:
    conversation = get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在。")
    try:
        path = export_conversation(conversation, format.lower())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name)


@app.post("/api/conversations/{conversation_id}/messages")
async def conversation_message_post(
    conversation_id: str,
    request: ConversationMessageCreate,
) -> dict:
    conversation = get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在。")
    try:
        return await _conversation_reply(
            conversation_id,
            content=request.content,
            use_web=request.use_web,
            engine=request.engine,
            add_user=True,
        )
    except (ResearchUnavailable, CodexUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"对话生成失败：{_friendly_error(exc)}") from exc


@app.post("/api/conversations/{conversation_id}/messages/enqueue", status_code=202)
async def conversation_message_enqueue(
    conversation_id: str,
    request: ConversationMessageCreate,
) -> dict:
    conversation = get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在。")
    add_message(
        conversation_id,
        "user",
        request.content,
        metadata={"engine": request.engine, "use_web": request.use_web, "queued": True},
    )
    return _enqueue_research(
        "conversation",
        f"回复：{conversation['title']}",
        {
            "conversation_id": conversation_id,
            "content": request.content,
            "use_web": request.use_web,
            "engine": request.engine,
        },
    )


@app.get("/api/jobs")
async def jobs_get() -> list[dict]:
    return list_jobs()


@app.get("/api/jobs/{job_id}/runs")
async def job_runs_get(
    job_id: int,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail="定时任务不存在。")
    return list_job_runs(job_id, limit)


@app.post("/api/jobs", status_code=201)
async def job_post(request: ScheduledJobCreate) -> dict:
    return create_job(request.model_dump())


@app.put("/api/jobs/{job_id}")
async def job_put(job_id: int, request: ScheduledJobUpdate) -> dict:
    result = save_job(job_id, request.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="定时任务不存在。")
    return result


@app.delete("/api/jobs/{job_id}")
async def job_delete(job_id: int) -> dict:
    if job_id in running_jobs:
        raise HTTPException(status_code=409, detail="这个任务正在运行，结束后才能删除。")
    if not delete_job(job_id):
        raise HTTPException(status_code=404, detail="定时任务不存在。")
    return {"deleted": True}


@app.post("/api/jobs/{job_id}/run")
async def job_run(job_id: int) -> dict:
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail="定时任务不存在。")
    if job_id in running_jobs:
        raise HTTPException(status_code=409, detail="这个任务正在运行，请稍后再试。")
    report = await _execute_job(job_id)
    if not report:
        raise HTTPException(status_code=502, detail="任务没有成功生成报告，请查看任务状态。")
    return report


@app.post("/api/jobs/{job_id}/enqueue", status_code=202)
async def job_enqueue(job_id: int) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="定时任务不存在。")
    if job_id in running_jobs:
        raise HTTPException(status_code=409, detail="这个任务正在运行，请稍后再试。")
    return _enqueue_research("scheduled_job", f"试跑：{job['name']}", {"job_id": job_id})


@app.get("/api/background-research")
async def background_research_get(limit: int = Query(default=30, ge=1, le=200)) -> list[dict]:
    return list_research_tasks(limit)


@app.get("/api/background-research/{task_id}")
async def background_research_item_get(task_id: str) -> dict:
    task = get_research_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="后台任务不存在。")
    return task


@app.post("/api/background-research/{task_id}/cancel")
async def background_research_cancel(task_id: str) -> dict:
    task = get_research_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="后台任务不存在。")
    if task["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="这个后台任务已经结束，不能取消。")
    running = running_research_tasks.get(task_id)
    if running and not running.done():
        running.cancel()
    finish_research_task(task_id, status="cancelled", error="用户已取消。")
    return get_research_task(task_id) or {"id": task_id, "status": "cancelled"}


@app.post("/api/background-research/{task_id}/retry", status_code=202)
async def background_research_retry(task_id: str) -> dict:
    task = get_research_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="后台任务不存在。")
    if task["status"] not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="只有失败或已取消的后台任务可以重试。")
    return _enqueue_research(
        task["task_type"],
        f"重试：{task['title']}",
        dict(task["request"]),
    )


@app.post("/api/background-research/daily", status_code=202)
async def background_research_daily(request: ResearchRequest) -> dict:
    return _enqueue_research("daily", "生成今日市场简报", request.model_dump())


@app.post("/api/background-research/company", status_code=202)
async def background_research_company(request: CompanyResearchRequest) -> dict:
    watchlist_item = get_watchlist(request.watchlist_id) if request.watchlist_id else None
    if not watchlist_item:
        watchlist_item, _ = get_or_add_watchlist(
            {
                "name": request.company,
                "symbol": request.symbol,
                "market": request.market or "其他",
                "thesis": request.context,
                "notes": "",
            }
        )
    payload = request.model_dump()
    payload["watchlist_id"] = watchlist_item["id"]
    return _enqueue_research(
        "company",
        f"研究公司：{request.company}",
        payload,
    )


@app.post("/api/background-research/ask", status_code=202)
async def background_research_ask(request: ResearchRequest) -> dict:
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="请先写下要研究的问题。")
    return _enqueue_research("qa", request.question[:80], request.model_dump())


@app.post("/api/research/daily")
async def research_daily(request: ResearchRequest) -> dict:
    sync_memory_files_to_db()
    profile = get_profile()
    now = datetime.now().astimezone()
    prompt = daily_brief_prompt(profile, list_watchlist(), request.context or request.question)
    prompt = _with_memory(prompt, request.context or request.question or "今日市场简报")
    return await _run_research(
        "daily",
        f"{now:%Y-%m-%d} 每日简报",
        request.question,
        prompt,
        "balanced",
        engine=request.engine,
        review_mode=request.review_mode,
    )


@app.post("/api/research/company")
async def research_company(request: CompanyResearchRequest) -> dict:
    sync_memory_files_to_db()
    profile = get_profile()
    watchlist_item = get_watchlist(request.watchlist_id) if request.watchlist_id else None
    if not watchlist_item:
        watchlist_item, _ = get_or_add_watchlist(
            {
                "name": request.company,
                "symbol": request.symbol,
                "market": request.market or "其他",
                "thesis": request.context,
                "notes": "",
            }
        )
    prompt = company_prompt(
        profile,
        list_watchlist(),
        request.company,
        request.symbol,
        request.market,
        request.context,
    )
    prompt = _with_memory(
        prompt,
        " ".join(filter(None, [request.company, request.symbol, request.market, request.context])),
    )
    return await _run_research(
        "company",
        f"{request.company} 公司研究",
        " ".join(filter(None, [request.company, request.symbol, request.market])),
        prompt,
        "deep",
        engine=request.engine,
        watchlist_id=watchlist_item["id"],
        review_mode=request.review_mode,
    )


@app.post("/api/research/ask")
async def research_ask(request: ResearchRequest) -> dict:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="请先写下要研究的问题。")
    sync_memory_files_to_db()
    profile = get_profile()
    prompt = qa_prompt(profile, list_watchlist(), question, request.context)
    prompt = _with_memory(prompt, f"{question} {request.context}")
    return await _run_research(
        "qa",
        question[:60],
        question,
        prompt,
        "balanced",
        engine=request.engine,
        review_mode=request.review_mode,
    )


@app.get("/{path:path}", include_in_schema=False)
async def spa_fallback(path: str) -> FileResponse:
    candidate = STATIC_DIR / path
    if candidate.is_file() and STATIC_DIR in candidate.resolve().parents:
        return FileResponse(candidate)
    return FileResponse(STATIC_DIR / "index.html")
