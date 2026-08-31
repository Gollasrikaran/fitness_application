# Wrapper for Windows Task Scheduler — runs the weekly progression job and
# keeps a plain log, since Task Scheduler doesn't surface console output on
# its own. The job itself (scripts/run_weekly_progression.py) is unchanged;
# this is scheduling only (Implementation_RLM_plan.md Phase 7).
#
# Uses python.exe's full resolved path (from `python -c "import sys;
# print(sys.executable)"`), not bare "python.exe" — found live: a
# Task-Scheduler-triggered run produced no log output and no error, most
# likely because the Windows Store Python execution alias that resolves
# "python.exe" in an interactive shell does not reliably resolve the same
# way in Task Scheduler's non-interactive execution context. The whole body
# is wrapped in try/catch so ANY failure — even one this script didn't
# anticipate — still leaves a real line in the log instead of the silent
# nothing that made the original failure hard to diagnose.
#
# Also deliberately does NOT redirect the python call's stdout with 2>&1: in
# Windows PowerShell 5.1, merging a native command's stderr into the success
# stream that way wraps each line in a NativeCommandError, which (combined
# with $ErrorActionPreference = "Stop") aborts the pipeline immediately —
# discovered live, when the job's own ordinary WARNING-level guard-clamp log
# line (expected, not a failure) got misread as fatal and could have cut the
# run off before it finished. Stderr is instead redirected straight to its
# own file below (2> $errFile, never merged into the stdout pipe), which
# sidesteps that specific failure mode while still capturing tracebacks —
# found live (code audit): the previous version dropped stderr entirely, so
# an unhandled Python exception left no trace beyond "exit code 1" in the log.
#
# FLASK_ENV is set explicitly, not left to default (found live, code audit):
# Task Scheduler does not inherit a user's shell environment, so this job
# previously ran with FLASK_ENV silently defaulting to "development" inside
# run_weekly_progression.py — which happens to be correct for right now
# (this app isn't deployed anywhere real yet; .env.dev itself sets
# FLASK_ENV=development, and none of the production secrets exist).
# *** WHEN THIS APP IS ACTUALLY DEPLOYED TO PRODUCTION, change the line below
# to "production" and make sure SECRET_KEY / JWT_CURRENT_KID / JWT_KEY_CURRENT
# / REDIS_DURABLE_URL / REDIS_CACHE_URL / DATABASE_URL are all set in this
# process's real environment first — load_config() now refuses to boot with
# an unrecognized FLASK_ENV value, but an explicit wrong value here would
# still be a real mistake this comment can't catch for you. ***
$env:FLASK_ENV = "development"

# Found live (code audit): both the repo root and the python.exe path below
# used to be hardcoded to this one developer's machine
# ("D:\fitness_app", a WindowsApps python.exe under a specific user
# profile) — this script would not run at all on any other machine, user
# account, or checkout location, including a real production host once one
# is chosen. Both are now resolved at runtime instead.

# $PSScriptRoot is this file's own directory (scripts\); the repo root is
# one level up, wherever the repo actually happens to be checked out.
$repoRoot = Split-Path -Parent $PSScriptRoot

# Resolve a REAL python.exe instead of hardcoding one. The original bug
# this file's header comment describes was about invoking the BARE
# "python.exe" command by name — PATH/execution-alias resolution at
# invocation time is what's unreliable under Task Scheduler's
# non-interactive context, not the resolved target file itself. Get-Command
# resolves that alias to its real, full target path correctly even in this
# same context (verified live); using that full path — same as the old
# hardcoded value did — sidesteps the alias problem entirely regardless of
# whether it happens to live under WindowsApps.
#
# Tried preferring py.exe (the official Python Launcher) first here — found
# live it can resolve to a DIFFERENT Python install than the one with this
# project's actual dependencies (sqlalchemy etc.) installed, e.g. a bare
# system Python alongside a WindowsApps one used for real work. python.exe/
# python3.exe on PATH is what a developer's shell and this project's own
# setup actually use, so that has to come first; py.exe is a last-resort
# fallback only, not a preference.
function Resolve-PythonExe {
    foreach ($name in @("python.exe", "python3.exe")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw ("Could not find any python.exe/python3.exe/py.exe on PATH for " +
           "the account this task runs as. Install Python and/or add it " +
           "to PATH, or hardcode `$pythonExe in this script for this " +
           "specific machine.")
}

$logDir = Join-Path $repoRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logFile = Join-Path $logDir "weekly_progression.log"
$errFile = Join-Path $logDir "weekly_progression_stderr.tmp"

function Write-Log($message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] $message" | Out-File -Append -Encoding utf8 $logFile
}

try {
    $pythonExe = Resolve-PythonExe
    Write-Log "Wrapper started (FLASK_ENV=$env:FLASK_ENV, repoRoot=$repoRoot, python=$pythonExe)"
    Set-Location $repoRoot
    Write-Log "Working directory set; invoking $pythonExe"

    & $pythonExe "scripts\run_weekly_progression.py" 2> $errFile | Out-File -Append -Encoding utf8 $logFile
    $exitCode = $LASTEXITCODE

    if (Test-Path $errFile) {
        $errContent = Get-Content $errFile -Raw -ErrorAction SilentlyContinue
        if ($errContent -and $errContent.Trim()) {
            Write-Log "STDERR:`n$errContent"
        }
        Remove-Item $errFile -Force -ErrorAction SilentlyContinue
    }

    Write-Log "Run finished, exit code $exitCode"
} catch {
    Write-Log "WRAPPER ERROR: $($_.Exception.Message)"
}
