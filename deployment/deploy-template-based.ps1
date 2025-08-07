param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory = $true)]
    [string]$Domain,
    
    [string]$Location = "westus",
    [switch]$SkipInfrastructure,
    [switch]$SkipImageBuild,
    [bool]$UseOAuth2 = $true
)

Write-Host "🚀 Template-Based Respondr Deployment" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Yellow
Write-Host "Domain: $Domain" -ForegroundColor Yellow
Write-Host "Location: $Location" -ForegroundColor Yellow
Write-Host "Use OAuth2: $UseOAuth2" -ForegroundColor Yellow
Write-Host ""

# Step 1: Generate values from current environment
Write-Host "📋 Step 1: Generating configuration from current Azure environment..." -ForegroundColor Green
& ".\generate-values.ps1" -ResourceGroupName $ResourceGroupName -Domain $Domain
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to generate values from environment"
    exit 1
}

# Step 2: Infrastructure deployment (if not skipped)
if (-not $SkipInfrastructure) {
    Write-Host "🏗️  Step 2: Deploying Azure infrastructure..." -ForegroundColor Green
    & ".\deploy-complete.ps1" -ResourceGroupName $ResourceGroupName -Domain $Domain -Location $Location -UseOAuth2:$UseOAuth2
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Infrastructure deployment failed"
        exit 1
    }
} else {
    Write-Host "⏭️  Step 2: Skipping infrastructure deployment" -ForegroundColor Yellow
}

# Step 3: Generate secrets from template
Write-Host "🔐 Step 3: Generating secrets from template..." -ForegroundColor Green
& ".\create-secrets.ps1" -ResourceGroupName $ResourceGroupName
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to generate secrets"
    exit 1
}

# Step 4: Setup OAuth2 (if enabled)
if ($UseOAuth2) {
    Write-Host "🔒 Step 4: Setting up OAuth2 authentication..." -ForegroundColor Green
    & ".\setup-oauth2.ps1" -ResourceGroupName $ResourceGroupName -Domain $Domain
    if ($LASTEXITCODE -ne 0) {
        Write-Error "OAuth2 setup failed"
        exit 1
    }
} else {
    Write-Host "⏭️  Step 4: Skipping OAuth2 setup" -ForegroundColor Yellow
}

# Step 5: Generate deployment files from templates
Write-Host "📝 Step 5: Generating deployment files from templates..." -ForegroundColor Green

# Choose the appropriate template based on OAuth2 setting
if ($UseOAuth2) {
    $templateFile = "respondr-k8s-oauth2-template.yaml"
    $outputFile = "respondr-k8s-generated.yaml"
} else {
    Write-Error "Non-OAuth2 deployment not yet supported in template system"
    exit 1
}

& ".\process-template.ps1" -TemplateFile $templateFile -OutputFile $outputFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to generate deployment file from template"
    exit 1
}

# Step 6: Deploy to Kubernetes
Write-Host "☸️  Step 6: Deploying to Kubernetes..." -ForegroundColor Green

# Deploy Redis first
kubectl apply -f redis-deployment.yaml
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to deploy Redis"
    exit 1
}

# Deploy application
kubectl apply -f $outputFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to deploy application"
    exit 1
}

# Wait for deployment
Write-Host "⏳ Waiting for deployment to be ready..." -ForegroundColor Yellow
kubectl rollout status deployment/respondr-deployment -n respondr --timeout=300s

# Step 7: Verification
Write-Host "✅ Step 7: Verifying deployment..." -ForegroundColor Green
if ($UseOAuth2) {
    & ".\verify-oauth2-deployment.ps1" -Domain $Domain
} else {
    Write-Host "Manual verification required for non-OAuth2 deployment" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "🎉 Template-based deployment completed!" -ForegroundColor Green
Write-Host "📋 Generated files (not committed to git):" -ForegroundColor Cyan
Write-Host "   - values.yaml (environment configuration)" -ForegroundColor White
Write-Host "   - secrets.yaml (Kubernetes secrets)" -ForegroundColor White
Write-Host "   - $outputFile (generated deployment)" -ForegroundColor White
Write-Host ""
Write-Host "🔗 Your application is available at: https://respondr.$Domain" -ForegroundColor Green
Write-Host ""
Write-Host "⚠️  IMPORTANT: All generated files are in .gitignore and should never be committed!" -ForegroundColor Yellow
