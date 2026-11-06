# Install ai-symbiont without cloning the repository (Windows PowerShell).
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/smalls257/ai-symbiont/main/install.ps1))) [-Nightly] [-Ref <git ref>] [-Harness <id>|auto|all|none]
#
# Parallel to install.sh: this script knows only `uv` and the package. Harness plugin commands
# live in `symbiont setup`, read from the harness registry. Re-running upgrades the package.
param(
    [switch]$Nightly,
    [string]$Ref = "main",
    [string]$Harness = "auto"
)
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/smalls257/ai-symbiont"
$UvInstallHint = 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
$extras = if ($Nightly) { "[nightly]" } else { "" }  # torch is large, so the trainer is opt-in

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    # Not piped on the user's behalf: running a second remote script is the user's call.
    # throw, never exit: this runs inside the user's own session as a scriptblock, and exit would close it.
    throw "install.ps1: uv is not installed. Install it with the official command, then run this again:`n  $UvInstallHint"
}

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "install.ps1: '$Program $($Arguments -join ' ')' failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked "uv" @("tool", "install", "--force", "ai-symbiont$extras @ git+$RepoUrl@$Ref")
Invoke-Checked "uv" @("tool", "update-shell")
$binDir = (& uv tool dir --bin).Trim()
# uv tool installs the console script as symbiont.exe on Windows (Windows PowerShell 5.1 has no $IsWindows).
$onWindows = ($PSVersionTable.PSEdition -eq "Desktop") -or ($IsWindows -eq $true)
$symbiont = if ($onWindows) { "symbiont.exe" } else { "symbiont" }
Invoke-Checked (Join-Path $binDir $symbiont) @("setup", "--harness", $Harness)
