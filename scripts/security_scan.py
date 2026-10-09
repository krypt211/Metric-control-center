"""Basic secret/config regression scan; never print matched values."""
from pathlib import Path
import re,subprocess,sys
root=Path(__file__).resolve().parents[1]
p=subprocess.run(["git","ls-files","-z"],cwd=root,capture_output=True)
files=[root/f for f in p.stdout.decode().split("\0") if f] if p.returncode==0 else []
if not files:files=[f for folder in ("backend","services","frontend","scripts","docker") for f in (root/folder).rglob("*") if f.is_file()]
bad=[]
secret=re.compile(r"(?:mf_live_|mfk_)[A-Za-z0-9_-]{24,}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
for file in files:
    if ".secrets" in file.parts:bad.append(str(file.relative_to(root)))
    if any(part in (".secrets","node_modules",".next",".venv","__pycache__",".tools") for part in file.parts):continue
    if file.suffix not in (".py",".ts",".tsx",".yml",".yaml",".json",".md",".sh",".ps1",".env",".example"):continue
    content=file.read_text(encoding="utf-8",errors="replace")
    if any("fixture" not in m.group().lower() for m in secret.finditer(content)):bad.append(str(file.relative_to(root)))
    if file.is_relative_to(root/"frontend") and ("localStorage" in content or "Bearer " in content or "ACTION_API_TOKEN_FILE" in content):bad.append(str(file.relative_to(root)))
if bad:
    print("SECURITY_SCAN_FAILED:",",".join(sorted(set(bad))));sys.exit(1)
print("Basic source secret and frontend token scan: PASS")
