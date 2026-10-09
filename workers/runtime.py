"""Celery supervision, expiring heartbeats and safe structured logs."""
import json,os,re,signal,subprocess,sys,threading,time
from datetime import datetime,timezone
from redis import Redis
def emit(service,level,event,request_id=None):
    print(json.dumps({"timestamp":datetime.now(timezone.utc).isoformat(),"service":service,
        "level":level,"event":event,"request_id":request_id,
        "error_code":"WORKER_OPERATION_FAILED" if level=="ERROR" else None}),flush=True)
def main():
    mode=sys.argv[1] if len(sys.argv)>1 else ""
    if mode not in ("worker","scheduler"):raise SystemExit(2)
    if os.environ.get("LOCAL_READ_ONLY")!="true" or os.environ.get("ACTIONS_ENABLED")!="false":
        raise SystemExit("READ_ONLY_REQUIRED")
    cmd=["celery","-A","workers.ingestion:app"]
    cmd+=["worker","-Q","ingestion","--loglevel=INFO","--concurrency=2"] if mode=="worker" else ["beat","--schedule=/tmp/beat-schedule","--loglevel=INFO"]
    child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    def output():
        for line in child.stdout:
            level="ERROR" if re.search(r"\b(ERROR|CRITICAL)\b",line) else "INFO"
            identifier=re.search(r"\[([a-f0-9-]{36})\]",line)
            event="task_finished" if "succeeded" in line else "task_received" if "received" in line else "service_output"
            emit(mode,level,event,identifier.group(1) if identifier else None)
    threading.Thread(target=output,daemon=True).start()
    def stop(signum,frame):child.terminate()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    client=Redis.from_url(os.environ["CELERY_BROKER_URL"],socket_timeout=2,socket_connect_timeout=2)
    emit(mode,"INFO","started")
    try:
        while child.poll() is None:
            try:client.set("mcc:heartbeat:"+mode,str(int(time.time())),ex=45)
            except Exception:emit(mode,"ERROR","HEARTBEAT_UNAVAILABLE")
            time.sleep(2)
    finally:
        try:client.delete("mcc:heartbeat:"+mode)
        except Exception:pass
        client.close()
    raise SystemExit(child.returncode or 0)
if __name__=="__main__":main()
