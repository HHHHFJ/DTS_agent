import { tool } from "@opencode-ai/plugin"
import path from "node:path"

type OpenCodeContext = {
  directory?: string
  worktree?: string
}

/** Run a dts_agent command and return a ToolResult-compatible object. */
async function runDts(args: string[], context: OpenCodeContext) {
  try {
    const pluginHome = path.resolve(import.meta.dir, "..", "..")
    const home = Bun.env.DTS_AGENT_HOME || pluginHome
    const python = Bun.env.DTS_AGENT_PYTHON || "python"
    const pythonPath = [home, Bun.env.PYTHONPATH].filter(Boolean).join(path.delimiter)
    const proc = Bun.spawn([python, "-m", "dts_agent", "--root", home, ...args], {
      cwd: context.directory || context.worktree || home,
      env: {
        ...Bun.env,
        DTS_AGENT_HOME: home,
        PYTHONPATH: pythonPath,
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const stdout = await new Response(proc.stdout).text()
    const stderr = await new Response(proc.stderr).text()
    const exitCode = await proc.exited
    if (exitCode !== 0) {
      return { output: stderr.trim() || stdout.trim() || `dts_agent exited with ${exitCode}` }
    }
    const trimmed = stdout.trim()
    if (!trimmed) return { output: "OK" }
    const parsed = JSON.parse(trimmed)
    if (typeof parsed === "object" && parsed !== null && typeof parsed.output === "string") {
      return parsed
    }
    return {
      output: JSON.stringify(parsed, null, 2),
      metadata: parsed,
    }
  } catch (err) {
    return { output: `dts_agent error: ${err instanceof Error ? err.message : String(err)}` }
  }
}

export const status = tool({
  description: "Show DTS Guardian knowledge base status.",
  args: {},
  async execute(_args, context) {
    return await runDts(["status", "--json"], context)
  },
})

export const sync_now = tool({
  description: "Run dts_data_fetch.py, import DTS Excel, fetch configured repository PR/MR diffs, and update the local SQLite security knowledge base.",
  args: {
    force: tool.schema.boolean().optional().describe("Force a manual refresh marker for maintenance output."),
    excelPath: tool.schema.string().optional().describe("Existing DTS Excel/CSV path to import instead of running dts_data_fetch.py."),
    excelOutputDir: tool.schema.string().optional().describe("Directory where dts_data_fetch.py generated Excel/CSV should be stored."),
    excelOutputFile: tool.schema.string().optional().describe("Exact generated Excel/CSV path, ending with .xlsx or .csv."),
    fetchScript: tool.schema.string().optional().describe("Path to dts_data_fetch.py. Defaults to DTS_FETCH_SCRIPT or ./dts_data_fetch.py."),
    skipFetchPr: tool.schema.boolean().optional().describe("Only import Excel tickets and PR links, without fetching repository PR/MR diffs."),
    skipBuildKb: tool.schema.boolean().optional().describe("Fetch PR snippets but do not build knowledge patterns. Use this for OpenCode Agent judgement mode."),
    interactiveTokenSetup: tool.schema.boolean().optional().describe("Open a local token setup dialog when parsed PR/MR hosts need credentials. Defaults to true."),
    requireLlm: tool.schema.boolean().optional().describe("Fail if no LLM security judge is configured."),
  },
  async execute(args, context) {
    const cmd = ["sync", "--mode", "manual", "--json"]
    if (args.force) cmd.push("--force")
    if (args.excelPath) cmd.push("--file", args.excelPath)
    if (args.excelOutputDir) cmd.push("--output-dir", args.excelOutputDir)
    if (args.excelOutputFile) cmd.push("--output-file", args.excelOutputFile)
    if (args.fetchScript) cmd.push("--fetch-script", args.fetchScript)
    if (args.skipFetchPr) cmd.push("--skip-fetch-pr")
    if (args.skipBuildKb) cmd.push("--skip-build-kb")
    if (args.interactiveTokenSetup !== false) cmd.push("--interactive-token-setup")
    if (args.requireLlm) cmd.push("--require-llm")
    return await runDts(cmd, context)
  },
})

export const import_excel = tool({
  description: "Import a DTS Excel/CSV file with columns 序号/问题单号/简要描述/严重程度/创建时间/提出方/修改文件清单.",
  args: {
    excelPath: tool.schema.string().describe("Path to the DTS Excel or CSV file."),
    skipFetchPr: tool.schema.boolean().optional().describe("Only import tickets and PR links, without fetching repository PR/MR diffs."),
    skipBuildKb: tool.schema.boolean().optional().describe("Fetch PR snippets but do not build knowledge patterns. Use this for OpenCode Agent judgement mode."),
    interactiveTokenSetup: tool.schema.boolean().optional().describe("Open a local token setup dialog when parsed PR/MR hosts need credentials. Defaults to true."),
    requireLlm: tool.schema.boolean().optional().describe("Fail if no LLM security judge is configured."),
  },
  async execute(args, context) {
    const cmd = ["import-excel", "--file", args.excelPath, "--json"]
    if (args.skipFetchPr) cmd.push("--skip-fetch-pr")
    if (args.skipBuildKb) cmd.push("--skip-build-kb")
    if (args.interactiveTokenSetup !== false) cmd.push("--interactive-token-setup")
    if (args.requireLlm) cmd.push("--require-llm")
    return await runDts(cmd, context)
  },
})

export const parse_pr_urls = tool({
  description: "Parse configured repository PR/MR URLs from an imported DTS ticket or from a DTS Excel file.",
  args: {
    ticketId: tool.schema.string().optional().describe("Optional DTS ticket id."),
    excelPath: tool.schema.string().optional().describe("Optional DTS Excel/CSV path to parse directly."),
  },
  async execute(args, context) {
    const cmd = ["parse-pr-urls", "--json"]
    if (args.ticketId) cmd.push("--ticket", args.ticketId)
    if (args.excelPath) cmd.push("--file", args.excelPath)
    return await runDts(cmd, context)
  },
})

export const fetch_pr_diff = tool({
  description: "Fetch and parse old/new code snippets from a repository pull request or merge request URL.",
  args: {
    prUrl: tool.schema.string().describe("Repository PR/MR URL, for example https://gitcode.com/openeuler/ubs-engine/pull/466 or https://codehub-y.huawei.com/group/repo/-/merge_requests/123."),
    ticketId: tool.schema.string().optional().describe("DTS ticket id used for traceability. Defaults to MANUAL."),
    interactiveTokenSetup: tool.schema.boolean().optional().describe("Open a local token setup dialog when this PR/MR host needs credentials. Defaults to true."),
  },
  async execute(args, context) {
    const cmd = ["fetch-pr-diff", "--url", args.prUrl, "--ticket", args.ticketId || "MANUAL", "--json"]
    if (args.interactiveTokenSetup !== false) cmd.push("--interactive-token-setup")
    return await runDts(cmd, context)
  },
})

export const build_kb = tool({
  description: "Build issue patterns from stored code snippets.",
  args: {
    rebuild: tool.schema.boolean().optional().describe("Rebuild all patterns from stored snippets."),
    requireLlm: tool.schema.boolean().optional().describe("Fail if no LLM security judge is configured."),
  },
  async execute(args, context) {
    const cmd = ["build-kb", "--json"]
    if (args.rebuild) cmd.push("--rebuild")
    if (args.requireLlm) cmd.push("--require-llm")
    return await runDts(cmd, context)
  },
})

export const clear_kb = tool({
  description: "Clear generated DTS knowledge patterns while keeping imported DTS tickets, PR links, and snippets.",
  args: {
    includeJudgements: tool.schema.boolean().optional().describe("Also clear OpenCode agent snippet judgements."),
  },
  async execute(args, context) {
    const cmd = ["clear-kb", "--json"]
    if (args.includeJudgements) cmd.push("--include-judgements")
    return await runDts(cmd, context)
  },
})

export const judgement_tasks = tool({
  description: "List stored PR diff snippets that need OpenCode agent security judgement before entering the knowledge base.",
  args: {
    limit: tool.schema.number().optional().describe("Maximum task count. Defaults to 5."),
    ticketId: tool.schema.string().optional().describe("Only list snippets for one DTS ticket."),
    rejudge: tool.schema.boolean().optional().describe("Include snippets that already have judgements."),
  },
  async execute(args, context) {
    const cmd = ["judge-tasks", "--limit", String(args.limit || 5), "--json"]
    if (args.ticketId) cmd.push("--ticket", args.ticketId)
    if (args.rejudge) cmd.push("--rejudge")
    return await runDts(cmd, context)
  },
})

export const apply_judgement = tool({
  description: "Store an OpenCode agent judgement for one snippet and create a searchable pattern only when the old code has a real security issue.",
  args: {
    snippetId: tool.schema.string().describe("Snippet id from dts_judgement_tasks."),
    hasSecurityIssue: tool.schema.boolean().describe("Whether the old snippet/context contains a real security issue."),
    issueType: tool.schema.string().describe("Issue type, for example 命令注入风险, 权限校验缺失, 路径穿越风险, or 通用安全缺陷."),
    confidence: tool.schema.number().describe("Confidence from 0 to 1."),
    rationale: tool.schema.string().describe("Short Chinese rationale based on the old snippet and context."),
    fixAdvice: tool.schema.string().optional().describe("Optional fix advice. Defaults to built-in advice for the issue type."),
  },
  async execute(args, context) {
    const cmd = [
      "apply-judgement",
      "--snippet-id", args.snippetId,
      "--has-security-issue", String(args.hasSecurityIssue),
      "--issue-type", args.issueType,
      "--confidence", String(args.confidence),
      "--rationale", args.rationale,
      "--source", "opencode-agent",
      "--json",
    ]
    if (args.fixAdvice) cmd.push("--fix-advice", args.fixAdvice)
    return await runDts(cmd, context)
  },
})

export const kb_query = tool({
  description: "Query the DTS security knowledge base by ticket id, issue type, keywords, or code snippet.",
  args: {
    query: tool.schema.string().describe("Search text or code snippet."),
    limit: tool.schema.number().optional().describe("Maximum result count. Defaults to 10."),
  },
  async execute(args, context) {
    return await runDts(["query", "--query", args.query, "--limit", String(args.limit || 10), "--json"], context)
  },
})

export const review_diff = tool({
  description: "Review the current git diff against the DTS security knowledge base.",
  args: {
    base: tool.schema.string().optional().describe("Git base revision. Defaults to HEAD~1."),
    path: tool.schema.string().optional().describe("Repository path. Defaults to current OpenCode worktree."),
    exclude: tool.schema.array(tool.schema.string()).optional().describe("Directory names or relative paths to exclude, for example ['test', 'tests']."),
    minConfidence: tool.schema.number().optional().describe("Minimum match confidence. Defaults to DTS_REVIEW_MIN_CONFIDENCE or 0.70."),
  },
  async execute(args, context) {
    const cmd = ["review-diff", "--path", args.path || context.worktree || context.directory || ".", "--base", args.base || "HEAD~1", "--json"]
    for (const item of args.exclude || []) cmd.push("--exclude", item)
    if (args.minConfidence !== undefined) cmd.push("--min-confidence", String(args.minConfidence))
    return await runDts(cmd, context)
  },
})

export const review_repo = tool({
  description: "Review a repository path against the DTS security knowledge base.",
  args: {
    path: tool.schema.string().optional().describe("Repository path. Defaults to current OpenCode worktree."),
    exclude: tool.schema.array(tool.schema.string()).optional().describe("Directory names or relative paths to exclude, for example ['test', 'tests']."),
    minConfidence: tool.schema.number().optional().describe("Minimum match confidence. Defaults to DTS_REVIEW_MIN_CONFIDENCE or 0.70."),
  },
  async execute(args, context) {
    const cmd = ["review-repo", "--path", args.path || context.worktree || context.directory || ".", "--json"]
    for (const item of args.exclude || []) cmd.push("--exclude", item)
    if (args.minConfidence !== undefined) cmd.push("--min-confidence", String(args.minConfidence))
    return await runDts(cmd, context)
  },
})

export const generate_report = tool({
  description: "Generate a DTS security test report from a review run.",
  args: {
    reviewId: tool.schema.string().optional().describe("Review id. Defaults to latest."),
    format: tool.schema.enum(["md", "json"]).optional().describe("Report format. Defaults to md."),
    output: tool.schema.string().optional().describe("Optional output file path."),
  },
  async execute(args, context) {
    const cmd = ["report", "--review-id", args.reviewId || "latest", "--format", args.format || "md", "--json"]
    if (args.output) cmd.push("--output", args.output)
    return await runDts(cmd, context)
  },
})
