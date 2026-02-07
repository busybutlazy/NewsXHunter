備份workflow
```bash
docker compose exec -u node n8n n8n export:workflow --all --separate --output=/exports
```
＊docker內只讀的到docker內，因此要將備份資料夾在docker compose先掛載，再儲存
目前路徑 ./n8n_backups:./exportss

備份credentials
```bash
docker compose exec -u node n8n n8n export:credentials --all --separate --output=/exports
```
