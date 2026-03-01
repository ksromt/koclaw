"""
Scheduler tool definitions for Koclaw Agent.

These tools are presented to the LLM alongside MCP tools but are intercepted
by the bridge and routed as scheduler_request messages to the Gateway.
"""

SCHEDULER_TOOLS: list[dict] = [
    {
        "name": "scheduler_create_job",
        "description": (
            "Create a timed reminder or recurring job. "
            "Use this when the user asks to be reminded of something, "
            "wants a scheduled notification, or needs a recurring task. "
            "For reminders like '10\u5206\u5f8c\u306bXX\u3092\u601d\u3044\u51fa\u3055\u305b\u3066', use delay_seconds. "
            "For daily/weekly schedules like '\u6bce\u671d9\u6642\u306b\u5929\u6c17\u3092\u6559\u3048\u3066', use cron."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "What to remind or do when the job fires",
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": (
                        "Relative delay in seconds (for one-shot reminders). "
                        "E.g., 600 for 10 minutes."
                    ),
                },
                "cron": {
                    "type": "string",
                    "description": (
                        "5-field cron expression for recurring jobs. "
                        "E.g., '0 9 * * *' for daily at 9 AM."
                    ),
                },
                "timezone": {
                    "type": "string",
                    "description": (
                        "IANA timezone for cron jobs. "
                        "Default: user's detected timezone."
                    ),
                },
                "one_shot": {
                    "type": "boolean",
                    "description": (
                        "If true, job is deleted after firing once. "
                        "Default: true for delay_seconds, false for cron."
                    ),
                },
            },
            "required": ["message"],
        },
        "_mcp_server": "_scheduler",
    },
    {
        "name": "scheduler_list_jobs",
        "description": (
            "List active scheduled jobs/reminders for the current user. "
            "Use when the user asks '\u30ea\u30de\u30a4\u30f3\u30c0\u30fc\u4e00\u89a7' or 'what reminders do I have'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_mcp_server": "_scheduler",
    },
    {
        "name": "scheduler_delete_job",
        "description": (
            "Cancel/delete a scheduled job by its ID. "
            "Use when the user wants to cancel a reminder or recurring job."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The job ID to delete (8-character hex string)",
                },
            },
            "required": ["job_id"],
        },
        "_mcp_server": "_scheduler",
    },
]


def is_scheduler_tool(tool_name: str) -> bool:
    """Check if a tool name is a scheduler pseudo-tool."""
    return tool_name.startswith("scheduler_")
