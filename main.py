import sqlite3
import uvicorn
import os
import uuid
import shutil
import sys
import threading
import time
import webview
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

# --- 1. 环境与绝对路径初始化 (打包为 EXE 后的防丢数据核心逻辑) ---
if getattr(sys, 'frozen', False):
    # 如果是打包后的 EXE 运行，根目录定为 EXE 所在的真实物理目录
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是 Python 脚本运行，根目录定为脚本所在目录
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DB_FILE = os.path.join(BASE_DIR, "todo_calendar.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                all_day BOOLEAN DEFAULT 1,
                is_completed BOOLEAN DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS eval_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module TEXT NOT NULL,
                sub_module TEXT NOT NULL,
                title TEXT NOT NULL,
                score REAL NOT NULL,
                record_date TEXT,          
                proof_path TEXT
            )
        ''')

        cursor.execute("PRAGMA table_info(eval_records)")
        eval_columns = [info[1] for info in cursor.fetchall()]
        if "record_date" not in eval_columns:
            cursor.execute("ALTER TABLE eval_records ADD COLUMN record_date TEXT")

        cursor.execute("PRAGMA table_info(tasks)")
        task_columns = [info[1] for info in cursor.fetchall()]
        if "color_hex" not in task_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN color_hex TEXT DEFAULT '#4F46E5'")

        conn.commit()


init_db()

app = FastAPI(title="SDAU 软院效率中枢 桌面版")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# --- 2. 日历 API ---
class TaskCreate(BaseModel):
    title: str
    start_date: str
    end_date: Optional[str] = None
    all_day: bool = True
    color_hex: str = "#4F46E5"


class TaskTimeUpdate(BaseModel):
    start_date: str
    end_date: Optional[str] = None
    all_day: bool = True


class TaskEditUpdate(BaseModel):
    title: str
    color_hex: str


@app.get("/api/tasks")
def get_tasks():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks")
        rows = cursor.fetchall()
        events = []
        for row in rows:
            color = "#10B981" if row["is_completed"] else (row["color_hex"] or "#4F46E5")
            events.append({
                "id": row["id"],
                "title": row["title"],
                "start": row["start_date"],
                "end": row["end_date"],
                "allDay": bool(row["all_day"]),
                "backgroundColor": color,
                "borderColor": color,
                "extendedProps": {
                    "is_completed": bool(row["is_completed"]),
                    "raw_color": row["color_hex"] or "#4F46E5"
                }
            })
        return events


@app.post("/api/tasks")
def create_task(task: TaskCreate):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tasks (title, start_date, end_date, all_day, color_hex) VALUES (?, ?, ?, ?, ?)",
                       (task.title, task.start_date, task.end_date, task.all_day, task.color_hex))
        conn.commit()
        return {"id": cursor.lastrowid}


@app.put("/api/tasks/{task_id}")
def update_task_time(task_id: int, task: TaskTimeUpdate):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE tasks SET start_date=?, end_date=?, all_day=? WHERE id=?",
                       (task.start_date, task.end_date, task.all_day, task_id))
        conn.commit()
        return {"status": "success"}


@app.patch("/api/tasks/{task_id}/edit")
def update_task_details(task_id: int, payload: TaskEditUpdate):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE tasks SET title=?, color_hex=? WHERE id=?", (payload.title, payload.color_hex, task_id))
        conn.commit()
        return {"status": "success"}


@app.patch("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE tasks SET is_completed = NOT is_completed WHERE id=?", (task_id,))
        conn.commit()
        return {"status": "success"}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
        return {"status": "success"}


# --- 3. 综测 API ---
@app.post("/api/eval")
async def create_eval_record(
        module: str = Form(...),
        sub_module: str = Form(...),
        title: str = Form(...),
        score: float = Form(...),
        record_date: str = Form(...),
        file: Optional[UploadFile] = File(None)
):
    proof_path = ""
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        proof_path = f"/uploads/{unique_filename}"

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO eval_records (module, sub_module, title, score, record_date, proof_path) VALUES (?, ?, ?, ?, ?, ?)",
            (module, sub_module, title, score, record_date, proof_path)
        )
        conn.commit()
    return {"status": "success"}


@app.put("/api/eval/{record_id}")
async def update_eval_record(
        record_id: int,
        module: str = Form(...),
        sub_module: str = Form(...),
        title: str = Form(...),
        score: float = Form(...),
        record_date: str = Form(...),
        file: Optional[UploadFile] = File(None)
):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        if file and file.filename:
            cursor.execute("SELECT proof_path FROM eval_records WHERE id=?", (record_id,))
            old = cursor.fetchone()
            if old and old[0] and os.path.exists(os.path.join(BASE_DIR, old[0].lstrip("/uploads/"))):
                try:
                    os.remove(os.path.join(BASE_DIR, old[0].lstrip("/uploads/")))
                except:
                    pass

            ext = os.path.splitext(file.filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{ext}"
            file_path = os.path.join(UPLOAD_DIR, unique_filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            proof_path = f"/uploads/{unique_filename}"
            cursor.execute(
                "UPDATE eval_records SET module=?, sub_module=?, title=?, score=?, record_date=?, proof_path=? WHERE id=?",
                (module, sub_module, title, score, record_date, proof_path, record_id))
        else:
            cursor.execute("UPDATE eval_records SET module=?, sub_module=?, title=?, score=?, record_date=? WHERE id=?",
                           (module, sub_module, title, score, record_date, record_id))
        conn.commit()
    return {"status": "success"}


@app.get("/api/eval")
def get_eval_records():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM eval_records ORDER BY record_date DESC, id DESC")
        return [dict(row) for row in cursor.fetchall()]


@app.delete("/api/eval/{record_id}")
def delete_eval_record(record_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT proof_path FROM eval_records WHERE id=?", (record_id,))
        row = cursor.fetchone()
        if row and row[0]:
            target_file = os.path.join(BASE_DIR, row[0].lstrip("/uploads/"))
            if os.path.exists(target_file):
                try:
                    os.remove(target_file)
                except:
                    pass
        cursor.execute("DELETE FROM eval_records WHERE id=?", (record_id,))
        conn.commit()
    return {"status": "success"}


# --- 4. 前端界面 HTML ---
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>SDAU 软院效率中枢</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js"></script>
    <style>
        .fc-theme-standard .fc-scrollgrid { border-color: #e5e7eb; }
        .fc-col-header-cell { background-color: #f9fafb; padding: 8px 0; font-weight: 600; text-align: center; }
        .fc-event { cursor: pointer; border-radius: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); height: auto !important; margin-bottom: 2px !important;}
        .fc-event-title { white-space: normal !important; word-break: break-word !important; line-height: 1.5 !important; padding: 4px 6px !important; font-size: 0.9rem;}

        .tab-active { border-bottom: 3px solid #1E40AF; color: #1E3A8A; font-weight: 800; }
        .tab-inactive { color: #6B7280; }

        .tag-jichu { background-color: #DBEAFE; color: #1E40AF; border: 1px solid #BFDBFE; }
        .tag-chengguo { background-color: #FEF3C7; color: #92400E; border: 1px solid #FDE68A; }

        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }

        input[type="color"]::-webkit-color-swatch-wrapper { padding: 0; }
        input[type="color"]::-webkit-color-swatch { border: none; border-radius: 8px; box-shadow: inset 0 0 0 1px rgba(0,0,0,0.1); }

        /* 防止选中文字导致拖拽异常 */
        body { user-select: none; }
        input, textarea { user-select: text; }
    </style>
</head>
<body class="bg-slate-50 text-slate-900 h-screen flex flex-col font-sans">

    <header class="bg-white border-b shadow-sm sticky top-0 z-40" style="-webkit-app-region: drag;">
        <div class="max-w-7xl mx-auto px-6 py-4 flex flex-col items-center">
            <h1 class="text-3xl font-black text-slate-800 tracking-tighter mb-4">SDAU 软院效率平台</h1>
            <div class="flex space-x-12 text-lg" style="-webkit-app-region: no-drag;">
                <button id="tab-cal" class="pb-2 px-4 tab-active transition-all" onclick="switchTab('cal')">📅 日程对齐</button>
                <button id="tab-eval" class="pb-2 px-4 tab-inactive transition-all" onclick="switchTab('eval')">🏆 综测备忘</button>
            </div>
        </div>
    </header>

    <main class="flex-1 overflow-hidden relative max-w-7xl mx-auto w-full">
        <div id="view-cal" class="h-full w-full p-6 absolute inset-0">
            <div class="bg-white rounded-2xl shadow-sm border p-6 h-full" id="calendar"></div>
        </div>

        <div id="view-eval" class="h-full w-full p-6 absolute inset-0 hidden overflow-y-auto">
            <div class="bg-indigo-900 text-white rounded-2xl p-8 mb-8 flex flex-col items-center shadow-xl relative overflow-hidden">
                <div class="absolute inset-0 bg-gradient-to-r from-blue-600/20 to-purple-600/20 z-0"></div>
                <span class="text-indigo-200 text-sm font-bold uppercase tracking-widest mb-2 z-10">本学年素质能力总分</span>
                <div class="flex items-baseline space-x-2 z-10">
                    <div class="text-7xl font-black" id="total-score">0.000</div>
                    <div class="text-3xl font-bold text-indigo-300">/ 100</div>
                </div>
                <div class="mt-6 flex space-x-4 z-10">
                    <button onclick="openEvalModal()" class="bg-white text-indigo-900 px-8 py-2.5 rounded-full font-bold hover:bg-indigo-50 transition shadow-lg">+ 添加全局条目</button>
                </div>
            </div>
            <div id="modules-grid" class="space-y-8 pb-12"></div>
        </div>
    </main>

    <div id="task-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm hidden flex justify-center items-center z-50">
        <div class="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
            <h3 id="task-modal-title" class="text-xl font-bold mb-4 text-slate-800 border-b pb-2">日程信息</h3>
            <input type="hidden" id="t-id"><input type="hidden" id="t-start"><input type="hidden" id="t-end"><input type="hidden" id="t-allday">

            <div class="mb-4">
                <label class="block text-xs font-bold text-slate-500 uppercase mb-1">待办内容</label>
                <textarea id="t-title" rows="3" class="w-full border-2 rounded-xl p-3 bg-slate-50 focus:border-indigo-500 outline-none resize-none"></textarea>
            </div>
            <div class="mb-6 flex justify-between items-center bg-slate-50 p-3 rounded-xl border-2 border-transparent">
                <label class="text-sm font-bold text-slate-700">标记颜色</label>
                <div class="flex items-center space-x-2">
                    <input type="color" id="t-color" value="#4F46E5" class="w-10 h-10 rounded cursor-pointer border-0 bg-transparent">
                </div>
            </div>
            <div class="flex flex-col space-y-2">
                <button onclick="saveTask()" class="w-full bg-indigo-600 text-white py-3 rounded-xl font-bold shadow-md hover:bg-indigo-700">保存日程</button>
                <div id="task-actions" class="hidden grid-cols-2 gap-2 mt-2">
                    <button onclick="toggleTask()" id="btn-toggle" class="bg-emerald-100 text-emerald-800 py-2 rounded-xl font-bold">标记完成</button>
                    <button onclick="deleteTask()" class="bg-rose-100 text-rose-800 py-2 rounded-xl font-bold">删除</button>
                </div>
                <button onclick="closeTaskModal()" class="w-full py-2 font-bold text-slate-400">取消</button>
            </div>
        </div>
    </div>

    <div id="eval-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm hidden flex justify-center items-center z-50">
        <div class="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-8">
            <h3 id="eval-modal-title" class="text-2xl font-bold mb-6 text-slate-800">新增加分项</h3>
            <form id="eval-form" onsubmit="handleEvalSubmit(event)">
                <input type="hidden" id="f-id">
                <div class="grid grid-cols-2 gap-4 mb-4">
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">模块</label>
                        <select id="f-module" class="w-full border-2 rounded-xl p-3 bg-slate-50 focus:border-indigo-500 outline-none font-bold text-indigo-900">
                            <option value="身心">身心素养</option><option value="文艺">文艺素养</option>
                            <option value="劳动">劳动素养</option><option value="创新">创新素养</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">类别</label>
                        <select id="f-sub" class="w-full border-2 rounded-xl p-3 bg-slate-50 focus:border-indigo-500 outline-none">
                            <option value="基础">基础性评价</option><option value="成果">成果性评价</option><option value="突破">突破性 (创新专享)</option>
                        </select>
                    </div>
                </div>
                <div class="mb-4">
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">项目标题</label>
                    <input type="text" id="f-title" class="w-full border-2 rounded-xl p-3 bg-slate-50 focus:border-indigo-500 outline-none" required>
                </div>
                <div class="grid grid-cols-2 gap-4 mb-4">
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">分值 (0.001精度)</label>
                        <input type="number" step="0.001" id="f-score" class="w-full border-2 rounded-xl p-3 bg-slate-50 focus:border-indigo-500 outline-none" required>
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">记录日期</label>
                        <input type="date" id="f-date" class="w-full border-2 rounded-xl p-3 bg-slate-50 focus:border-indigo-500 outline-none" required>
                    </div>
                </div>
                <div class="mb-6">
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">证明材料图片</label>
                    <input type="file" id="f-file" accept="image/*" class="text-sm block w-full file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:bg-indigo-50 file:text-indigo-700">
                </div>
                <div class="flex justify-end space-x-4">
                    <button type="button" onclick="closeEvalModal()" class="px-6 py-2 font-bold text-slate-400">取消</button>
                    <button type="submit" class="bg-indigo-600 text-white px-8 py-2 rounded-xl font-bold shadow-lg">保存更改</button>
                </div>
            </form>
        </div>
    </div>

    <div id="img-preview" class="fixed inset-0 bg-black/90 hidden z-[60] flex items-center justify-center p-8" onclick="this.classList.add('hidden')">
        <img id="preview-src" src="" class="max-w-full max-h-full rounded-lg shadow-2xl">
    </div>

    <script>
        let calendar;
        const MODS = {
            "身心": { max: 15, limits: {"基础":9, "成果":6} }, "文艺": { max: 15, limits: {"基础":9, "成果":6} },
            "劳动": { max: 25, limits: {"基础":15, "成果":10} }, "创新": { max: 45, limits: {"基础":5, "突破":40} }
        };

        function switchTab(t) {
            const isCal = t === 'cal';
            document.getElementById('view-cal').classList.toggle('hidden', !isCal);
            document.getElementById('view-eval').classList.toggle('hidden', isCal);
            document.getElementById('tab-cal').className = isCal ? "pb-2 px-4 tab-active transition-all" : "pb-2 px-4 tab-inactive transition-all";
            document.getElementById('tab-eval').className = !isCal ? "pb-2 px-4 tab-active transition-all" : "pb-2 px-4 tab-inactive transition-all";
            if(isCal) { if(calendar) calendar.render(); } 
            else { loadEval(); }
        }

        function closeTaskModal() { document.getElementById('task-modal').classList.add('hidden'); }

        async function saveTask() {
            const id = document.getElementById('t-id').value;
            const title = document.getElementById('t-title').value.trim();
            const color = document.getElementById('t-color').value;
            if(!title) return alert("待办内容不能为空！");
            if(id) {
                await fetch(`/api/tasks/${id}/edit`, {
                    method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title: title, color_hex: color})
                });
            } else {
                const start = document.getElementById('t-start').value;
                const end = document.getElementById('t-end').value;
                const allday = document.getElementById('t-allday').value === 'true';
                await fetch('/api/tasks', { 
                    method: 'POST', headers: {'Content-Type':'application/json'}, 
                    body: JSON.stringify({title: title, start_date: start, end_date: end || null, all_day: allday, color_hex: color})
                });
            }
            closeTaskModal(); calendar.refetchEvents();
        }

        async function toggleTask() {
            const id = document.getElementById('t-id').value;
            await fetch(`/api/tasks/${id}/toggle`, {method:'PATCH'});
            closeTaskModal(); calendar.refetchEvents();
        }

        async function deleteTask() {
            if(confirm('彻底删除？')) {
                const id = document.getElementById('t-id').value;
                await fetch(`/api/tasks/${id}`, {method:'DELETE'});
                closeTaskModal(); calendar.refetchEvents();
            }
        }

        document.addEventListener('DOMContentLoaded', function() {
            calendar = new FullCalendar.Calendar(document.getElementById('calendar'), {
                initialView: 'dayGridMonth',
                headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek' },
                events: '/api/tasks', editable: true, selectable: true,
                select: function(info) {
                    document.getElementById('t-id').value = ''; document.getElementById('t-title').value = '';
                    document.getElementById('t-color').value = '#4F46E5'; 
                    document.getElementById('t-start').value = info.startStr; document.getElementById('t-end').value = info.endStr;
                    document.getElementById('t-allday').value = info.allDay;
                    document.getElementById('task-modal-title').innerText = '新建日程';
                    document.getElementById('task-actions').classList.add('hidden'); document.getElementById('task-actions').classList.remove('grid');
                    document.getElementById('task-modal').classList.remove('hidden');
                },
                eventDrop: async (info) => {
                    await fetch(`/api/tasks/${info.event.id}`, {
                        method: 'PUT', headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({start_date:info.event.startStr, end_date:info.event.endStr||null, all_day:info.event.allDay})
                    });
                },
                eventClick: function(info) {
                    document.getElementById('t-id').value = info.event.id;
                    document.getElementById('t-title').value = info.event.title;
                    document.getElementById('t-color').value = info.event.extendedProps.raw_color; 
                    document.getElementById('task-modal-title').innerText = '编辑日程';
                    const btnToggle = document.getElementById('btn-toggle');
                    if(info.event.extendedProps.is_completed) {
                        btnToggle.innerText = "恢复为未完成"; btnToggle.className = "bg-amber-100 text-amber-800 py-2 rounded-xl font-bold";
                    } else {
                        btnToggle.innerText = "标记为完成"; btnToggle.className = "bg-emerald-100 text-emerald-800 py-2 rounded-xl font-bold";
                    }
                    document.getElementById('task-actions').classList.remove('hidden'); document.getElementById('task-actions').classList.add('grid');
                    document.getElementById('task-modal').classList.remove('hidden');
                }
            });
            calendar.render();
        });

        async function loadEval() {
            const res = await fetch('/api/eval'); const records = await res.json();
            const grid = document.getElementById('modules-grid'); grid.innerHTML = '';
            let total = 0;
            Object.entries(MODS).forEach(([name, cfg]) => {
                const recs = records.filter(r => r.module === name);
                let leftSum = recs.filter(r => r.sub_module === '基础').reduce((s,r)=>s+r.score, 0);
                let rightVal = 0;
                if(name === '创新') rightVal = recs.filter(r => r.sub_module === '突破').reduce((s,r)=>s+r.score, 0);
                else rightVal = recs.filter(r => r.sub_module === '成果').reduce((s,r)=>s+r.score, 0);

                const leftFinal = Math.min(leftSum, cfg.limits["基础"]);
                const rightFinal = Math.min(rightVal, cfg.limits[name==='创新'?'突破':'成果']);
                const modScore = leftFinal + rightFinal; total += modScore;

                grid.innerHTML += `
                <div class="bg-white rounded-3xl border shadow-sm overflow-hidden">
                    <div class="bg-slate-50 px-8 py-5 flex justify-between items-center border-b">
                        <div class="flex items-center space-x-4">
                            <h4 class="text-xl font-bold text-slate-800">${name}素养</h4>
                            <button onclick="openEvalModal('${name}')" class="text-xs bg-indigo-100 text-indigo-700 px-3 py-1.5 rounded-full font-bold">+ 添加活动</button>
                        </div>
                        <div class="flex items-baseline space-x-1">
                            <div class="text-3xl font-black text-indigo-600 tracking-tight">${modScore.toFixed(3)}</div>
                            <div class="text-lg font-bold text-slate-400">/ ${cfg.max}</div>
                        </div>
                    </div>
                    <div class="grid grid-cols-2 divide-x">
                        <div class="p-6">
                            <div class="flex justify-between items-center mb-4">
                                <span class="px-3 py-1 rounded-full text-xs font-bold tag-jichu">基础性评价</span>
                                <span class="text-xs font-bold text-slate-400">小计: ${leftFinal.toFixed(3)} / ${cfg.limits["基础"]}</span>
                            </div>
                            <div class="space-y-3">${renderEvalItems(recs.filter(r=>r.sub_module==='基础'))}</div>
                        </div>
                        <div class="p-6">
                            <div class="flex justify-between items-center mb-4">
                                <span class="px-3 py-1 rounded-full text-xs font-bold tag-chengguo">${name==='创新'?'突破性评价':'成果性评价'}</span>
                                <span class="text-xs font-bold text-slate-400">小计: ${rightFinal.toFixed(3)} / ${cfg.limits[name==='创新'?'突破':'成果']}</span>
                            </div>
                            <div class="space-y-3">${renderEvalItems(recs.filter(r=>r.sub_module!=='基础'))}</div>
                        </div>
                    </div>
                </div>`;
            });
            document.getElementById('total-score').innerText = Math.min(total, 100).toFixed(3);
        }

        function renderEvalItems(items) {
            if(!items.length) return `<div class="text-center py-8 text-slate-300 text-sm italic">暂无记录</div>`;
            return items.map(i => `
                <div class="group bg-slate-50 p-3 rounded-xl border border-transparent hover:border-indigo-200 transition relative">
                    <div class="flex justify-between items-start mb-1">
                        <div class="font-bold text-sm text-slate-800">${i.title}</div>
                        <div class="text-indigo-600 font-mono text-xs font-bold">+${i.score.toFixed(3)}</div>
                    </div>
                    <div class="flex justify-between items-center mt-2">
                        <span class="text-[11px] text-slate-400 font-medium">${i.record_date || '未记录'}</span>
                        <div class="flex space-x-3 opacity-0 group-hover:opacity-100 transition">
                            ${i.proof_path ? `<button onclick="viewImg('${i.proof_path}')" class="text-indigo-500 hover:text-indigo-700 font-bold text-[11px]">证明</button>` : ''}
                            <button onclick='editEvalRecord(${JSON.stringify(i)})' class="text-slate-500 hover:text-slate-800 font-bold text-[11px]">编辑</button>
                            <button onclick="delEvalRecord(${i.id})" class="text-rose-500 hover:text-rose-700 font-bold text-[11px]">删除</button>
                        </div>
                    </div>
                </div>`).join('');
        }

        function openEvalModal(defaultModule = null) {
            document.getElementById('eval-form').reset(); document.getElementById('f-id').value = '';
            document.getElementById('f-date').value = new Date().toISOString().split('T')[0];
            if(defaultModule) document.getElementById('f-module').value = defaultModule;
            document.getElementById('eval-modal-title').innerText = '新增加分项';
            document.getElementById('eval-modal').classList.remove('hidden');
        }
        function closeEvalModal() { document.getElementById('eval-modal').classList.add('hidden'); }

        function editEvalRecord(item) {
            document.getElementById('f-id').value = item.id; document.getElementById('f-module').value = item.module;
            document.getElementById('f-sub').value = item.sub_module; document.getElementById('f-title').value = item.title;
            document.getElementById('f-score').value = item.score; document.getElementById('f-date').value = item.record_date || '';
            document.getElementById('eval-modal-title').innerText = '编辑加分项'; document.getElementById('eval-modal').classList.remove('hidden');
        }

        async function handleEvalSubmit(e) {
            e.preventDefault(); const id = document.getElementById('f-id').value;
            const formData = new FormData();
            formData.append('module', document.getElementById('f-module').value); formData.append('sub_module', document.getElementById('f-sub').value);
            formData.append('title', document.getElementById('f-title').value); formData.append('score', document.getElementById('f-score').value);
            formData.append('record_date', document.getElementById('f-date').value);
            if(document.getElementById('f-file').files[0]) formData.append('file', document.getElementById('f-file').files[0]);
            await fetch(id ? `/api/eval/${id}` : '/api/eval', { method: id ? 'PUT' : 'POST', body: formData });
            closeEvalModal(); loadEval();
        }

        async function delEvalRecord(id) {
            if(confirm('彻底删除？')) { await fetch(`/api/eval/${id}`, { method: 'DELETE' }); loadEval(); }
        }
        function viewImg(src) { document.getElementById('preview-src').src = src; document.getElementById('img-preview').classList.remove('hidden'); }
    </script>
</body>
</html>
"""


@app.get("/")
def read_root():
    return HTMLResponse(content=HTML_CONTENT)


def start_server():
    # 关闭多余的日志输出，让终端保持干净
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")


if __name__ == "__main__":
    # 移除了所有的 print 语句，防止 Windows GBK 编码和隐藏控制台冲突

    # 1. 在后台线程启动 FastAPI 服务
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 稍微等一秒，确保后端接口已经就绪
    time.sleep(1)

    # 2. 启动原生的窗口壳子加载网页
    webview.create_window(
        title='SDAU 软院效率中枢',
        url='http://127.0.0.1:8000',
        width=1280,
        height=850,
        min_size=(1024, 700)
    )
    # 这行代码会阻塞主线程，直到你关掉软件窗口
    webview.start()