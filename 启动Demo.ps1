$ErrorActionPreference = "Stop"

$workspaceRoot = $PSScriptRoot
$backendRoot = Join-Path $workspaceRoot "backend_api"
$frontendRoot = Join-Path $workspaceRoot "demo_web"
$pythonPath = Join-Path $backendRoot ".venv\Scripts\python.exe"
$backendEnvPath = Join-Path $backendRoot ".env"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "未找到后端虚拟环境，请先按 backend_api\README.md 安装依赖。"
}

if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules"))) {
    throw "未找到前端依赖，请先在 demo_web 目录运行 npm install。"
}

$backendRunning = Test-NetConnection -ComputerName "127.0.0.1" -Port 8000 -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $backendRunning) {
    $backendArguments = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
    if (Test-Path -LiteralPath $backendEnvPath) {
        $backendArguments += @("--env-file", ".env")
    }
    Start-Process -FilePath $pythonPath `
        -ArgumentList $backendArguments `
        -WorkingDirectory $backendRoot `
        -WindowStyle Hidden
}

$frontendRunning = Test-NetConnection -ComputerName "127.0.0.1" -Port 9001 -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $frontendRunning) {
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "dev" `
        -WorkingDirectory $frontendRoot `
        -WindowStyle Hidden
}

Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:9001"
