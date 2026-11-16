$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..' 'validate-deployment-config.ps1')

$enabled = @(@{ name = 'ENABLE_LOCAL_AUTH'; value = 'true' })
Assert-LocalAuthConfiguration -PlainEnv @() -SecretMap @{}
Assert-LocalAuthConfiguration -PlainEnv @(@{ name = 'ENABLE_LOCAL_AUTH'; value = 'false' }) -SecretMap @{}
Assert-LocalAuthConfiguration -PlainEnv $enabled -SecretMap @{ LOCAL_AUTH_SECRET_KEY = 'synthetic-signing-secret' }
Assert-LocalAuthConfiguration -PlainEnv $enabled -SecretMap @{ LOCAL_AUTH_SECRET_FALLBACK = 'synthetic-fallback-secret' }
Assert-LocalAuthConfiguration -PlainEnv $enabled -SecretMap @{ LOCAL_AUTH_SECRET_KEY = ''; LOCAL_AUTH_SECRET_FALLBACK = 'synthetic-fallback-secret' }

foreach ($secret in @($null, '', ' ', 'dev-local-secret-key', 'your-secret-key-change-this')) {
  $rejected = $false
  try {
    Assert-LocalAuthConfiguration -PlainEnv $enabled -SecretMap @{ LOCAL_AUTH_SECRET_KEY = $secret }
  }
  catch {
    $rejected = $true
  }
  if (-not $rejected) { throw 'Invalid signing configuration was accepted.' }
}

$scripts = @('deploy.ps1', 'validate-deployment-config.ps1', (Join-Path '..' 'deployment' 'deploy-from-scratch.ps1'))
foreach ($script in $scripts) {
  $tokens = $null
  $parseErrors = $null
  $path = Join-Path $PSScriptRoot '..' $script
  [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors) | Out-Null
  if ($parseErrors.Count -gt 0) { throw "PowerShell syntax validation failed: $script" }
}
Write-Output 'Deployment configuration checks passed.'
