# AmnesiaFS Windows Setup Script
# Run with: .\setup.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AmnesiaFS Setup for Windows" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check for admin rights (needed for WinFsp)
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# Step 1: Check/Install WinFsp
Write-Host "[1/3] Checking WinFsp..." -ForegroundColor Yellow
if (Test-Path "C:\Program Files (x86)\WinFsp") {
    Write-Host "  WinFsp is already installed." -ForegroundColor Green
} else {
    Write-Host "  WinFsp not found. Installing via winget..." -ForegroundColor Yellow
    try {
        winget install WinFsp.WinFsp --accept-source-agreements --accept-package-agreements
        Write-Host "  WinFsp installed successfully." -ForegroundColor Green
        Write-Host "  NOTE: You may need to restart your terminal." -ForegroundColor Yellow
    } catch {
        Write-Host "  Failed to install WinFsp automatically." -ForegroundColor Red
        Write-Host "  Please install manually from: https://winfsp.dev/rel/" -ForegroundColor Red
    }
}

# Step 2: Install Python dependencies
Write-Host ""
Write-Host "[2/3] Installing Python dependencies..." -ForegroundColor Yellow

$corePackages = @(
    "fusepy",
    "pywin32",
    "sqlalchemy",
    "lz4",
    "networkx",
    "numpy",
    "rich",
    "pyyaml",
    "psutil"
)

foreach ($pkg in $corePackages) {
    Write-Host "  Installing $pkg..." -NoNewline
    python -m pip install $pkg --quiet 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host " OK" -ForegroundColor Green
    } else {
        Write-Host " FAILED" -ForegroundColor Red
    }
}

# Step 3: Optional sentence-transformers
Write-Host ""
Write-Host "[3/3] Optional: AI Embeddings" -ForegroundColor Yellow
Write-Host "  sentence-transformers enables semantic search but adds ~1GB download."
$response = Read-Host "  Install sentence-transformers? (y/N)"
if ($response -eq "y" -or $response -eq "Y") {
    Write-Host "  Installing sentence-transformers (this may take a while)..."
    python -m pip install sentence-transformers
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  sentence-transformers installed." -ForegroundColor Green
    } else {
        Write-Host "  Installation failed. Semantic search will be disabled." -ForegroundColor Yellow
    }
} else {
    Write-Host "  Skipped. Semantic search will be disabled." -ForegroundColor Yellow
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "  1. Format a test image:"
Write-Host "     python tools/format_device.py test.img --force"
Write-Host ""
Write-Host "  2. Mount to K: drive:"
Write-Host "     python tools/mount.py test.img K: --debug"
Write-Host ""
Write-Host "  3. Use the filesystem:"
Write-Host "     - Copy files to K:\"
Write-Host "     - Browse K:\.ai\ for AI features"
Write-Host ""
