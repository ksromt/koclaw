"""
Calendar tool definitions for Koclaw Agent.

These tools are presented to the LLM alongside MCP tools but are intercepted
by the bridge and routed to the local CalendarStore.
"""

CALENDAR_TOOLS: list[dict] = [
    {
        "name": "calendar_add_event",
        "description": (
            "日程・予定をカレンダーに追加する。"
            "先生の予定、イベント、締切などを記録する時に使う。"
            "リマインダーが必要な場合は、追加後に scheduler_create_job で"
            "別途リマインダーを設定すること。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "予定のタイトル（例：研究室卒業祝賀会）",
                },
                "date": {
                    "type": "string",
                    "description": "日付（YYYY-MM-DD形式、例：2026-03-29）",
                },
                "time": {
                    "type": "string",
                    "description": "開始時刻（HH:MM形式、例：11:40）",
                },
                "end_time": {
                    "type": "string",
                    "description": "終了時刻（HH:MM形式、例：13:00）",
                },
                "location": {
                    "type": "string",
                    "description": "場所（例：研究室、オンライン）",
                },
                "notes": {
                    "type": "string",
                    "description": "備考・メモ",
                },
            },
            "required": ["title", "date"],
        },
        "_mcp_server": "_calendar",
    },
    {
        "name": "calendar_list_events",
        "description": (
            "日程・予定の一覧を取得する。"
            "日付範囲を指定して検索できる。"
            "デフォルトは今日以降の予定を表示。"
            "「今週の予定は？」「明日は何がある？」などに使う。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_date": {
                    "type": "string",
                    "description": (
                        "検索開始日（YYYY-MM-DD）。省略時は今日。"
                    ),
                },
                "to_date": {
                    "type": "string",
                    "description": (
                        "検索終了日（YYYY-MM-DD）。省略時は制限なし。"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト10）",
                },
            },
        },
        "_mcp_server": "_calendar",
    },
    {
        "name": "calendar_update_event",
        "description": (
            "既存の日程・予定を更新する。"
            "日時、場所、タイトルなどを変更する時に使う。"
            "変更したいフィールドのみ指定すればOK。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "更新する予定のID（例：evt_20260329_001）",
                },
                "title": {
                    "type": "string",
                    "description": "新しいタイトル",
                },
                "date": {
                    "type": "string",
                    "description": "新しい日付（YYYY-MM-DD）",
                },
                "time": {
                    "type": "string",
                    "description": "新しい開始時刻（HH:MM）",
                },
                "end_time": {
                    "type": "string",
                    "description": "新しい終了時刻（HH:MM）",
                },
                "location": {
                    "type": "string",
                    "description": "新しい場所",
                },
                "notes": {
                    "type": "string",
                    "description": "新しい備考",
                },
            },
            "required": ["event_id"],
        },
        "_mcp_server": "_calendar",
    },
    {
        "name": "calendar_delete_event",
        "description": (
            "日程・予定を削除する。"
            "キャンセルされた予定や間違って追加した予定を削除する時に使う。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "削除する予定のID（例：evt_20260329_001）",
                },
            },
            "required": ["event_id"],
        },
        "_mcp_server": "_calendar",
    },
]


def is_calendar_tool(tool_name: str) -> bool:
    """Check if a tool name is a calendar pseudo-tool."""
    return tool_name.startswith("calendar_")
