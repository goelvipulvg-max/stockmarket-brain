# graphq.ps1 - UTF-8-safe wrapper for the `graphify` code-graph CLI on Windows.
#
# Why: graphify prints Unicode (arrows, section signs) which crashes the default cp1252
# console with UnicodeEncodeError (and shows mojibake). This sets UTF-8 for THIS process
# only -- it does NOT touch global env vars, so the trading engine's Python is unaffected.
#
# Also blocks `extract` (which calls an LLM and costs tokens). Use `update .` for an
# AST-only, zero-cost rebuild. AST-only, always.
#
# NOTE: keep this file ASCII-only -- Windows PowerShell 5.1 reads BOM-less files as cp1252,
# so any non-ASCII byte here would break parsing (the very bug this wrapper exists to avoid).
#
# Usage:
#   .\graphq.ps1 query "how does the two-AI consensus decide a trade"
#   .\graphq.ps1 path "determine_consensus()" "process_filing()"
#   .\graphq.ps1 explain "ai_consensus"
#   .\graphq.ps1 update .

if ($args.Count -gt 0 -and $args[0] -eq 'extract') {
    Write-Error "graphq.ps1: 'extract' is blocked - it calls an LLM and spends tokens. Use 'update .' for an AST-only rebuild."
    exit 2
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
& graphify @args
exit $LASTEXITCODE
