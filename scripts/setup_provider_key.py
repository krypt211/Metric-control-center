"""Provision a separate key; preserve existing keys and protect a new file before writing."""
import base64,os,secrets,subprocess
from pathlib import Path

def protect_new_file(target):
    if os.name!='nt':
        target.chmod(0o444)
        return
    script="""
$ErrorActionPreference='Stop'
$target=[System.IO.Path]::GetFullPath($env:MFC_NEW_PROVIDER_KEY)
$acl=[System.Security.AccessControl.FileSecurity]::new()
$acl.SetAccessRuleProtection($true,$false)
$current=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.SetOwner($current)
foreach($sid in @($current,[System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))){
  $rule=[System.Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow')
  $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $target -AclObject $acl
"""
    env={**os.environ,'MFC_NEW_PROVIDER_KEY':str(target.resolve())}
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=env,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise SystemExit('New key permissions failed; key material was not written')

def main():
    root=Path(__file__).resolve().parents[1]
    directory=root/'.secrets';directory.mkdir(mode=0o700,exist_ok=True)
    target=directory/'provider_encryption_key'
    if target.exists():
        try:
            from cryptography.fernet import Fernet
            Fernet(target.read_bytes().strip())
        except Exception:raise SystemExit('Existing provider key is invalid; not overwritten') from None
        print('Provider encryption key already configured; preserved.')
        return
    with target.open('x',encoding='ascii') as f:
        protect_new_file(target)
        f.write(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    print('Separate provider encryption key created. Value not printed.')
if __name__=='__main__':main()
