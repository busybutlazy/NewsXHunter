# N8N操作筆記
### 備份
備份workflow
```bash
docker compose exec -u node n8n n8n export:workflow --all --separate --output=/exports/workflows
```
＊ docker內只讀的到docker內，因此要將備份資料夾在docker compose先掛載，再儲存
目前路徑 ./n8n_backups:./exportss

備份credentials
```bash
docker compose exec -u node n8n n8n export:credentials --all --separate --output=/exports/credentials
```
＊credentials讀取時，N8N_ENCRYPTION_KEY必須要相同，不然會失效。


### 匯入
匯入備份的n8n workflow 和 credentials
```bash
docker compose exec -u node n8n n8n import:workflows --separate --input=/exports/workflows/

docker compose exec -u node n8n n8n import:credentials --separate --input=/exports/credentials/
```
＊ 因為我是把./backups 映射到./export 所以--input後面擺/exports/*

