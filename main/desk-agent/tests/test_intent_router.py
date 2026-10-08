from core.agent.intent_router import IntentRouter


router = IntentRouter()


def test_send_file_email():
    result = router.classify_fast("把桌面的成绩单发到我的邮箱")
    assert result is not None
    assert result.name == "send_file_email"
    assert result.entities["file_query"] == "成绩单"


def test_edit_any_text_and_send():
    result = router.classify_fast(
        "把桌面的成绩单里的名字改成agent，然后发给我"
    )
    assert result is not None
    assert result.name == "edit_document_and_send"
    assert result.entities["new_text"] == "agent"
    assert "old_text" in result.missing_fields


def test_edit_exact_text():
    result = router.classify_fast("把报告里的金额从100改成200")
    assert result is not None
    assert result.name == "edit_document"
    assert result.entities["old_text"] == "100"
    assert result.entities["new_text"] == "200"


def test_delete_text_is_edit():
    result = router.classify_fast("删除成绩单里的学号123")
    assert result is not None
    assert result.name == "edit_document"
    assert result.entities["file_query"] == "成绩单"
    assert result.entities["old_text"] == "学号123"
    assert result.entities["new_text"] == ""


def test_edit_named_field_to_new_content():
    result = router.classify_fast("修改报告里的标题为AI报告")
    assert result is not None
    assert result.name == "edit_document"
    assert result.entities["file_query"] == "报告"
    assert result.entities["old_text"] == "标题"
    assert result.entities["new_text"] == "AI报告"
    assert "old_text" in result.missing_fields


def test_edit_arbitrary_text_and_send():
    result = router.classify_fast("把桌面的报告里的旧标题替换成新的AI项目汇报，然后发给我")
    assert result is not None
    assert result.name == "edit_document_and_send"
    assert result.entities["file_query"] == "报告"
    assert result.entities["old_text"] == "旧标题"
    assert result.entities["new_text"] == "新的AI项目汇报"
    assert result.missing_fields == []


def test_edit_with_change_wording():
    result = router.classify_fast("把报告里的标题换成AI报告")
    assert result is not None
    assert result.name == "edit_document"
    assert result.entities["file_query"] == "报告"
    assert result.entities["old_text"] == "标题"
    assert result.entities["new_text"] == "AI报告"


def test_edit_custom_document_name():
    result = router.classify_fast("把桌面上的预算表.docx中的第二季度换成第三季度")
    assert result is not None
    assert result.name == "edit_document"
    assert result.entities["file_query"] == "预算表.docx"
    assert result.entities["old_text"] == "第二季度"
    assert result.entities["new_text"] == "第三季度"


def test_edit_recently_found_file_reference():
    result = router.classify_fast("修改刚刚找到的简历，将李栩威换成李威")
    assert result is not None
    assert result.name == "edit_document"
    assert result.entities["file_query"] == "简历"
    assert result.entities["old_text"] == "李栩威"
    assert result.entities["new_text"] == "李威"


def test_weather():
    result = router.classify_fast("查询北京天气")
    assert result is not None
    assert result.name == "weather"


def test_confirm_cancel_and_selection():
    assert router.classify_fast("确认发送").name == "confirm_task"
    assert router.classify_fast("取消发送").name == "cancel_task"
    assert router.classify_fast("选择第2个").name == "select_file"


def test_chat_falls_through():
    assert router.classify_fast("你好") is None
