function Assert-LocalAuthConfiguration {
  param([array]$PlainEnv, [hashtable]$SecretMap)

  $localAuthEnabled = @($plainEnv | Where-Object { $_.name -eq 'ENABLE_LOCAL_AUTH' } | ForEach-Object { $_.value }) -icontains 'true'
  if ($localAuthEnabled) {
    $localAuthSecret = $secretMap['LOCAL_AUTH_SECRET_KEY']
    if ([string]::IsNullOrEmpty($localAuthSecret)) {
      $localAuthSecret = $secretMap['LOCAL_AUTH_SECRET_FALLBACK']
    }
    if ([string]::IsNullOrWhiteSpace($localAuthSecret) -or $localAuthSecret -in @('dev-local-secret-key', 'your-secret-key-change-this')) {
      throw 'Local authentication requires a configured signing secret.'
    }
  }
}
