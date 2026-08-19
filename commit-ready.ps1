<#
  Stage and commit auto_Interner. Does NOT push - that stays your call.

  Double-click COMMIT.cmd, or:
      powershell -ExecutionPolicy Bypass -File commit-ready.ps1

  Handles the stale .git/index.lock that has blocked every previous attempt.
#>
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

function Say($t)  { Write-Host ""; Write-Host $t -ForegroundColor Cyan }
function Note($t) { Write-Host "   $t" -ForegroundColor Gray }
function Alarm($t){ Write-Host "   $t" -ForegroundColor Red }

# --- 1. the lock ------------------------------------------------------------
Say "1. stale index.lock"
$lock = Join-Path $PSScriptRoot '.git\index.lock'
if (Test-Path -LiteralPath $lock) {
    # Git writes this before touching the index and removes it after. If a
    # process died mid-write it survives, and every add/commit/rm then fails
    # with "Another git process seems to be running". Safe to remove when no
    # git process is actually live.
    $live = Get-Process git -ErrorAction SilentlyContinue
    if ($live) { Alarm "a git process IS running (PID $($live.Id)). Close it, then re-run."; exit 1 }
    Remove-Item -LiteralPath $lock -Force
    Note "removed"
} else { Note "none" }

# --- 2. unreferenced artefact ----------------------------------------------
Say "2. unreferenced demo.gif"
$gif = Join-Path $PSScriptRoot 'docs\media\demo.gif'
if (Test-Path -LiteralPath $gif) {
    $mb = [math]::Round((Get-Item $gif).Length / 1MB, 1)
    Remove-Item -LiteralPath $gif -Force
    Note "removed ($mb MB, replaced by the worked example)"
} else { Note "already gone" }

# --- 3. stage ---------------------------------------------------------------
Say "3. staging"
& git add -A
$staged = (& git status --porcelain | Measure-Object).Count
Note "$staged change(s) staged"

# --- 4. the check that matters ---------------------------------------------
Say "4. secret scan"
$bad = & git diff --cached --name-only |
       Where-Object { $_ -match '(?i)(^|/)\.env$|secret|credential|\.key$|\.pem$' } |
       Where-Object { $_ -notmatch '\.env\.example$' }
if ($bad) {
    Alarm "STOP - sensitive path staged:"
    $bad | ForEach-Object { Alarm "   $_" }
    Alarm "Nothing was committed. Run: git reset"
    exit 1
}
Note "clean - no secret staged"

$claude = & git diff --cached --name-only | Where-Object { $_ -like '.claude/*' }
if ($claude) { Alarm "STOP - .claude/ is staged. Check .gitignore."; exit 1 }
Note ".claude/ not staged"

# --- 5. commit --------------------------------------------------------------
Say "5. commit"
$before = (& git log --oneline | Measure-Object).Count
& git commit -q -m "Add corpus selection, worked example, and scope documentation"
$after = (& git log --oneline | Measure-Object).Count
if ($after -gt $before) { Note "committed - $after total" }
else { Alarm "commit did not happen"; exit 1 }

Say "Done. Nothing pushed."
Write-Host ""
Write-Host "   Review, then push yourself:" -ForegroundColor Gray
Write-Host "       git show --stat HEAD" -ForegroundColor Gray
Write-Host "       git push origin main" -ForegroundColor Gray
Write-Host ""
