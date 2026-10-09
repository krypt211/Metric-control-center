function Assert-ProviderKeyFile([string]$TaskRoot) {
    $keyPath=Join-Path $TaskRoot '.secrets/provider_encryption_key'
    if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) { throw 'Provider encryption key missing. Recover the original key separately before startup/backup; SQL backups do not contain it.' }
    $encoded=[System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($keyPath)).Trim()
    if ($encoded -notmatch '^[A-Za-z0-9_-]{43}=$') { throw 'Provider encryption key invalid; do not overwrite it. Recover the original key.' }
    try { $decoded=[Convert]::FromBase64String($encoded.Replace('-','+').Replace('_','/')); if ($decoded.Length -ne 32) { throw 'invalid' } } catch { throw 'Provider encryption key invalid; recover the original key.' }
    $acl=Get-Acl -LiteralPath $keyPath
    $allowed=@([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value,'S-1-5-18','S-1-5-32-544')
    if (-not $acl.AreAccessRulesProtected) { throw 'Provider encryption key ACL inheritance must be disabled.' }
    foreach ($rule in $acl.Access) {
        $sid=$rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        if ($rule.IsInherited -or $sid -notin $allowed -or $rule.AccessControlType -ne 'Allow') { throw 'Provider encryption key ACL contains unexpected access.' }
    }
    Write-Host 'Provider encryption key presence/format/ACL: PASS (value not printed).'
}
