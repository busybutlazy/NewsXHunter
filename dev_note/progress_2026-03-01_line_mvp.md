# 2026-03-01 開發進度（LINE MVP + Agent骨架）

## 今日完成
- 完成 Cloudflare Tunnel 對外連線（網域可連到 raspi）。
- `edge_worker` 已新增 LINE webhook 路由並可成功回覆訊息。
- 已完成 LINE 簽章驗證（`X-Line-Signature`）。
- 已完成 webhook 事件處理：
  - `follow`：建立/啟用使用者並回歡迎訊息。
  - `unfollow`：將使用者設為非啟用。
  - `message(text)`：交給 `Lorekeeper` 回答後使用 LINE reply 回覆。
- 已建立 `Bard`/`Lorekeeper` 服務骨架與資料落庫骨架。
- 已建立/擴充資料表與 repo 層（含 agent run、問答配額、LINE 推播、RAG 空間預留）。

## 目前可用 API
- `POST /v1/rss/ingest/rawitem`：RSS raw item ingest（既有功能）。
- `POST /v1/agents/bard/push`：Bard 推播（會寫推播/agent 紀錄）。
- `POST /v1/agents/lorekeeper/ask`：Lorekeeper 問答（含每日 5 題限制）。
- `POST /v1/line/webhook`：LINE webhook（驗簽 + 事件處理）。
- `GET /healthz`：健康檢查。

## 關鍵檔案
- `db/init.sql`
- `edge_worker/app/api/v1/line_webhook.py`
- `edge_worker/app/services/line_messaging_service.py`
- `edge_worker/app/services/line_webhook_service.py`
- `edge_worker/app/services/bard_agent_service.py`
- `edge_worker/app/services/lorekeeper_agent_service.py`
- `edge_worker/app/adapters/repos/line_delivery_repo.py`
- `edge_worker/app/adapters/repos/user_query_repo.py`
- `edge_worker/app/adapters/repos/agent_run_repo.py`

## 今天遇到的問題與解法
1. `LINE Verify` 出現 404  
- 原因：服務未載入含 webhook 路由的新版本或 URL path 錯誤。  
- 檢查：`curl -X POST https://<domain>/v1/line/webhook -d '{}'` 不應該是 404（應為 401 或 200）。

2. webhook 進站後 500，錯誤 `relation "edge_ingest.line_webhook_events" does not exist`  
- 原因：Postgres 既有 volume 下，`init.sql` 不會自動重跑。  
- 解法：手動執行 SQL 檔。

## DB 手動同步指令（已驗證可用）
```bash
docker compose exec -T postgres psql -U edge -d edge -f /docker-entrypoint-initdb.d/01_init.sql
docker compose exec -T postgres psql -U edge -d edge -c "\dt edge_ingest.line_webhook_events"
```

## Tunnel / 網路狀態確認指令
```bash
cloudflared tunnel list
curl -i https://linebot.busybutlazy.online/healthz
```

## 下次接續待辦（優先順序）
1. 完成 LINE 失敗重試機制（push/reply 失敗重送 + 次數上限）。
2. 補 dead-letter / 失敗事件追蹤表（或沿用既有 log 表做策略）。
3. 強化 webhook idempotency（目前已用 `line_webhook_events` 去重）。
4. 補 webhook 行為測試（follow/message/unfollow）。
5. 接 Arango 真正向量 RAG（目前 `Lorekeeper` 為 placeholder 檢索）。
6. Graph RAG 先保留 schema，後續再實作查詢路徑。

## 目前限制（重要）
- `Lorekeeper` 的 RAG 還沒接 Arango 實體檢索（目前只保留接口/欄位/placeholder）。
- LINE 功能目前是 MVP，可用但尚未有完整重試與營運級監控。

## 安全備註
- 今日對話中曾暴露過金鑰字串，建議盡快輪替：
  - `OPENAI_API_KEY`
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - 必要時 `LINE_CHANNEL_SECRET`
