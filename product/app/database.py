from __future__ import annotations

import json
import re
import sqlite3
import uuid
from calendar import monthrange
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .config import (
    BACKUPS_DIR,
    CONVERSATIONS_DIR,
    DB_PATH,
    REPORTS_DIR,
    WORKSPACE_DIR,
    ensure_runtime_dirs,
)
from .data_sources import build_collection_plan
from .source_quality import align_sources_with_content, audit_sources, enrich_sources


DEFAULT_PROFILE: dict[str, Any] = {
    "owner_name": "老板",
    "primary_markets": ["A股", "港股"],
    "reference_markets": ["美股", "日本", "韩国"],
    "focus_sectors": ["科技", "消费"],
    "analysis_framework": "全球局势 → 市场 → 板块 → 公司 → 估值与验证信号",
    "reference_investors": [],
    "investment_horizon": "长期为主",
    "risk_preference": "稳健，先研究公司，再考虑估值",
    "preferred_metrics": ["商业模式", "管理层", "自由现金流", "ROE", "ROIC", "负债", "PE"],
    "excluded_sectors": [],
    "report_style": "先给结论，再给事实、分析、反方证据和风险",
    "data_permissions": ["公开市场信息", "交易所公告", "公司公告与财报", "政府和监管机构数据"],
    "privacy_boundaries": ["不读取微信和通讯录", "不连接证券账户", "不保存密码和验证码"],
    "report_time": "08:00",
    "auto_brief_enabled": False,
    "last_auto_brief_date": "",
}

DEFAULT_JOBS = [
    {
        "name": "定时消息面扫描",
        "job_type": "hourly_news",
        "frequency": "interval",
        "interval_minutes": 120,
        "time_of_day": "08:00",
        "weekday": -1,
        "active_start": "07:00",
        "active_end": "23:00",
        "enabled": False,
        "engine": "auto",
        "frameworks": [],
        "prompt": "扫描全球、A股、港股及自选公司的最新重要消息，只汇报新增变化。",
    },
    {
        "name": "每日市场晨报",
        "job_type": "daily_brief",
        "frequency": "daily",
        "interval_minutes": 1440,
        "time_of_day": "08:00",
        "weekday": -1,
        "active_start": "00:00",
        "active_end": "23:59",
        "enabled": True,
        "engine": "auto",
        "frameworks": [],
        "prompt": "生成全球到A股、港股、板块和自选公司的每日研究简报。",
    },
    {
        "name": "每周基本面复盘",
        "job_type": "weekly_review",
        "frequency": "weekly",
        "interval_minutes": 10080,
        "time_of_day": "20:00",
        "weekday": 5,
        "active_start": "00:00",
        "active_end": "23:59",
        "enabled": False,
        "engine": "auto",
        "frameworks": [],
        "prompt": "复盘本周公司基本面、关键假设、反方证据和待核验事项。",
    },
]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    ensure_runtime_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def list_database_backups() -> list[dict[str, Any]]:
    ensure_runtime_dirs()
    backups: list[dict[str, Any]] = []
    for path in sorted(BACKUPS_DIR.glob("research-*.db"), reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue
        backups.append(
            {
                "name": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(
                    timespec="seconds"
                ),
            }
        )
    return backups


def create_database_backup(*, force: bool = False, keep: int = 14) -> dict[str, Any] | None:
    """Create a consistent local SQLite snapshot without mutating the live database."""
    ensure_runtime_dirs()
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        return None

    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d-%H%M%S") if force else now.strftime("%Y%m%d")
    target = BACKUPS_DIR / f"research-{stamp}.db"
    if target.exists() and not force:
        return next(
            (item for item in list_database_backups() if item["path"] == str(target)),
            None,
        )
    if target.exists():
        suffix = 1
        while (BACKUPS_DIR / f"research-{stamp}-{suffix}.db").exists():
            suffix += 1
        target = BACKUPS_DIR / f"research-{stamp}-{suffix}.db"

    temporary = target.with_suffix(".db.tmp")
    source = sqlite3.connect(str(DB_PATH), timeout=30)
    destination = sqlite3.connect(str(temporary), timeout=30)
    backup_error: Exception | None = None
    try:
        source_check = source.execute("PRAGMA quick_check").fetchone()
        if not source_check or source_check[0] != "ok":
            raise sqlite3.DatabaseError("主数据库完整性检查未通过，已停止备份。")
        source.backup(destination)
        destination.commit()
        target_check = destination.execute("PRAGMA quick_check").fetchone()
        if not target_check or target_check[0] != "ok":
            raise sqlite3.DatabaseError("备份数据库完整性检查未通过。")
    except Exception as exc:
        backup_error = exc
    finally:
        destination.close()
        source.close()
    if backup_error:
        temporary.unlink(missing_ok=True)
        raise backup_error

    temporary.replace(target)
    backups = list_database_backups()
    for stale in backups[max(1, keep):]:
        try:
            Path(stale["path"]).unlink(missing_ok=True)
        except OSError:
            continue
    return next(
        (item for item in list_database_backups() if item["path"] == str(target)),
        None,
    )


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    if name not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                market TEXT NOT NULL,
                thesis TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                tracking_frequency TEXT NOT NULL DEFAULT 'manual',
                tracking_enabled INTEGER NOT NULL DEFAULT 0,
                tracking_time TEXT NOT NULL DEFAULT '09:00',
                created_at TEXT NOT NULL,
                UNIQUE(symbol, market)
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'web',
                status TEXT NOT NULL DEFAULT 'active',
                watchlist_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(watchlist_id) REFERENCES watchlist(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                external_id TEXT NOT NULL DEFAULT '',
                sources_json TEXT NOT NULL DEFAULT '[]',
                model TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                job_type TEXT NOT NULL,
                frequency TEXT NOT NULL,
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                time_of_day TEXT NOT NULL DEFAULT '08:00',
                weekday INTEGER NOT NULL DEFAULT 0,
                active_start TEXT NOT NULL DEFAULT '00:00',
                active_end TEXT NOT NULL DEFAULT '23:59',
                enabled INTEGER NOT NULL DEFAULT 0,
                engine TEXT NOT NULL DEFAULT 'auto',
                frameworks_json TEXT NOT NULL DEFAULT '[]',
                watchlist_id INTEGER,
                day_of_month INTEGER NOT NULL DEFAULT 1,
                month_of_year INTEGER NOT NULL DEFAULT 1,
                prompt TEXT NOT NULL DEFAULT '',
                last_run_at TEXT NOT NULL DEFAULT '',
                next_run_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(watchlist_id) REFERENCES watchlist(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                trigger_type TEXT NOT NULL DEFAULT 'manual',
                scheduled_for TEXT NOT NULL DEFAULT '',
                attempt_count INTEGER NOT NULL DEFAULT 1,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                report_id INTEGER,
                conversation_id TEXT,
                error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(job_id) REFERENCES scheduled_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS research_tasks (
                id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                request_json TEXT NOT NULL DEFAULT '{}',
                report_id INTEGER,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,
                title TEXT NOT NULL,
                query TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                sources_json TEXT NOT NULL DEFAULT '[]',
                model TEXT NOT NULL DEFAULT '',
                engine TEXT NOT NULL DEFAULT 'api',
                review_mode TEXT NOT NULL DEFAULT 'single',
                status TEXT NOT NULL DEFAULT 'completed',
                watchlist_id INTEGER,
                file_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_hypotheses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watchlist_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                statement TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'tracking',
                support_json TEXT NOT NULL DEFAULT '[]',
                counter_json TEXT NOT NULL DEFAULT '[]',
                validation_json TEXT NOT NULL DEFAULT '[]',
                invalidation_json TEXT NOT NULL DEFAULT '[]',
                next_review_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(watchlist_id) REFERENCES watchlist(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id, id);
            CREATE INDEX IF NOT EXISTS idx_conversations_updated
                ON conversations(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_next_run
                ON scheduled_jobs(enabled, next_run_at);
            CREATE INDEX IF NOT EXISTS idx_research_tasks_created
                ON research_tasks(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_hypotheses_watchlist
                ON research_hypotheses(watchlist_id, updated_at DESC);
            """
        )
        _ensure_column(conn, "reports", "conversation_id TEXT")
        _ensure_column(conn, "reports", "job_run_id INTEGER")
        _ensure_column(conn, "reports", "source TEXT NOT NULL DEFAULT 'web'")
        _ensure_column(conn, "reports", "engine TEXT NOT NULL DEFAULT 'api'")
        _ensure_column(conn, "reports", "review_mode TEXT NOT NULL DEFAULT 'single'")
        _ensure_column(conn, "reports", "watchlist_id INTEGER")
        _ensure_column(conn, "reports", "file_path TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "scheduled_jobs", "engine TEXT NOT NULL DEFAULT 'auto'")
        _ensure_column(conn, "scheduled_jobs", "frameworks_json TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "scheduled_jobs", "watchlist_id INTEGER")
        _ensure_column(conn, "scheduled_jobs", "day_of_month INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "scheduled_jobs", "month_of_year INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "job_runs", "trigger_type TEXT NOT NULL DEFAULT 'manual'")
        _ensure_column(conn, "job_runs", "scheduled_for TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "job_runs", "attempt_count INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "messages", "external_id TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "conversations", "watchlist_id INTEGER")
        _ensure_column(conn, "watchlist", "tracking_frequency TEXT NOT NULL DEFAULT 'manual'")
        _ensure_column(conn, "watchlist", "tracking_enabled INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "watchlist", "tracking_time TEXT NOT NULL DEFAULT '09:00'")
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_external
               ON messages(external_id) WHERE external_id != ''"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_conversations_watchlist
               ON conversations(watchlist_id, updated_at DESC)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_reports_watchlist
               ON reports(watchlist_id, created_at DESC)"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_job_runs_scheduled_once
               ON job_runs(job_id, scheduled_for)
               WHERE trigger_type='scheduled' AND scheduled_for != ''"""
        )

        row = conn.execute("SELECT 1 FROM settings WHERE key='profile'").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
                ("profile", json.dumps(DEFAULT_PROFILE, ensure_ascii=False), _now()),
            )
        if not conn.execute("SELECT 1 FROM scheduled_jobs LIMIT 1").fetchone():
            for job in DEFAULT_JOBS:
                _insert_job(conn, job)
        if not conn.execute("SELECT 1 FROM settings WHERE key='v06_defaults_applied'").fetchone():
            conn.execute(
                """UPDATE scheduled_jobs
                   SET interval_minutes=120,
                       name=CASE WHEN name='每小时消息面扫描' THEN '定时消息面扫描' ELSE name END,
                       updated_at=?
                   WHERE job_type='hourly_news' AND interval_minutes=60 AND last_run_at=''""",
                (_now(),),
            )
            conn.execute(
                """UPDATE scheduled_jobs
                   SET enabled=1, updated_at=?
                   WHERE job_type='daily_brief' AND last_run_at=''""",
                (_now(),),
            )
            conn.execute(
                """UPDATE scheduled_jobs
                   SET weekday=-1, updated_at=?
                   WHERE frequency IN ('interval', 'daily') AND weekday=0 AND last_run_at=''""",
                (_now(),),
            )
            conn.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
                ("v06_defaults_applied", "1", _now()),
            )
        if not conn.execute(
            "SELECT 1 FROM settings WHERE key='v0113_public_frameworks_default_off'"
        ).fetchone():
            legacy_frameworks = ["段永平公开方法", "但斌公开方法"]
            conn.execute(
                """UPDATE scheduled_jobs
                   SET frameworks_json='[]', updated_at=?
                   WHERE frameworks_json=?""",
                (_now(), json.dumps(legacy_frameworks, ensure_ascii=False)),
            )
            profile_row = conn.execute(
                "SELECT value FROM settings WHERE key='profile'"
            ).fetchone()
            if profile_row:
                try:
                    profile = json.loads(profile_row["value"])
                except (TypeError, json.JSONDecodeError):
                    profile = {}
                if profile.get("reference_investors") == legacy_frameworks:
                    profile["reference_investors"] = []
                    conn.execute(
                        "UPDATE settings SET value=?, updated_at=? WHERE key='profile'",
                        (json.dumps(profile, ensure_ascii=False), _now()),
                    )
            conn.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
                ("v0113_public_frameworks_default_off", "1", _now()),
            )
        conn.execute(
            """UPDATE scheduled_jobs
               SET frequency='interval',
                   interval_minutes=CASE
                       WHEN interval_minutes IN (60, 120, 240, 720) THEN interval_minutes
                       ELSE 120
                   END,
                   time_of_day='08:00',
                   weekday=-1,
                   updated_at=?
               WHERE job_type='hourly_news'
                 AND (frequency!='interval'
                      OR interval_minutes NOT IN (60, 120, 240, 720)
                      OR weekday!=-1)""",
            (_now(),),
        )
        conn.execute(
            """UPDATE scheduled_jobs
               SET frequency=CASE WHEN frequency='weekly' THEN 'weekly' ELSE 'daily' END,
                   interval_minutes=1440,
                   weekday=CASE WHEN frequency='weekly' AND weekday BETWEEN 0 AND 6 THEN weekday ELSE -1 END,
                   updated_at=?
               WHERE job_type!='hourly_news'
                 AND (frequency NOT IN ('daily', 'weekly')
                      OR interval_minutes!=1440
                      OR (frequency!='weekly' AND weekday!=-1))""",
            (_now(),),
        )
        conn.execute(
            """UPDATE research_tasks
               SET status='failed', error='研究台重启，原后台任务已中止，请重新发起。', finished_at=?
               WHERE status IN ('queued', 'running')""",
            (_now(),),
        )
        interrupted_at = _now()
        interrupted_runs = conn.execute(
            """SELECT r.id, r.job_id, r.trigger_type, r.scheduled_for, j.next_run_at, j.enabled
               FROM job_runs r
               JOIN scheduled_jobs j ON j.id=r.job_id
               WHERE r.status='running'"""
        ).fetchall()
        for run in interrupted_runs:
            conn.execute(
                """UPDATE job_runs
                   SET status='interrupted', finished_at=?,
                       error='研究台上次关闭时任务尚未完成；正式计划会在本次启动后自动重试。'
                   WHERE id=?""",
                (interrupted_at, run["id"]),
            )
            if (
                run["trigger_type"] == "scheduled"
                and run["scheduled_for"]
                and bool(run["enabled"])
                and (not run["next_run_at"] or run["next_run_at"] > run["scheduled_for"])
            ):
                conn.execute(
                    """UPDATE scheduled_jobs
                       SET next_run_at=?, updated_at=?
                       WHERE id=?""",
                    (run["scheduled_for"], interrupted_at, run["job_id"]),
                )


def get_profile() -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
    if not row:
        return DEFAULT_PROFILE.copy()
    profile = DEFAULT_PROFILE.copy()
    profile.update(json.loads(row["value"]))
    return profile


def get_setting(key: str, default: Any = None) -> Any:
    with connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return row["value"]


def save_setting(key: str, value: Any) -> Any:
    with connection() as conn:
        conn.execute(
            """INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, json.dumps(value, ensure_ascii=False), _now()),
        )
    return value


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = DEFAULT_PROFILE.copy()
    normalized.update(profile)
    with connection() as conn:
        conn.execute(
            """INSERT INTO settings(key, value, updated_at) VALUES ('profile', ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (json.dumps(normalized, ensure_ascii=False), _now()),
        )
    _write_profile_markdown(normalized)
    return normalized


def list_watchlist() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT w.*,
                      (SELECT COUNT(*) FROM reports r WHERE r.watchlist_id=w.id) AS report_count,
                      (SELECT COUNT(*) FROM conversations c WHERE c.watchlist_id=w.id) AS conversation_count,
                      COALESCE((SELECT MAX(r.created_at) FROM reports r WHERE r.watchlist_id=w.id), '')
                          AS last_report_at,
                      (SELECT id FROM scheduled_jobs j
                       WHERE j.watchlist_id=w.id AND j.job_type='company_tracking'
                       ORDER BY j.id DESC LIMIT 1) AS tracking_job_id
               FROM watchlist w
               ORDER BY w.created_at DESC, w.id DESC"""
        ).fetchall()
    return [_watchlist_row(row) for row in rows]


def get_watchlist(item_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT w.*,
                      (SELECT COUNT(*) FROM reports r WHERE r.watchlist_id=w.id) AS report_count,
                      (SELECT COUNT(*) FROM conversations c WHERE c.watchlist_id=w.id) AS conversation_count,
                      COALESCE((SELECT MAX(r.created_at) FROM reports r WHERE r.watchlist_id=w.id), '')
                          AS last_report_at,
                      (SELECT id FROM scheduled_jobs j
                       WHERE j.watchlist_id=w.id AND j.job_type='company_tracking'
                       ORDER BY j.id DESC LIMIT 1) AS tracking_job_id
               FROM watchlist w WHERE w.id=?""",
            (item_id,),
        ).fetchone()
    return _watchlist_row(row) if row else None


def find_watchlist(symbol: str, market: str, name: str = "") -> dict[str, Any] | None:
    symbol = symbol.strip().upper()
    with connection() as conn:
        row = None
        if symbol:
            row = conn.execute(
                "SELECT id FROM watchlist WHERE symbol=? AND market=?",
                (symbol, market.strip()),
            ).fetchone()
        if not row and name.strip():
            row = conn.execute(
                "SELECT id FROM watchlist WHERE name=? AND market=? ORDER BY id DESC LIMIT 1",
                (name.strip(), market.strip()),
            ).fetchone()
    return get_watchlist(int(row["id"])) if row else None


def _watchlist_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["tracking_enabled"] = bool(result.get("tracking_enabled"))
    return result


def add_watchlist(item: dict[str, str]) -> dict[str, Any]:
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO watchlist(symbol, name, market, thesis, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                item["symbol"].strip().upper(),
                item["name"].strip(),
                item["market"].strip(),
                item.get("thesis", "").strip(),
                item.get("notes", "").strip(),
                _now(),
            ),
        )
        row = conn.execute("SELECT * FROM watchlist WHERE id=?", (cursor.lastrowid,)).fetchone()
    result = get_watchlist(int(row["id"])) or dict(row)
    _write_watchlist_markdown()
    return result


def get_or_add_watchlist(item: dict[str, str]) -> tuple[dict[str, Any], bool]:
    market = item.get("market", "").strip() or "其他"
    symbol = item.get("symbol", "").strip().upper() or item.get("name", "").strip()
    existing = find_watchlist(symbol, market, item.get("name", ""))
    if existing:
        return existing, False
    created = add_watchlist(
        {
            "symbol": symbol,
            "name": item.get("name", "").strip(),
            "market": market,
            "thesis": item.get("thesis", "").strip(),
            "notes": item.get("notes", "").strip(),
        }
    )
    return created, True


def update_watchlist_tracking(
    item_id: int,
    *,
    enabled: bool,
    frequency: str,
    time_of_day: str,
) -> dict[str, Any] | None:
    with connection() as conn:
        cursor = conn.execute(
            """UPDATE watchlist
               SET tracking_enabled=?, tracking_frequency=?, tracking_time=?
               WHERE id=?""",
            (1 if enabled else 0, frequency if enabled else "manual", time_of_day, item_id),
        )
    if cursor.rowcount < 1:
        return None
    _write_watchlist_markdown()
    return get_watchlist(item_id)


def delete_watchlist(item_id: int) -> bool:
    with connection() as conn:
        conn.execute("DELETE FROM scheduled_jobs WHERE watchlist_id=?", (item_id,))
        cursor = conn.execute("DELETE FROM watchlist WHERE id=?", (item_id,))
    deleted = cursor.rowcount > 0
    if deleted:
        _write_watchlist_markdown()
    return deleted


def sync_memory_files_to_db() -> None:
    """Reconcile Codex-edited Markdown into the web database.

    The webpage writes the same files after its own changes. Codex is allowed to
    edit the Markdown directly; this function is called before web research and
    scheduled jobs so both entry points converge on one state.
    """

    profile_path = WORKSPACE_DIR / "00_老板投资说明书.md"
    if profile_path.exists():
        text = profile_path.read_text(encoding="utf-8")
        current = get_profile()
        mappings = {
            "称呼": ("owner_name", False),
            "重点市场": ("primary_markets", True),
            "参考市场": ("reference_markets", True),
            "分析顺序": ("analysis_framework", False),
            "参考投资框架": ("reference_investors", True),
            "投资周期": ("investment_horizon", False),
            "报告偏好": ("report_style", False),
            "重点板块": ("focus_sectors", True),
            "常用指标": ("preferred_metrics", True),
            "排除行业": ("excluded_sectors", True),
            "风险偏好": ("risk_preference", False),
            "允许使用的数据": ("data_permissions", True),
            "隐私边界": ("privacy_boundaries", True),
        }
        changed = False
        for label, (key, is_list) in mappings.items():
            match = re.search(rf"^-\s*{re.escape(label)}\s*[:：]\s*(.+)$", text, flags=re.MULTILINE)
            if not match:
                continue
            value = match.group(1).strip()
            if not value or value == "待确认":
                continue
            parsed: Any = _split_values(value) if is_list else value
            if current.get(key) != parsed:
                current[key] = parsed
                changed = True
        if changed:
            timestamp = _now()
            with connection() as conn:
                conn.execute(
                    """INSERT INTO settings(key, value, updated_at) VALUES ('profile', ?, ?)
                       ON CONFLICT(key) DO UPDATE SET
                           value=excluded.value, updated_at=excluded.updated_at""",
                    (json.dumps(current, ensure_ascii=False), timestamp),
                )

    watchlist_path = WORKSPACE_DIR / "01_自选公司.md"
    if not watchlist_path.exists():
        return
    rows: list[tuple[str, str, str, str, str]] = []
    for line in watchlist_path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] in {"公司", "---"} or set(cells[0]) == {"-"}:
            continue
        name, symbol, market, joined, thesis, status = cells[:6]
        if not name or not symbol or symbol == "代码":
            continue
        rows.append((symbol.upper(), name, market, joined or _now()[:10], thesis))
    if rows:
        with connection() as conn:
            for symbol, name, market, joined, thesis in rows:
                conn.execute(
                    """INSERT INTO watchlist(symbol, name, market, thesis, notes, created_at)
                       VALUES (?, ?, ?, ?, '', ?)
                       ON CONFLICT(symbol, market) DO UPDATE SET
                           name=excluded.name, thesis=excluded.thesis""",
                    (symbol, name, market, thesis, joined),
                )


def _split_values(value: str) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in re.split(r"[，,、/]", value) if part.strip()))


def _write_profile_markdown(profile: dict[str, Any]) -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    path = WORKSPACE_DIR / "00_老板投资说明书.md"
    existing_updates = ""
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if "## 更新记录" in old:
            existing_updates = old.split("## 更新记录", 1)[1].strip()
    join = lambda values: "、".join(values) if values else "待确认"
    body = f"""# 老板投资说明书

> 这里只记录老板明确确认过的长期偏好。网页与 Codex 共用此文件和本地数据库。

## 基本信息

- 称呼：{profile.get("owner_name") or "老板"}
- 重点市场：{join(profile.get("primary_markets", []))}
- 参考市场：{join(profile.get("reference_markets", []))}
- 分析顺序：{profile.get("analysis_framework") or "待确认"}
- 参考投资框架：{join(profile.get("reference_investors", []))}
- 投资周期：{profile.get("investment_horizon") or "待确认"}
- 报告偏好：{profile.get("report_style") or "待确认"}

## 研究偏好

- 重点板块：{join(profile.get("focus_sectors", []))}
- 常用指标：{join(profile.get("preferred_metrics", []))}
- 排除行业：{join(profile.get("excluded_sectors", []))}
- 风险偏好：{profile.get("risk_preference") or "待确认"}

## 数据与交易边界

- 允许使用的数据：{join(profile.get("data_permissions", []))}
- 隐私边界：{join(profile.get("privacy_boundaries", []))}
- 不连接证券账户，不自动下单，不输出个性化交易指令

## 更新记录

{existing_updates}
"""
    path.write_text(body, encoding="utf-8")


def _write_watchlist_markdown() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    path = WORKSPACE_DIR / "01_自选公司.md"
    rows = list_watchlist()
    lines = [
        "# 自选公司",
        "",
        "网页与 Codex 共用此清单。",
        "",
        "| 公司 | 代码 | 市场 | 加入日期 | 最初研究理由 | 状态 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in rows:
        clean = lambda value: str(value or "").replace("|", "／").replace("\n", " ")
        lines.append(
            f"| {clean(item['name'])} | {clean(item['symbol'])} | {clean(item['market'])} | "
            f"{clean(item['created_at'][:10])} | {clean(item['thesis'])} | "
            f"{clean(item['tracking_frequency']) if item['tracking_enabled'] else '手动研究'} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def create_conversation(
    title: str,
    source: str = "web",
    conversation_id: str | None = None,
    *,
    watchlist_id: int | None = None,
) -> dict[str, Any]:
    conversation_id = conversation_id or uuid.uuid4().hex
    now = _now()
    with connection() as conn:
        conn.execute(
            """INSERT INTO conversations(
                   id, title, source, status, watchlist_id, created_at, updated_at
               ) VALUES (?, ?, ?, 'active', ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   title=CASE WHEN conversations.title='' THEN excluded.title ELSE conversations.title END,
                   watchlist_id=COALESCE(conversations.watchlist_id, excluded.watchlist_id),
                   updated_at=excluded.updated_at""",
            (conversation_id, title.strip()[:100] or "新对话", source, watchlist_id, now, now),
        )
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    result = dict(row)
    _export_conversation(conversation_id)
    return result


def upsert_external_conversation(
    conversation_id: str,
    title: str,
    *,
    source: str,
    created_at: str,
    updated_at: str,
    status: str = "active",
) -> dict[str, Any]:
    with connection() as conn:
        conn.execute(
            """INSERT INTO conversations(id, title, source, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   title=excluded.title,
                   source=excluded.source,
                   status=excluded.status,
                   updated_at=excluded.updated_at""",
            (
                conversation_id,
                title.strip()[:100] or "Codex 投研对话",
                source,
                status,
                created_at,
                updated_at,
            ),
        )
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    return dict(row)


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    sources: list[dict[str, str]] | None = None,
    model: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now()
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
            raise KeyError("conversation_not_found")
        cursor = conn.execute(
            """INSERT INTO messages(
                   conversation_id, role, content, sources_json, model, metadata_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                conversation_id,
                role,
                content,
                json.dumps(align_sources_with_content(sources, content), ensure_ascii=False),
                model,
                json.dumps(metadata or {}, ensure_ascii=False),
                now,
            ),
        )
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
        if role == "user":
            row = conn.execute("SELECT title FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if row and row["title"] in {"新对话", "Codex 对话"}:
                title = re.sub(r"\s+", " ", content).strip()[:38] or row["title"]
                conn.execute("UPDATE conversations SET title=? WHERE id=?", (title, conversation_id))
        row = conn.execute("SELECT * FROM messages WHERE id=?", (cursor.lastrowid,)).fetchone()
    result = _message_row(row)
    _export_conversation(conversation_id)
    return result


def upsert_external_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    external_id: str,
    created_at: str,
    sources: list[dict[str, str]] | None = None,
    model: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert a synced message once and update it if Codex later finalizes it."""

    with connection() as conn:
        existing = conn.execute(
            "SELECT id FROM messages WHERE external_id=?",
            (external_id,),
        ).fetchone()
        conn.execute(
            """INSERT INTO messages(
                   conversation_id, role, content, external_id, sources_json,
                   model, metadata_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(external_id) WHERE external_id != '' DO UPDATE SET
                   role=excluded.role,
                   content=excluded.content,
                   sources_json=excluded.sources_json,
                   model=excluded.model,
                   metadata_json=excluded.metadata_json,
                   created_at=excluded.created_at""",
            (
                conversation_id,
                role,
                content,
                external_id,
                json.dumps(align_sources_with_content(sources, content), ensure_ascii=False),
                model,
                json.dumps(metadata or {}, ensure_ascii=False),
                created_at,
            ),
        )
        conn.execute(
            """UPDATE conversations
               SET updated_at=CASE WHEN updated_at < ? THEN ? ELSE updated_at END
               WHERE id=?""",
            (created_at, created_at, conversation_id),
        )
        row = conn.execute(
            "SELECT * FROM messages WHERE external_id=?",
            (external_id,),
        ).fetchone()
    result = _message_row(row)
    _export_conversation(conversation_id)
    return result, existing is None


def list_conversations(
    limit: int = 50,
    offset: int = 0,
    *,
    query: str = "",
    source: str = "",
    watchlist_id: int | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    visible_message = (
        "COALESCE(json_extract({alias}.metadata_json, '$.error'), 0)=0 "
        "AND COALESCE(json_extract({alias}.metadata_json, '$.cancelled'), 0)=0"
    )
    clauses: list[str] = [
        """NOT (
            c.source='scheduler'
            AND EXISTS (
                SELECT 1 FROM messages mf
                WHERE mf.conversation_id=c.id
                  AND COALESCE(json_extract(mf.metadata_json, '$.error'), 0)=1
            )
            AND NOT EXISTS (
                SELECT 1 FROM messages ms
                WHERE ms.conversation_id=c.id
                  AND json_extract(ms.metadata_json, '$.report_id') IS NOT NULL
            )
        )"""
    ]
    values: list[Any] = []
    if query:
        clauses.append(
            f"""(c.title LIKE ? OR EXISTS (
                SELECT 1 FROM messages m2
                WHERE m2.conversation_id=c.id
                  AND {visible_message.format(alias="m2")}
                  AND m2.content LIKE ?
            ))"""
        )
        needle = f"%{query}%"
        values.extend([needle, needle])
    if source:
        clauses.append("c.source=?")
        values.append(source)
    if watchlist_id is not None:
        clauses.append("c.watchlist_id=?")
        values.append(watchlist_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.extend([limit, offset])
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT c.*,
                       COUNT(CASE WHEN {visible_message.format(alias="m")}
                                  THEN m.id END) AS message_count,
                       COALESCE((
                           SELECT substr(m3.content, 1, 160)
                           FROM messages m3
                           WHERE m3.conversation_id=c.id
                             AND {visible_message.format(alias="m3")}
                           ORDER BY m3.id DESC LIMIT 1
                       ), '') AS preview
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id=c.id
                {where}
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                LIMIT ? OFFSET ?""",
            values,
        ).fetchall()
    return [dict(row) for row in rows]


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT c.*, w.name AS company_name, w.symbol AS company_symbol, w.market AS company_market
               FROM conversations c
               LEFT JOIN watchlist w ON w.id=c.watchlist_id
               WHERE c.id=?""",
            (conversation_id,),
        ).fetchone()
        if not row:
            return None
        messages = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    result = dict(row)
    parsed_messages = [_message_row(message) for message in messages]
    result["messages"] = [
        message
        for message in parsed_messages
        if not message["metadata"].get("error")
        and not message["metadata"].get("cancelled")
    ]
    return result


def conversation_has_active_task(conversation_id: str) -> bool:
    with connection() as conn:
        active_run = conn.execute(
            """SELECT 1 FROM job_runs
               WHERE status='running' AND conversation_id=? LIMIT 1""",
            (conversation_id,),
        ).fetchone()
        if active_run:
            return True
        rows = conn.execute(
            """SELECT request_json FROM research_tasks
               WHERE status IN ('queued', 'running') AND task_type='conversation'"""
        ).fetchall()
    for row in rows:
        try:
            request = json.loads(row["request_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if str(request.get("conversation_id") or "") == conversation_id:
            return True
    return False


def delete_conversation(conversation_id: str) -> bool:
    with connection() as conn:
        conn.execute(
            "UPDATE job_runs SET conversation_id=NULL WHERE conversation_id=?",
            (conversation_id,),
        )
        cursor = conn.execute(
            "DELETE FROM conversations WHERE id=?",
            (conversation_id,),
        )
    if cursor.rowcount < 1:
        return False
    root = CONVERSATIONS_DIR.resolve()
    for path in CONVERSATIONS_DIR.glob(f"{conversation_id}_*.md"):
        try:
            resolved = path.resolve()
            if root in resolved.parents:
                resolved.unlink(missing_ok=True)
        except OSError:
            continue
    return True


def _export_conversation(conversation_id: str) -> Path | None:
    conversation = get_conversation(conversation_id)
    if not conversation:
        return None
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", conversation["title"]).strip("-")[:55]
    safe_title = safe_title or "conversation"
    path = CONVERSATIONS_DIR / f"{conversation_id}_{safe_title}.md"
    for stale in CONVERSATIONS_DIR.glob(f"{conversation_id}_*.md"):
        if stale != path:
            stale.unlink(missing_ok=True)
    company_line = (
        f"- 关联公司：{conversation.get('company_name')} "
        f"（{conversation.get('company_market')} · {conversation.get('company_symbol')}）\n"
        if conversation.get("watchlist_id")
        else ""
    )
    blocks = [
        f"# {conversation['title']}",
        "",
        f"- 对话来源：{conversation['source']}",
        company_line.rstrip(),
        f"- 创建时间：{conversation['created_at']}",
        f"- 最后更新：{conversation['updated_at']}",
        "",
    ]
    for message in conversation["messages"]:
        role = "老板" if message["role"] == "user" else "AI 投研员工"
        blocks.extend(
            [
                f"## {role} · {message['created_at']}",
                "",
                message["content"].strip(),
                "",
            ]
        )
    path.write_text("\n".join(part for part in blocks if part is not None), encoding="utf-8")
    return path


def _message_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["sources"] = align_sources_with_content(
        json.loads(result.pop("sources_json") or "[]"),
        result["content"],
    )
    result["source_audit"] = audit_sources(result["sources"], result["content"])
    result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
    return result


def memory_counts() -> dict[str, Any]:
    with connection() as conn:
        totals = conn.execute(
            """SELECT
                   (SELECT COUNT(*) FROM conversations) AS conversations,
                   (SELECT COUNT(*) FROM messages) AS messages,
                   (SELECT COUNT(*) FROM reports) AS reports,
                   (SELECT COUNT(*) FROM research_hypotheses) AS hypotheses,
                   (SELECT COUNT(*) FROM watchlist) AS watchlist"""
        ).fetchone()
        sources = conn.execute(
            "SELECT source, COUNT(*) AS count FROM conversations GROUP BY source"
        ).fetchall()
        latest = conn.execute(
            """SELECT m.role, m.content, m.created_at, c.source
               FROM messages m JOIN conversations c ON c.id=m.conversation_id
               WHERE COALESCE(json_extract(m.metadata_json, '$.error'), 0)=0
                 AND COALESCE(json_extract(m.metadata_json, '$.cancelled'), 0)=0
               ORDER BY m.id DESC LIMIT 6"""
        ).fetchall()
    result = dict(totals)
    result["by_source"] = {row["source"]: row["count"] for row in sources}
    result["latest"] = [dict(row) for row in latest]
    return result


def memory_candidates(
    limit: int = 600,
    *,
    terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search the full archive, then add recent context for lightweight retrieval."""

    limit = max(20, min(limit, 2000))
    search_terms = [term for term in (terms or []) if term][:12]
    visible_archive = """
        COALESCE(json_extract(m.metadata_json, '$.error'), 0)=0
        AND COALESCE(json_extract(m.metadata_json, '$.cancelled'), 0)=0
        AND NOT (
            c.source='scheduler'
            AND EXISTS (
                SELECT 1 FROM messages mf
                WHERE mf.conversation_id=c.id
                  AND COALESCE(json_extract(mf.metadata_json, '$.error'), 0)=1
            )
            AND NOT EXISTS (
                SELECT 1 FROM messages ms
                WHERE ms.conversation_id=c.id
                  AND json_extract(ms.metadata_json, '$.report_id') IS NOT NULL
            )
        )
    """
    with connection() as conn:
        recent_messages = conn.execute(
            f"""SELECT 'message' AS kind, m.id, m.role, m.content, m.created_at,
                      c.source, c.title
               FROM messages m JOIN conversations c ON c.id=m.conversation_id
               WHERE {visible_archive}
               ORDER BY m.id DESC LIMIT ?""",
            (min(limit // 5, 120),),
        ).fetchall()
        recent_reports = conn.execute(
            """SELECT 'report' AS kind, id, 'assistant' AS role, content, created_at,
                      source, title
               FROM reports ORDER BY id DESC LIMIT ?""",
            (min(limit // 10, 60),),
        ).fetchall()
        matched_messages: list[sqlite3.Row] = []
        matched_reports: list[sqlite3.Row] = []
        if search_terms:
            message_where = " OR ".join("(m.content LIKE ? OR c.title LIKE ?)" for _ in search_terms)
            report_where = " OR ".join("(content LIKE ? OR title LIKE ?)" for _ in search_terms)
            values = [value for term in search_terms for value in (f"%{term}%", f"%{term}%")]
            matched_messages = conn.execute(
                    f"""SELECT 'message' AS kind, m.id, m.role, m.content, m.created_at,
                           c.source, c.title
                    FROM messages m JOIN conversations c ON c.id=m.conversation_id
                    WHERE {visible_archive} AND ({message_where})
                    ORDER BY m.id DESC LIMIT ?""",
                [*values, limit],
            ).fetchall()
            matched_reports = conn.execute(
                f"""SELECT 'report' AS kind, id, 'assistant' AS role, content, created_at,
                           source, title
                    FROM reports
                    WHERE {report_where}
                    ORDER BY id DESC LIMIT ?""",
                [*values, min(limit // 2, 500)],
            ).fetchall()

    merged: dict[tuple[str, int], dict[str, Any]] = {}
    for row in [*matched_messages, *matched_reports, *recent_messages, *recent_reports]:
        item = dict(row)
        merged[(item["kind"], item["id"])] = item
    return list(merged.values())


def save_report(
    report_type: str,
    title: str,
    query: str,
    content: str,
    sources: list[dict[str, str]],
    model: str,
    engine: str = "api",
    *,
    conversation_id: str | None = None,
    job_run_id: int | None = None,
    source: str = "web",
    watchlist_id: int | None = None,
    review_mode: str = "single",
) -> dict[str, Any]:
    now = _now()
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO reports(
                   report_type, title, query, content, sources_json, model, engine, review_mode, created_at,
                   conversation_id, job_run_id, source, watchlist_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_type,
                title,
                query,
                content,
                json.dumps(align_sources_with_content(sources, content), ensure_ascii=False),
                model,
                engine,
                review_mode,
                now,
                conversation_id,
                job_run_id,
                source,
                watchlist_id,
            ),
        )
        row = conn.execute("SELECT * FROM reports WHERE id=?", (cursor.lastrowid,)).fetchone()
    result = _report_row(row)
    path = _export_report(result)
    with connection() as conn:
        conn.execute("UPDATE reports SET file_path=? WHERE id=?", (str(path), result["id"]))
    return get_report(result["id"]) or result


def _export_report(report: dict[str, Any]) -> Path:
    folder_map = {
        "daily": "daily",
        "company": "company",
        "qa": "questions",
        "review": "reviews",
        "hourly": "scheduled",
        "weekly": "scheduled",
        "scheduled": "scheduled",
    }
    folder = REPORTS_DIR / folder_map.get(report["report_type"], "scheduled")
    folder.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", report["title"]).strip("-")[:55] or "report"
    stamp = report["created_at"].replace(":", "").replace("+", "-").replace("T", "_")
    path = folder / f"{stamp}_{report['id']}_{safe_title}.md"
    source_lines = "\n".join(
        f"- **{item.get('quality_label') or '待核验'}｜"
        f"{item.get('citation_role') or '检索参考'}** "
        f"[{item.get('title') or '来源'}]({item.get('url')})"
        f"（{item.get('publisher') or item.get('domain') or '未知机构'}）"
        for item in report.get("sources", [])
        if item.get("url")
    )
    audit = report.get("source_audit") or audit_sources(
        report.get("sources", []),
        report.get("content", ""),
    )
    warning_lines = "\n".join(f"- {item}" for item in audit.get("warnings", []))
    body = (
        f"# {report['title']}\n\n"
        f"- 生成时间：{report['created_at']}\n"
        f"- 类型：{report['report_type']}\n"
        f"- 来源入口：{report.get('source', 'web')}\n"
        f"- 研究引擎：{report.get('engine', 'api')}\n"
        f"- 复核方式：{'事实核验员 + 反方研究员' if report.get('review_mode') == 'team' else '主研究员单独完成'}\n"
        f"- 模型：{report.get('model') or '未记录'}\n\n"
        f"{report['content'].strip()}\n\n"
        f"## 证据质量\n\n"
        f"- 结论：{audit.get('coverage_label', '尚未审计')}\n"
        f"- 一手来源：{audit.get('primary_count', 0)} / {audit.get('total', 0)}\n"
        f"- 正文引用：{audit.get('cited_count', 0)}\n"
        f"- 独立域名：{audit.get('unique_domains', 0)}\n"
        f"- 数字事实同行引用：{audit.get('cited_numeric_claim_count', 0)} / "
        f"{audit.get('numeric_claim_count', 0)}\n"
        f"{warning_lines}\n\n"
        f"## 来源清单\n\n{source_lines or '- 本报告没有联网来源。'}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def list_reports(
    limit: int = 30,
    report_type: str | None = None,
    *,
    watchlist_id: int | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    with connection() as conn:
        if report_type and watchlist_id is not None:
            rows = conn.execute(
                """SELECT * FROM reports
                   WHERE report_type=? AND watchlist_id=?
                   ORDER BY id DESC LIMIT ?""",
                (report_type, watchlist_id, limit),
            ).fetchall()
        elif report_type:
            rows = conn.execute(
                "SELECT * FROM reports WHERE report_type=? ORDER BY id DESC LIMIT ?",
                (report_type, limit),
            ).fetchall()
        elif watchlist_id is not None:
            rows = conn.execute(
                "SELECT * FROM reports WHERE watchlist_id=? ORDER BY id DESC LIMIT ?",
                (watchlist_id, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_report_row(row) for row in rows]


def get_report(report_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    return _report_row(row) if row else None


def delete_report(report_id: int) -> bool:
    report = get_report(report_id)
    if not report:
        return False
    with connection() as conn:
        cursor = conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
    if cursor.rowcount < 1:
        return False
    candidates: list[Path] = []
    if report.get("file_path"):
        candidates.append(Path(report["file_path"]))
    candidates.extend(REPORTS_DIR.rglob(f"*_{report_id}_*.md"))
    root = REPORTS_DIR.resolve()
    for path in candidates:
        try:
            resolved = path.resolve()
            if root in resolved.parents:
                resolved.unlink(missing_ok=True)
        except OSError:
            continue
    return True


def _report_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["sources"] = align_sources_with_content(
        json.loads(result.pop("sources_json") or "[]"),
        result["content"],
    )
    result["source_audit"] = audit_sources(result["sources"], result["content"])
    return result


def create_hypothesis(item: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO research_hypotheses(
                   watchlist_id, title, statement, status, support_json, counter_json,
                   validation_json, invalidation_json, next_review_at, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(item["watchlist_id"]),
                str(item["title"]).strip(),
                str(item.get("statement", "")).strip(),
                str(item.get("status", "tracking")),
                json.dumps(item.get("support_evidence", []), ensure_ascii=False),
                json.dumps(item.get("counter_evidence", []), ensure_ascii=False),
                json.dumps(item.get("validation_signals", []), ensure_ascii=False),
                json.dumps(item.get("invalidation_signals", []), ensure_ascii=False),
                str(item.get("next_review_at", "")).strip(),
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM research_hypotheses WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()
    return get_hypothesis(int(row["id"])) or _hypothesis_row(row)


def list_hypotheses(
    *,
    watchlist_id: int | None = None,
    status: str = "",
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if watchlist_id is not None:
        clauses.append("h.watchlist_id=?")
        values.append(watchlist_id)
    if status:
        clauses.append("h.status=?")
        values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT h.*, w.name AS company_name, w.symbol AS company_symbol,
                       w.market AS company_market
                FROM research_hypotheses h
                JOIN watchlist w ON w.id=h.watchlist_id
                {where}
                ORDER BY
                    CASE h.status
                        WHEN 'tracking' THEN 0
                        WHEN 'challenged' THEN 1
                        WHEN 'supported' THEN 2
                        WHEN 'invalidated' THEN 3
                        ELSE 4
                    END,
                    h.updated_at DESC""",
            values,
        ).fetchall()
    return [_hypothesis_row(row) for row in rows]


def get_hypothesis(hypothesis_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT h.*, w.name AS company_name, w.symbol AS company_symbol,
                      w.market AS company_market
               FROM research_hypotheses h
               JOIN watchlist w ON w.id=h.watchlist_id
               WHERE h.id=?""",
            (hypothesis_id,),
        ).fetchone()
    return _hypothesis_row(row) if row else None


def update_hypothesis(hypothesis_id: int, item: dict[str, Any]) -> dict[str, Any] | None:
    existing = get_hypothesis(hypothesis_id)
    if not existing:
        return None
    merged = {**existing, **item}
    with connection() as conn:
        conn.execute(
            """UPDATE research_hypotheses
               SET title=?, statement=?, status=?, support_json=?, counter_json=?,
                   validation_json=?, invalidation_json=?, next_review_at=?, updated_at=?
               WHERE id=?""",
            (
                str(merged["title"]).strip(),
                str(merged.get("statement", "")).strip(),
                str(merged.get("status", "tracking")),
                json.dumps(merged.get("support_evidence", []), ensure_ascii=False),
                json.dumps(merged.get("counter_evidence", []), ensure_ascii=False),
                json.dumps(merged.get("validation_signals", []), ensure_ascii=False),
                json.dumps(merged.get("invalidation_signals", []), ensure_ascii=False),
                str(merged.get("next_review_at", "")).strip(),
                _now(),
                hypothesis_id,
            ),
        )
    return get_hypothesis(hypothesis_id)


def delete_hypothesis(hypothesis_id: int) -> bool:
    with connection() as conn:
        cursor = conn.execute(
            "DELETE FROM research_hypotheses WHERE id=?",
            (hypothesis_id,),
        )
    return cursor.rowcount > 0


def _hypothesis_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["support_evidence"] = json.loads(result.pop("support_json") or "[]")
    result["counter_evidence"] = json.loads(result.pop("counter_json") or "[]")
    result["validation_signals"] = json.loads(result.pop("validation_json") or "[]")
    result["invalidation_signals"] = json.loads(result.pop("invalidation_json") or "[]")
    return result


def get_company_workspace(item_id: int) -> dict[str, Any] | None:
    company = get_watchlist(item_id)
    if not company:
        return None
    reports = list_reports(200, watchlist_id=item_id)
    conversations = list_conversations(200, watchlist_id=item_id)
    tracking_job = get_company_tracking_job(item_id)
    return {
        "company": company,
        "reports": reports,
        "conversations": conversations,
        "hypotheses": list_hypotheses(watchlist_id=item_id),
        "tracking_job": tracking_job,
        "collection_plan": build_collection_plan(
            [company["market"]],
            company=company["name"],
            symbol=company["symbol"],
        ),
    }


def _insert_job(conn: sqlite3.Connection, job: dict[str, Any]) -> int:
    now = datetime.now().astimezone()
    next_run = calculate_next_run(job, now).isoformat(timespec="seconds")
    cursor = conn.execute(
        """INSERT INTO scheduled_jobs(
               name, job_type, frequency, interval_minutes, time_of_day, weekday,
               active_start, active_end, enabled, engine, frameworks_json, watchlist_id,
               day_of_month, month_of_year, prompt, last_run_at, next_run_at,
               created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)""",
        (
            job["name"],
            job["job_type"],
            job["frequency"],
            int(job.get("interval_minutes", 60)),
            job.get("time_of_day", "08:00"),
            int(job.get("weekday", 0)),
            job.get("active_start", "00:00"),
            job.get("active_end", "23:59"),
            1 if job.get("enabled") else 0,
            job.get("engine", "auto"),
            json.dumps(job.get("frameworks", []), ensure_ascii=False),
            job.get("watchlist_id"),
            int(job.get("day_of_month", 1)),
            int(job.get("month_of_year", 1)),
            job.get("prompt", ""),
            next_run,
            now.isoformat(timespec="seconds"),
            now.isoformat(timespec="seconds"),
        ),
    )
    return int(cursor.lastrowid)


def list_jobs() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT j.*,
                      (SELECT status FROM job_runs r WHERE r.job_id=j.id ORDER BY r.id DESC LIMIT 1)
                          AS last_status,
                      (SELECT error FROM job_runs r WHERE r.job_id=j.id ORDER BY r.id DESC LIMIT 1)
                          AS last_error,
                      (SELECT trigger_type FROM job_runs r WHERE r.job_id=j.id ORDER BY r.id DESC LIMIT 1)
                          AS last_trigger_type,
                      (SELECT scheduled_for FROM job_runs r WHERE r.job_id=j.id ORDER BY r.id DESC LIMIT 1)
                          AS last_scheduled_for,
                      (SELECT attempt_count FROM job_runs r WHERE r.job_id=j.id ORDER BY r.id DESC LIMIT 1)
                          AS last_attempt_count
               FROM scheduled_jobs j ORDER BY j.id"""
        ).fetchall()
    return [_job_row(row) for row in rows]


def get_job(job_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)).fetchone()
    return _job_row(row) if row else None


def save_job(job_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    current = get_job(job_id)
    if not current:
        return None
    merged = {**current, **payload}
    now = datetime.now().astimezone()
    next_run = calculate_next_run(merged, now).isoformat(timespec="seconds")
    with connection() as conn:
        conn.execute(
            """UPDATE scheduled_jobs SET
                   name=?, job_type=?, frequency=?, interval_minutes=?, time_of_day=?, weekday=?,
                   active_start=?, active_end=?, enabled=?, engine=?, frameworks_json=?,
                   watchlist_id=?, day_of_month=?, month_of_year=?,
                   prompt=?, next_run_at=?, updated_at=?
               WHERE id=?""",
            (
                merged["name"],
                merged["job_type"],
                merged["frequency"],
                int(merged["interval_minutes"]),
                merged["time_of_day"],
                int(merged["weekday"]),
                merged["active_start"],
                merged["active_end"],
                1 if merged["enabled"] else 0,
                merged.get("engine", "auto"),
                json.dumps(merged.get("frameworks", []), ensure_ascii=False),
                merged.get("watchlist_id"),
                int(merged.get("day_of_month", 1)),
                int(merged.get("month_of_year", 1)),
                merged["prompt"],
                next_run,
                now.isoformat(timespec="seconds"),
                job_id,
            ),
        )
    return get_job(job_id)


def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    with connection() as conn:
        job_id = _insert_job(conn, payload)
    return get_job(job_id) or {}


def delete_job(job_id: int) -> bool:
    with connection() as conn:
        cursor = conn.execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))
    return cursor.rowcount > 0


def get_company_tracking_job(watchlist_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT * FROM scheduled_jobs
               WHERE watchlist_id=? AND job_type='company_tracking'
               ORDER BY id DESC LIMIT 1""",
            (watchlist_id,),
        ).fetchone()
    return _job_row(row) if row else None


def list_due_jobs(now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now().astimezone()
    with connection() as conn:
        rows = conn.execute(
            """SELECT * FROM scheduled_jobs
               WHERE enabled=1 AND next_run_at!='' AND next_run_at<=?
               ORDER BY next_run_at""",
            (now.isoformat(timespec="seconds"),),
        ).fetchall()
    return [_job_row(row) for row in rows]


def _job_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    result["frameworks"] = json.loads(result.pop("frameworks_json", "[]") or "[]")
    return result


def create_research_task(task_type: str, title: str, request: dict[str, Any]) -> dict[str, Any]:
    task_id = str(uuid.uuid4())
    with connection() as conn:
        conn.execute(
            """INSERT INTO research_tasks(id, task_type, title, status, request_json, created_at)
               VALUES (?, ?, ?, 'queued', ?, ?)""",
            (task_id, task_type, title[:120], json.dumps(request, ensure_ascii=False), _now()),
        )
    return get_research_task(task_id) or {}


def start_research_task(task_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE research_tasks SET status='running', started_at=?, error='' WHERE id=?",
            (_now(), task_id),
        )


def finish_research_task(
    task_id: str,
    *,
    status: str,
    report_id: int | None = None,
    error: str = "",
) -> None:
    with connection() as conn:
        conn.execute(
            """UPDATE research_tasks
               SET status=?, report_id=?, error=?, finished_at=?
               WHERE id=?""",
            (status, report_id, error[:1000], _now(), task_id),
        )


def get_research_task(task_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM research_tasks WHERE id=?", (task_id,)).fetchone()
    return _research_task_row(row) if row else None


def list_research_tasks(limit: int = 30) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM research_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_research_task_row(row) for row in rows]


def _research_task_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["request"] = json.loads(result.pop("request_json") or "{}")
    return result


def create_job_run(
    job_id: int,
    conversation_id: str,
    *,
    trigger_type: str = "manual",
) -> int:
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO job_runs(
                   job_id, status, trigger_type, scheduled_for, attempt_count,
                   started_at, conversation_id
               ) VALUES (?, 'running', ?, '', 1, ?, ?)""",
            (job_id, trigger_type, _now(), conversation_id),
        )
    return int(cursor.lastrowid)


def claim_due_job(job_id: int, now: datetime | None = None) -> int | None:
    """Atomically reserve one due schedule and move the job to its next occurrence."""
    local_now = (now or datetime.now().astimezone()).astimezone()
    now_text = local_now.isoformat(timespec="seconds")
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM scheduled_jobs
               WHERE id=? AND enabled=1 AND next_run_at!='' AND next_run_at<=?""",
            (job_id, now_text),
        ).fetchone()
        if not row:
            return None

        job = _job_row(row)
        scheduled_for = str(job["next_run_at"])
        existing = conn.execute(
            """SELECT id, status FROM job_runs
               WHERE job_id=? AND trigger_type='scheduled' AND scheduled_for=?""",
            (job_id, scheduled_for),
        ).fetchone()
        if existing:
            if existing["status"] != "interrupted":
                return None
            run_id = int(existing["id"])
            conn.execute(
                """UPDATE job_runs
                   SET status='running', started_at=?, finished_at='', report_id=NULL,
                       conversation_id=NULL, error='', attempt_count=attempt_count+1
                   WHERE id=?""",
                (now_text, run_id),
            )
        else:
            cursor = conn.execute(
                """INSERT INTO job_runs(
                       job_id, status, trigger_type, scheduled_for, attempt_count, started_at
                   ) VALUES (?, 'running', 'scheduled', ?, 1, ?)""",
                (job_id, scheduled_for, now_text),
            )
            run_id = int(cursor.lastrowid)

        next_run = calculate_next_run(job, local_now + timedelta(seconds=1))
        conn.execute(
            """UPDATE scheduled_jobs SET next_run_at=?, updated_at=? WHERE id=?""",
            (next_run.isoformat(timespec="seconds"), now_text, job_id),
        )
    return run_id


def attach_job_run_conversation(run_id: int, conversation_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE job_runs SET conversation_id=? WHERE id=?",
            (conversation_id, run_id),
        )


def increment_job_run_attempt(run_id: int) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE job_runs SET attempt_count=attempt_count+1 WHERE id=?",
            (run_id,),
        )


def list_job_runs(job_id: int, limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with connection() as conn:
        rows = conn.execute(
            """SELECT * FROM job_runs
               WHERE job_id=? ORDER BY id DESC LIMIT ?""",
            (job_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def finish_job_run(
    run_id: int,
    *,
    status: str,
    report_id: int | None = None,
    error: str = "",
) -> None:
    with connection() as conn:
        row = conn.execute("SELECT job_id FROM job_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return
        finished = datetime.now().astimezone()
        conn.execute(
            """UPDATE job_runs SET status=?, finished_at=?, report_id=?, error=? WHERE id=?""",
            (status, finished.isoformat(timespec="seconds"), report_id, error[:1000], run_id),
        )
        conn.execute(
            """UPDATE scheduled_jobs SET last_run_at=?, updated_at=? WHERE id=?""",
            (
                finished.isoformat(timespec="seconds"),
                finished.isoformat(timespec="seconds"),
                row["job_id"],
            ),
        )


def calculate_next_run(job: dict[str, Any], after: datetime) -> datetime:
    local = after.astimezone()
    frequency = job.get("frequency", "interval")
    if frequency == "interval":
        candidate = local + timedelta(minutes=max(15, int(job.get("interval_minutes", 60))))
        return _move_into_active_window(candidate, job)

    hour, minute = (int(part) for part in job.get("time_of_day", "08:00").split(":"))
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if frequency == "daily":
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate

    if frequency == "monthly":
        day = max(1, min(28, int(job.get("day_of_month", 1))))
        candidate = local.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local:
            year = local.year + (1 if local.month == 12 else 0)
            month = 1 if local.month == 12 else local.month + 1
            candidate = candidate.replace(year=year, month=month, day=min(day, monthrange(year, month)[1]))
        return candidate

    if frequency == "yearly":
        month = max(1, min(12, int(job.get("month_of_year", 1))))
        day = max(1, min(28, int(job.get("day_of_month", 1))))
        candidate = local.replace(
            month=month,
            day=min(day, monthrange(local.year, month)[1]),
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate <= local:
            candidate = candidate.replace(year=local.year + 1)
        return candidate

    target_weekday = int(job.get("weekday", 0))
    if target_weekday == -1:
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate
    days = (target_weekday - local.weekday()) % 7
    candidate += timedelta(days=days)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate


def _move_into_active_window(candidate: datetime, job: dict[str, Any]) -> datetime:
    start_hour, start_minute = (int(part) for part in job.get("active_start", "00:00").split(":"))
    end_hour, end_minute = (int(part) for part in job.get("active_end", "23:59").split(":"))
    minutes = candidate.hour * 60 + candidate.minute
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if start <= minutes <= end:
        return candidate
    if minutes < start:
        return candidate.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    tomorrow = candidate + timedelta(days=1)
    return tomorrow.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
