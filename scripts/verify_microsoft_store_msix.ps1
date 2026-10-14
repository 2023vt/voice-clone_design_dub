param(
  [Parameter(Mandatory = $true)][string]$Package,
  [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$metadata = Get-Content (Join-Path $root 'store/metadata.json') -Raw | ConvertFrom-Json
$version = (Get-Content (Join-Path $root 'package.json') -Raw | ConvertFrom-Json).version
$expectedVersion = "$version.0"
$packagePath = (Resolve-Path $Package).Path
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("voicestudio-msix-" + [guid]::NewGuid())

New-Item -ItemType Directory -Path $temporary | Out-Null
try {
  & tar.exe -xf $packagePath -C $temporary
  if ($LASTEXITCODE -ne 0) { throw "Could not unpack MSIX: $LASTEXITCODE" }
  $manifestPath = Join-Path $temporary 'AppxManifest.xml'
  if (-not (Test-Path $manifestPath)) { throw 'MSIX is missing AppxManifest.xml' }
  [xml]$manifest = Get-Content $manifestPath -Raw
  $identity = $manifest.Package.Identity
  if ($identity.Name -ne $metadata.microsoftStore.identityName) {
    throw "Unexpected Identity.Name: $($identity.Name)"
  }
  if ($identity.Publisher -ne $metadata.microsoftStore.publisher) {
    throw "Unexpected Identity.Publisher: $($identity.Publisher)"
  }
  if ($identity.ProcessorArchitecture -ne 'x64') {
    throw "Unexpected architecture: $($identity.ProcessorArchitecture)"
  }
  if ($identity.Version -ne $expectedVersion) {
    throw "Unexpected package version: $($identity.Version), expected $expectedVersion"
  }
  if ($manifest.Package.Properties.PublisherDisplayName -ne $metadata.microsoftStore.publisherDisplayName) {
    throw "Unexpected PublisherDisplayName: $($manifest.Package.Properties.PublisherDisplayName)"
  }
  $capabilities = @($manifest.Package.Capabilities.ChildNodes | ForEach-Object { $_.Name })
  foreach ($required in @('runFullTrust', 'internetClient', 'privateNetworkClientServer', 'microphone')) {
    if ($capabilities -notcontains $required) { throw "MSIX is missing capability: $required" }
  }
  if (Test-Path (Join-Path $temporary 'AppxSignature.p7x')) {
    throw 'Partner Center artifact must remain unsigned so the Store can sign it'
  }
  $evidence = [ordered]@{
    schemaVersion = 1
    package = Split-Path -Leaf $packagePath
    identityName = $identity.Name
    publisher = $identity.Publisher
    publisherDisplayName = $manifest.Package.Properties.PublisherDisplayName
    packageVersion = $identity.Version
    architecture = $identity.ProcessorArchitecture
    packageFamilyName = $metadata.microsoftStore.packageFamilyName
    storeId = $metadata.microsoftStore.storeId
    capabilities = $capabilities
    signature = 'pending-microsoft-store'
  }
  $evidence | ConvertTo-Json -Depth 5 | Set-Content -Path $Output -Encoding utf8
} finally {
  Remove-Item -Recurse -Force $temporary -ErrorAction SilentlyContinue
}
