import asyncio
import httpx
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

url = "https://indodax.com/api/v2/chatroom/history"
WIB_OFFSET = 7 * 3600
history = []
seen_ids = set()
active_connections = set()

async def polling_chat():
    global history
    print("Polling chat Indodax aktif...")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await client.get(url)
                data = response.json()
                updated = False
                if data.get("success"):
                    chat_list = data["data"]["content"]
                    for chat in chat_list:
                        if chat['id'] not in seen_ids:
                            seen_ids.add(chat['id'])
                            ts = chat["timestamp"]
                            chat_time = datetime.utcfromtimestamp(ts + WIB_OFFSET).strftime('%Y-%m-%d %H:%M:%S')
                            chat["timestamp_wib"] = chat_time
                            history.append(chat)
                            updated = True
                    history[:] = history[-1000:]
                else:
                    print("Gagal ambil data dari API.")
                # Jika ada update, broadcast ke semua client websocket
                if updated and active_connections:
                    msg = json.dumps({"history": history[-1000:]})
                    to_remove = set()
                    for ws in list(active_connections):
                        try:
                            await ws.send_text(msg)
                        except Exception as e:
                            print("Harap refresh broo!:", e)
                            to_remove.add(ws)
                    for ws in to_remove:
                        active_connections.remove(ws)
            except Exception as e:
                print("Error polling:", e)
            await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(polling_chat())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def websocket_page():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Chatroom</title>
        <link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css"/>
        <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
        <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
        <style>
            body { font-family: Arial, sans-serif; margin: 8px; padding: 0; }
            table.dataTable thead th { font-weight: bold; border-bottom: 2px solid #ddd; }
            table.dataTable { border-bottom: 2px solid #ddd; }
            .level-0 { color: #000000 !important; }
            .level-1 { color: #CD7F32 !important; }
            .level-2 { color: #FFA500 !important; }
            .level-3 { color: #0000FF !important; }
            .level-4 { color: #32CD32 !important; }
            .level-5 { color: #FF00FF !important; }
            th, td { vertical-align: top; }
            th:nth-child(1), td:nth-child(1) { width: 130px; min-width: 110px; max-width: 150px; white-space: nowrap; }
            th:nth-child(2), td:nth-child(2) { width: 120px; min-width: 90px; max-width: 150px; white-space: nowrap; }
            th:nth-child(3), td:nth-child(3) { width: auto; word-break: break-word; white-space: pre-line; }
            .header-chatroom { display: flex; align-items: center; justify-content: flex-start; gap: 20px; margin-top: 0; margin-left: 10px; padding-top: 0; }
            .header-chatroom a {color: red;}
        </style>
    </head>
    <body>
    <div class="header-chatroom">
        <h2>Chatroom Indodax</h2>
        <a>* Maksimal 1000 chat terakhir</a>
    </div>
    <table id="history" class="display" style="width:100%">
        <thead>
            <tr>
                <th>Waktu</th>
                <th>Username</th>
                <th>Chat</th>
            </tr>
        </thead>
        <tbody></tbody>
    </table>
    <script>
        var table = $('#history').DataTable({
            "order": [[0, "desc"]],
            "paging": false,
            "info": false,
            "searching": true,
            "language": {
                "emptyTable": "Belum ada chat"
            }
        });
    
        function updateTable(history) {
            table.clear();
            history.forEach(function(chat) {
                var level = chat.level || 0;
                var row = [
                    chat.timestamp_wib || "",
                    '<span class="level-' + level + '">' + (chat.username || "") + '</span>',
                    '<span class="level-' + level + '">' + (chat.content || "") + '</span>'
                ];
                table.row.add(row);
            });
            table.draw();
        }
    
        function connectWS() {
            var ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
            ws.onmessage = function(event) {
                var data = JSON.parse(event.data);
                if (!data.ping) updateTable(data.history);
            };
            ws.onclose = function() {
                setTimeout(connectWS, 1000);
            };
        }
        connectWS();
    </script>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        await websocket.send_text(json.dumps({"history": history[-1000:]}))
        while True:
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({"ping": True}))
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.remove(websocket)
