#!/usr/bin/env pwsh

param(
    [Parameter(Mandatory = $true)] [string]$ResourceGroup,
    [Parameter(Mandatory = $true)] [string]$StorageAccountName,
    [Parameter(Mandatory = $true)] [string]$FunctionAppName,
    [string]$Location = "eastus"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$scriptDir/main.bicep" `
    --parameters saName=$StorageAccountName functionAppName=$FunctionAppName location=$Location

