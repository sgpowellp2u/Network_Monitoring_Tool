# setup_venv.ps1
$venvPath = ".venv"

if (-Not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment..."
    python -m venv $venvPath
} else {
    Write-Host "Virtual environment already exists."
}

# Activate the virtual environment
Write-Host "Activating virtual environment..."
& "$venvPath\Scripts\Activate.ps1"

# Upgrade pip
python -m pip install --upgrade pip
Write-Host "Setup complete. Virtual environment is active."
