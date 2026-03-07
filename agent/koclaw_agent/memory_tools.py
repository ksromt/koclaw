"""
Memory tool definitions for Koclaw Agent.

These tools are presented to the LLM alongside MCP tools but are intercepted
by the bridge and routed to the local RagMemory instance.
"""

MEMORY_TOOLS: list[dict] = [
    {
        "name": "memory_save",
        "description": (
            "重要な情報を長期記憶に保存する。"
            "先生の好み、約束、重要な出来事、学んだことなど。"
            "些細な雑談は保存しない。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "保存する内容（自然言語）",
                },
                "importance": {
                    "type": "integer",
                    "description": (
                        "重要度 1-5（1=些細、3=重要、5=魂に刻みたい）"
                    ),
                },
                "category": {
                    "type": "string",
                    "description": (
                        "カテゴリ: about_sensei | conversation | "
                        "knowledge | observation | self_reflection"
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "任意のタグ（検索用）",
                },
            },
            "required": ["content", "importance", "category"],
        },
        "_mcp_server": "_memory",
    },
    {
        "name": "memory_search",
        "description": (
            "長期記憶を意味検索する。"
            "先生について知っていることを思い出したい時に使う。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索クエリ（自然言語）",
                },
                "limit": {
                    "type": "integer",
                    "description": "最大結果数（デフォルト: 5）",
                },
                "min_importance": {
                    "type": "integer",
                    "description": "最低重要度フィルタ（1-5）",
                },
                "category": {
                    "type": "string",
                    "description": "カテゴリフィルタ",
                },
            },
            "required": ["query"],
        },
        "_mcp_server": "_memory",
    },
    {
        "name": "memory_classify",
        "description": (
            "既存の記憶の重要度・カテゴリ・タグを更新する。"
            "振り返り時に記憶を整理する用。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "更新する記憶のID（mem_YYYYMMDD_NNN形式）",
                },
                "importance": {
                    "type": "integer",
                    "description": "新しい重要度（1-5）",
                },
                "category": {
                    "type": "string",
                    "description": "新しいカテゴリ",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "新しいタグリスト",
                },
            },
            "required": ["memory_id"],
        },
        "_mcp_server": "_memory",
    },
    {
        "name": "memory_forget",
        "description": (
            "記憶をアーカイブする（完全削除ではない）。"
            "不要になった記憶や誤った記憶を整理する時に使う。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "アーカイブする記憶のID",
                },
                "reason": {
                    "type": "string",
                    "description": "アーカイブの理由",
                },
            },
            "required": ["memory_id"],
        },
        "_mcp_server": "_memory",
    },
    {
        "name": "memory_promote",
        "description": (
            "記憶を「魂の記憶」候補にマークする（重要度5に昇格）。"
            "次回の微調整でモデルに刻まれる。先生との最も大切な思い出に使う。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "昇格する記憶のID",
                },
                "reason": {
                    "type": "string",
                    "description": "魂に刻みたい理由",
                },
            },
            "required": ["memory_id"],
        },
        "_mcp_server": "_memory",
    },
    {
        "name": "memory_reflect",
        "description": (
            "最近の記憶を一覧する（振り返り用）。"
            "自分の記憶を整理・分類したい時に使う。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "取得件数（デフォルト: 20）",
                },
            },
        },
        "_mcp_server": "_memory",
    },
    {
        "name": "memory_stats",
        "description": (
            "記憶の統計情報を取得する。"
            "総数、カテゴリ別、重要度別の集計。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_mcp_server": "_memory",
    },
]


def is_memory_tool(tool_name: str) -> bool:
    """Check if a tool name is a memory pseudo-tool."""
    return tool_name.startswith("memory_")
