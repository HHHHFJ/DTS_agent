from __future__ import annotations


ISSUE_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "权限校验缺失",
        r"权限|鉴权|认证|授权|permission|auth|privilege|capability|access",
        "补充权限/鉴权检查，确保敏感路径在执行前完成主体、角色和资源范围校验。",
    ),
    (
        "输入校验缺失",
        r"参数|输入|校验|validate|check|invalid|非法|null|none|空指针|越界|bounds|range|length",
        "对外部输入、长度、空值、边界和状态组合做显式校验，并保持错误返回路径一致。",
    ),
    (
        "命令注入风险",
        r"命令|shell|exec|system|popen|subprocess|注入|injection",
        "避免拼接命令；使用参数化调用和白名单校验，必要时限制可执行命令范围。",
    ),
    (
        "路径穿越风险",
        r"路径|目录|path|file|filename|traversal|\.\./|绝对路径",
        "规范化路径并限制在可信根目录内，拒绝穿越、绝对路径和非法文件名。",
    ),
    (
        "资源释放遗漏",
        r"释放|泄漏|close|free|release|defer|cleanup|resource|fd|handle|memory leak",
        "确保异常和提前返回路径都释放资源，优先使用上下文管理或统一清理分支。",
    ),
    (
        "并发竞态",
        r"并发|竞态|race|lock|mutex|thread|goroutine|atomic|同步",
        "为共享状态补充锁、原子操作或事务边界，避免检查和使用之间的竞态窗口。",
    ),
    (
        "敏感信息泄露",
        r"敏感|泄露|密码|token|secret|key|log|日志|credential",
        "避免输出敏感字段；在日志、异常和接口响应中做脱敏或移除。",
    ),
    (
        "错误处理缺失",
        r"错误|异常|error|exception|return code|errno|fail|失败",
        "检查错误返回并补充失败分支，避免继续使用无效状态或不完整结果。",
    ),
)


def issue_advice(issue_type: str) -> str:
    for current_type, _pattern, advice in ISSUE_RULES:
        if current_type == issue_type:
            return advice
    return "结合历史修复前后差异补充等价防护逻辑，并为边界、异常和失败路径增加测试。"
