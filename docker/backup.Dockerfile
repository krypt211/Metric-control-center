FROM postgres:16-alpine
RUN apk add --no-cache python3
COPY scripts/database_backup.py /opt/database_backup.py
ENTRYPOINT ["python3", "/opt/database_backup.py"]
