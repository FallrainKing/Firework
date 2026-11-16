# Backup container: busybox crond runs /ops/backup.sh daily at 02:00 (Asia/Shanghai).
FROM alpine:3.20

RUN apk add --no-cache sqlite curl jq tzdata

COPY backup.sh /ops/backup.sh
RUN chmod +x /ops/backup.sh \
    && printf 'TZ=Asia/Shanghai\n0 2 * * * /ops/backup.sh >> /backups/backup.log 2>&1\n' | crontab -

CMD ["crond", "-f", "-l", "2"]
