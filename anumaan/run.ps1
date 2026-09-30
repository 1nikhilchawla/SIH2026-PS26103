<#
.SYNOPSIS
    ANUMAAN end-to-end pipeline: PDFs on disk -> parsed rows -> panel ->
    models -> metrics -> demo pages, optionally serving the live app.

.DESCRIPTION
    One command instead of nine, so a reviewer can reproduce every number in
    results/paimana/ without copying steps out of a README in the right order.
    The repository also carries a Makefile, but `make` is not present on a
    stock Windows box and its targets stop at the synthetic T1 model.

    Every step runs in dependency order and the script STOPS on the first
    failure. It never continues past a broken step to produce a page of stale
    numbers - a half-run pipeline that still writes HTML is how a demo ends up
    showing figures no command produced.

    The corpus is NOT downloaded by default. Harvesting hits the MoSPI portal,
    and the PDFs already on disk are SHA-256 verified against
    data/raw/manifest.csv by step 1. Pass -Harvest to fetch first.

.PARAMETER Harvest
    Download reports from the PAIMANA portal before parsing. Network access
    required. Without this flag the script uses data/raw as it stands.

.PARAMETER SinceFy
    Financial year to harvest from, e.g. "2019-20". Only used with -Harvest.

.PARAMETER SkipTests
    Skip the pytest run. Not recommended: those tests guard the parser.

.PARAMETER Serve
    After the pipeline succeeds, start the live app with uvicorn and leave it
    running in the foreground. Ctrl+C stops it.

.PARAMETER Port
    Port for -Serve. Default 8000.

.EXAMPLE
    ./run.ps1
    Full pipeline against the PDFs already in data/raw.

.EXAMPLE
    ./run.ps1 -Serve -Port 8010
    Full pipeline, then serve the app on http://127.0.0.1:8010

.EXAMPLE
    ./run.ps1 -Harvest -SinceFy 2019-20
    Download the corpus first, then run everything.
#>
[CmdletBinding()]
param(
    [switch]$Harvest,
    [string]$SinceFy = "2019-20",
    [switch]$SkipTests,
    [switch]$Serve,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$script:stepNo = 0
$started = Get-Date

function Write-Head([string]$text) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Write-Host $text -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkGray
}

function Invoke-Step {
    <#  Run one pipeline step and abort the whole run if it fails.
        $LASTEXITCODE is the only honest signal here: a Python script that
        raises SystemExit(1) still writes to stdout, so inspecting the output
        text would let a failure through. #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    $script:stepNo++
    Write-Head ("[{0}] {1}" -f $script:stepNo, $Name)
    Write-Host ("    {0} {1}" -f $script:Python, ($Arguments -join " ")) -ForegroundColor DarkGray
    $t0 = Get-Date
    & $script:Python @Arguments
    $code = $LASTEXITCODE
    $secs = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    if ($code -ne 0) {
        Write-Host ""
        Write-Host ("STOPPED at step {0} ({1}): exit code {2}." -f $script:stepNo, $Name, $code) -ForegroundColor Red
        Write-Host "Nothing downstream ran, so no artefact was refreshed from a failed step." -ForegroundColor Red
        exit $code
    }
    Write-Host ("    done in {0}s" -f $secs) -ForegroundColor DarkGreen
}

# --- Interpreter -------------------------------------------------------------
# Prefer the project venv. Falling back to a bare `python` is allowed but
# announced, because the pinned versions in requirements.txt are the ones that
# produced the checked-in numbers.
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $script:Python = $venvPython
} else {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Write-Host "No .venv and no python on PATH. Create the environment first:" -ForegroundColor Red
        Write-Host "    python -m venv .venv"
        Write-Host "    .venv/Scripts/python.exe -m pip install -r requirements.txt"
        exit 1
    }
    $script:Python = $cmd.Source
    Write-Host "WARNING: .venv not found, using $($cmd.Source)." -ForegroundColor Yellow
    Write-Host "         Versions may differ from requirements.txt." -ForegroundColor Yellow
}

Write-Head "ANUMAAN pipeline"
& $script:Python --version
Write-Host ("root      : {0}" -f $root)
Write-Host ("python    : {0}" -f $script:Python)
if ($Harvest) {
    Write-Host ("harvest   : yes (since FY {0})" -f $SinceFy)
} else {
    Write-Host "harvest   : no - using data/raw as it stands"
}

# --- Preflight: are the imports the code needs actually installed? -----------
# Checked before any work, so a missing package fails in two seconds rather
# than twelve minutes into the run.
Write-Head "[0] Preflight - dependency check"
$probe = @'
import importlib.util as u, sys
need = ["requests","bs4","pdfplumber","pandas","numpy","sklearn",
        "lightgbm","shap","yaml","matplotlib","fastapi","uvicorn"]
missing = [m for m in need if u.find_spec(m) is None]
if missing:
    print("missing packages: " + ", ".join(missing))
    sys.exit(1)
print("all required packages present")
'@
$probe | & $script:Python -
if ($LASTEXITCODE -ne 0) {
    Write-Host "Install them with:" -ForegroundColor Red
    Write-Host "    $script:Python -m pip install -r requirements.txt"
    exit 1
}

$rawDir = Join-Path $root "data\raw"
$pdfCount = @(Get-ChildItem -Path $rawDir -Filter *.pdf -ErrorAction SilentlyContinue).Count
if ($pdfCount -eq 0 -and -not $Harvest) {
    Write-Host "No PDFs in data/raw and -Harvest was not given. Either:" -ForegroundColor Red
    Write-Host "    ./run.ps1 -Harvest          (download from the MoSPI portal)"
    Write-Host "    or place the Flash Report PDFs in data/raw alongside manifest.csv"
    exit 1
}
Write-Host ("PDFs in data/raw: {0}" -f $pdfCount)

# --- Pipeline ----------------------------------------------------------------
if ($Harvest) {
    Invoke-Step -Name "Harvest Flash Reports from the PAIMANA portal" `
                -Arguments @("scripts/harvest_paimana.py", "--since-fy", $SinceFy)
}

Invoke-Step -Name "Verify corpus SHA-256 against data/raw/manifest.csv" `
            -Arguments @("scripts/verify_corpus.py", "--quiet")

Invoke-Step -Name "Parse every report, fail-closed against its printed totals" `
            -Arguments @("scripts/parse_paimana.py", "--all")

Invoke-Step -Name "Build the project x month panel (reconciled reports only)" `
            -Arguments @("scripts/build_panel.py")

Invoke-Step -Name "Train the slip model, walk-forward, with leakage controls" `
            -Arguments @("scripts/train_slip.py")

Invoke-Step -Name "Train the cost model (weak by design - see the honesty page)" `
            -Arguments @("scripts/train_cost.py")

Invoke-Step -Name "Diagnose the cost target: is the threshold the problem?" `
            -Arguments @("scripts/diagnose_cost_target.py")

Invoke-Step -Name "Evaluate: precision@k, reliability, SHAP attributions" `
            -Arguments @("scripts/eval_slip.py")

Invoke-Step -Name "Build the static demo pages from the artefacts on disk" `
            -Arguments @("scripts/build_demo_paimana.py")

# The pipeline rewrites results/paimana/, which the integrity manifest covers.
# Re-hash here so the tree is consistent; this seal is UNSIGNED on purpose.
# Production accepts only a manifest signed with ANUMAAN_INTEGRITY_KEY, which
# a person applies after review: python scripts/integrity.py seal --prompt-key
Invoke-Step -Name "Re-seal the integrity manifest (unsigned - sign after review)" `
            -Arguments @("scripts/integrity.py", "seal")

if (-not $SkipTests) {
    Invoke-Step -Name "Run the test suite" -Arguments @("-m", "pytest", "-q")
}

# --- Summary -----------------------------------------------------------------
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
Write-Head "Pipeline complete in ${elapsed}s"

$summary = @'
import json, pathlib
R = pathlib.Path("results/paimana")

def load(name):
    p = R / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

man, prov = load("manifest_verification.json"), load("panel_provenance.json")
slip, prec = load("metrics_slip.json"), load("precision_at_k.json")
if man:
    print(f"corpus     : {man['sha_ok']}/{man['manifest_rows']} PDFs SHA-256 verified")
if prov:
    print(f"panel      : {prov['n_rows']} rows | {prov['n_projects']} projects | "
          f"{prov['n_months']} months ({prov['panel_span']})")
    print(f"base rate  : {prov['slip_next_base_rate']:.4f} on "
          f"{prov['labelled_rows_slip_next']} labelled rows")
if slip and slip.get("folds"):
    f = slip["folds"][-1]
    m = f["models"]
    best_base = max(m[b]["pr_auc"] for b in
                    ("always_base_rate", "ministry_base_rate", "slipped_last_month"))
    print(f"slip model : fold {f['test_month']} lightgbm PR-AUC "
          f"{m['lightgbm']['pr_auc']:.4f} vs best baseline {best_base:.4f}")
    lk = f["leakage_check"]
    print(f"leakage    : real {lk['real_pr_auc']:.4f} | "
          f"shuffled {lk['shuffled_labels_pr_auc']:.4f} | "
          f"planted {lk['with_planted_leak_pr_auc']:.4f}")
if prec:
    row = next((r for r in prec["rows"] if r["k"] == 50), None)
    if row:
        print(f"usefulness : inspect top 50/month -> catch "
              f"{row['n_slips_caught']} slips vs {row['n_slips_at_random_k']} "
              f"at random ({row['lift_over_random']}x)")
'@
$summary | & $script:Python -

Write-Host ""
Write-Host "Artefacts : results/paimana/" -ForegroundColor Green
Write-Host "Demo pages: demo/paimana/index.html" -ForegroundColor Green
Write-Host ""

if ($Serve) {
    Write-Head "Serving the live app on http://127.0.0.1:$Port"
    Write-Host "The model trains in-process at startup. Ctrl+C to stop." -ForegroundColor DarkGray
    & $script:Python -m uvicorn app.main:app --port $Port
} else {
    Write-Host "To serve the live app:" -ForegroundColor DarkGray
    Write-Host "    ./run.ps1 -Serve -Port 8010" -ForegroundColor DarkGray
    Write-Host "To view the static pages:" -ForegroundColor DarkGray
    Write-Host "    $script:Python -m http.server 8766 --directory demo/paimana" -ForegroundColor DarkGray
}
