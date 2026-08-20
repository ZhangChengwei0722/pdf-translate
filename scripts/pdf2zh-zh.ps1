# pdf2zh-zh.ps1: thin launcher for the PDF Translator skill pipeline.
# Usage: .\pdf2zh-zh.ps1 start --input <pdf> --output-mode <mono|dual|mono+dual> --review-mode <multimodal|human|none> [-- <pdf2zh args...>]
#        .\pdf2zh-zh.ps1 continue --session <dir> --accept <ids> --reject <ids> [-- <pdf2zh args...>]
# Forwards all arguments verbatim to run_pipeline.py and returns its exit code.
# This script never reads keys, never sets provider environment variables,
# and never appends provider flags.

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pipeline = Join-Path $scriptDir 'run_pipeline.py'
if (-not (Test-Path $pipeline)) {
    Write-Error "run_pipeline.py not found next to $($MyInvocation.MyCommand.Path)"
    exit 2
}

$python = Get-Command python -ErrorAction Stop
& $python.Source $pipeline @args
exit $LASTEXITCODE
