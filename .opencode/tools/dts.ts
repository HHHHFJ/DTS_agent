import { tool } from "@opencode-ai/plugin"
import path from "path"

type OpenCodeContext = {
  directory?: string
  worktree?: string
}

async function runDts(args: string[], context: OpenCodeContext) {
  const home = Bun.env.DTS_AGENT_HOME || context.worktree || context.directory || process.cwd()
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
    throw new Error(stderr.trim() || stdout.trim() || `dts_agent exited with ${exitCode}`)
  }
  const trimmed = stdout.trim()
  if (!trimmed) return { status: "ok" }
  try {
    return JSON.parse(trimmed)
  } catch {
    return trimmed
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
  description: "Run dts_data_fetch.py, import DTS Excel, fetch GitCode PR diffs, and update the local SQLite security knowledge base.",
  args: {
    force: tool.schema.boolean().optional().describe("Force a manual refresh marker for audit output."),
    fetchScript: tool.schema.string().optional().describe("Path to dts_data_fetch.py. Defaults to DTS_FETCH_SCRIPT or ./dts_data_fetch.py."),
    skipFetchPr: tool.schema.boolean().optional().describe("Only import Excel tickets and PR links, without fetching GitCode PR diffs."),
  },
  async execute(args, context) {
    const cmd = ["sync", "--mode", "manual", "--json"]
    if (args.force) cmd.push("--force")
    if (args.fetchScript) cmd.push("--fetch-script", args.fetchScript)
    if (args.skipFetchPr) cmd.push("--skip-fetch-pr")
    return await runDts(cmd, context)
  },
})

export const import_excel = tool({
  description: "Import a DTS Excel/CSV file with columns 序号/问题单号/简要描述/严重程度/创建时间/提出方/修改文件清单.",
  args: {
    excelPath: tool.schema.string().describe("Path to the DTS Excel or CSV file."),
    skipFetchPr: tool.schema.boolean().optional().describe("Only import tickets and PR links, without fetching GitCode PR diffs."),
  },
  async execute(args, context) {
    const cmd = ["import-excel", "--file", args.excelPath, "--json"]
    if (args.skipFetchPr) cmd.push("--skip-fetch-pr")
    return await runDts(cmd, context)
  },
})

export const parse_pr_urls = tool({
  description: "Parse GitCode PR URLs from an imported DTS ticket or from a DTS Excel file.",
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
  description: "Fetch and parse old/new code snippets from a GitCode pull request URL.",
  args: {
    prUrl: tool.schema.string().describe("GitCode PR URL, for example https://gitcode.com/openeuler/ubs-engine/pull/466."),
    ticketId: tool.schema.string().optional().describe("DTS ticket id used for traceability. Defaults to MANUAL."),
  },
  async execute(args, context) {
    return await runDts(["fetch-pr-diff", "--url", args.prUrl, "--ticket", args.ticketId || "MANUAL", "--json"], context)
  },
})

export const build_kb = tool({
  description: "Build missing issue patterns from stored code snippets.",
  args: {},
  async execute(_args, context) {
    return await runDts(["build-kb", "--json"], context)
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
    minConfidence: tool.schema.number().optional().describe("Minimum match confidence. Defaults to DTS_REVIEW_MIN_CONFIDENCE or 0.35."),
  },
  async execute(args, context) {
    const cmd = ["review-diff", "--path", args.path || context.worktree || context.directory || ".", "--base", args.base || "HEAD~1", "--json"]
    if (args.minConfidence !== undefined) cmd.push("--min-confidence", String(args.minConfidence))
    return await runDts(cmd, context)
  },
})

export const review_repo = tool({
  description: "Review a repository path against the DTS security knowledge base.",
  args: {
    path: tool.schema.string().optional().describe("Repository path. Defaults to current OpenCode worktree."),
    minConfidence: tool.schema.number().optional().describe("Minimum match confidence. Defaults to DTS_REVIEW_MIN_CONFIDENCE or 0.35."),
  },
  async execute(args, context) {
    const cmd = ["review-repo", "--path", args.path || context.worktree || context.directory || ".", "--json"]
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
