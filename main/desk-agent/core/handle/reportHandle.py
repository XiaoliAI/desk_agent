"""Local Desk Agent does not upload conversations to a manager service."""


async def report(conn, chat_type, text, audio_data, report_time):
    return None


def enqueue_tts_report(conn, text, opus_data):
    return None


def enqueue_tool_report(
    conn,
    tool_name: str,
    tool_input: dict,
    tool_result: str | None = None,
    report_tool_call: bool = True,
):
    return None


def enqueue_asr_report(conn, text, opus_data):
    return None

