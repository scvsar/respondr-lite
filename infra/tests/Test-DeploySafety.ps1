$ErrorActionPreference = 'Stop'
$fixture = New-TemporaryFile
$previousAz = Get-Item Function:az -ErrorAction SilentlyContinue
$previousExitCode = $global:LASTEXITCODE

function global:az {
  $arguments = @($args)
  $global:LASTEXITCODE = 0
  if ($arguments[0] -eq 'deployment') {
    if ($arguments -contains '--debug') { throw 'Deployment must not enable debug logging.' }
    if (-not ($arguments -contains '--only-show-errors') -or -not ($arguments -contains 'none')) {
      throw 'Deployment output must be suppressed.'
    }
    $parameterArgument = $arguments | Where-Object { $_ -is [string] -and $_.StartsWith('@') } | Select-Object -First 1
    $global:deploySafetyState.ParameterPath = $parameterArgument.Substring(1)
    $parameters = Get-Content -LiteralPath $global:deploySafetyState.ParameterPath -Raw | ConvertFrom-Json
    $global:deploySafetyState.SecretPassed = $parameters.containerSecretMap.value.LOCAL_AUTH_SECRET_KEY -eq 'synthetic-private-signing-marker'
    if (-not $IsWindows) {
      $mode = [System.IO.File]::GetUnixFileMode($global:deploySafetyState.ParameterPath)
      $global:deploySafetyState.PrivateFile = $mode -eq ([System.IO.UnixFileMode]::UserRead -bor [System.IO.UnixFileMode]::UserWrite)
    }
    if ($global:deploySafetyState.Fail) { $global:LASTEXITCODE = 1 }
  }
}

try {
  Set-Content -LiteralPath $fixture.FullName -Value "ENABLE_LOCAL_AUTH=true`nLOCAL_AUTH_SECRET_KEY=synthetic-private-signing-marker"
  foreach ($failure in @($false, $true)) {
    $global:deploySafetyState = @{ Fail = $failure; ParameterPath = ''; SecretPassed = $false; PrivateFile = $IsWindows }
    $output = & (Join-Path $PSScriptRoot '..' 'deploy.ps1') `
      -ResourceGroup 'synthetic-rg' -StorageAccountName 'syntheticstorage' `
      -FunctionAppName 'synthetic-function' -Location 'eastus2' `
      -OpenAiName 'synthetic-openai' -OpenAiLocation 'eastus2' `
      -ContainerAppName 'synthetic-container' -ContainerImage 'example.test/synthetic:0' `
      -DotEnvPath $fixture.FullName *>&1
    $code = $LASTEXITCODE
    if ($failure -and $code -ne 1) { throw 'Deployment failure was not returned.' }
    if (-not $failure -and $code -ne 0) { throw 'Successful deployment returned an error.' }
    if (-not $global:deploySafetyState.SecretPassed) { throw 'Secure parameters did not reach the deployment command.' }
    if (-not $global:deploySafetyState.PrivateFile) { throw 'Deployment parameter permissions were too broad.' }
    if (Test-Path -LiteralPath $global:deploySafetyState.ParameterPath) { throw 'Deployment parameter file was not removed.' }
    if (($output | Out-String).Contains('synthetic-private-signing-marker')) { throw 'Deployment output exposed a secret.' }
  }
  Write-Output 'Deployment safety checks passed.'
}
finally {
  Remove-Item -LiteralPath $fixture.FullName -Force
  Remove-Item Function:az -ErrorAction SilentlyContinue
  if ($previousAz) { Set-Item Function:az $previousAz.ScriptBlock }
  Remove-Variable deploySafetyState -Scope Global -ErrorAction SilentlyContinue
  $global:LASTEXITCODE = $previousExitCode
}
