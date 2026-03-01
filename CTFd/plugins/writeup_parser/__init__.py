import os
import sys
import json
import uuid
import subprocess
import redis
from flask import request, jsonify, Blueprint, render_template_string
from werkzeug.utils import secure_filename
from CTFd.utils.user import get_current_team
from CTFd.utils.decorators import authed_only, admins_only

# 【安全配置】：允许的文件后缀与最大文件大小 (5MB)
ALLOWED_EXTENSIONS = {'md', 'txt'}
MAX_FILE_SIZE = 20 * 1024 * 1024 

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

USER_HTML = """
{% extends "base.html" %}
{% block content %}
<div class="container mt-5 text-center">
   <h2 class="mb-4">📥 队伍参赛总结与渗透报告提交</h2>
   <div class="alert alert-info mb-4 text-start shadow-sm" style="max-width: 600px; margin: 0 auto;">
     <strong>💡 报告格式要求：</strong><br>
     为保障系统安全与 AI 解析精度，本平台仅接收 <b>Markdown (.md)</b> 或纯文本 <b>(.txt)</b> 格式的报告文档。最大体积限制为 5MB。<br>
     多次提交将自动覆盖旧版报告。
   </div>
   <div class="row justify-content-center">
      <div class="col-md-6 card p-5 shadow-sm">
         <div class="mb-4 text-start">
             <label class="form-label fw-bold">请选择报告文档 (.md / .txt)</label>
             <!-- 【前端安全防御】：限制选择框只显示 md 和 txt -->
             <input type="file" id="reportFile" class="form-control" accept=".md,.txt">
         </div>
         <button onclick="submitReport()" class="btn btn-success w-100 btn-lg">🚀 提交队伍报告</button>
         <div id="uploadMsg" class="mt-4 fw-bold fs-5"></div>
      </div>
   </div>
</div>
{% endblock %}
{% block scripts %}
<script>
function submitReport() {
    let fileInput = document.getElementById('reportFile').files[0];
    if(!fileInput) { alert("请先选择文件！"); return; }
    
    // 【前端大小拦截】
    if(fileInput.size > 5 * 1024 * 1024) {
        alert("文件大小不能超过 5MB！");
        return;
    }
    
    let fd = new FormData();
    fd.append('file', fileInput);
    fd.append('nonce', window.init ? window.init.csrfNonce : '');
    
    document.getElementById('uploadMsg').innerText = "⏳ 正在上传进行安全扫描，请稍候...";
    document.getElementById('uploadMsg').style.color = 'black';

    fetch('/api/v1/plugins/writeup/upload_only', {
        method: 'POST',
        headers: {
            'Accept': 'application/json',
            'CSRF-Token': window.init ? window.init.csrfNonce : ''
        },
        body: fd
    }).then(r=>{
        if(r.status === 403) throw new Error("权限不足或会话已过期(403)");
        return r.json();
    }).then(d=>{
        document.getElementById('uploadMsg').innerText = d.message;
        document.getElementById('uploadMsg').style.color = d.success ? 'green' : 'red';
    }).catch(e => {
        document.getElementById('uploadMsg').innerText = "❌ " + e.message;
        document.getElementById('uploadMsg').style.color = 'red';
    });
}
</script>
{% endblock %}
"""

ADMIN_HTML = """
{% extends "admin/base.html" %}
{% block content %}
<div class="container mt-4">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h2>🤖 AI 判卷与赛后查重中心</h2>
    <button class="btn btn-danger btn-lg shadow-sm" onclick="runPlagiarismCheck()">🕵️ 赛后指纹查重引擎</button>
  </div>
  <p class="text-muted">此处展示各队伍提交的最终版 Markdown 总结报告。查重引擎将在所有已完成AI研判的报告中寻找“战术指纹”碰撞。</p>
  
  <div id="plagiarismResult" class="alert alert-warning d-none shadow-sm mb-4"></div>

  <table class="table table-striped table-hover mt-4 bg-white shadow-sm">
    <thead class="table-dark">
      <tr><th>队伍名</th><th>实体文件</th><th>AI 研判状态与结构化指纹</th><th style="width: 200px;">手动控制</th></tr>
    </thead>
    <tbody>
      {% for sub in submissions %}
      <tr>
        <td class="align-middle fw-bold">{{ sub.team_name }}</td>
        <td class="align-middle text-primary">{{ sub.original_filename }}</td>
        <td>
          <span class="badge bg-secondary mb-2" id="status-{{ sub.team_id }}">待判定</span>
          <div id="reason-{{ sub.team_id }}"></div>
        </td>
        <td class="align-middle">
          <button class="btn btn-sm btn-primary me-2 mb-1" onclick="analyze('{{ sub.team_id }}')">🧠 分析</button>
          <button class="btn btn-sm btn-outline-secondary mb-1" onclick="check('{{ sub.team_id }}')">🔄 刷新</button>
        </td>
      </tr>
      {% endfor %}
      {% if not submissions %}
      <tr><td colspan="4" class="text-center py-4">暂无队伍提交报告</td></tr>
      {% endif %}
    </tbody>
  </table>
</div>
{% endblock %}
{% block scripts %}
<script>
function analyze(team) {
    document.getElementById(`status-${team}`).className = 'badge bg-warning text-dark';
    document.getElementById(`status-${team}`).innerText = 'AI 深度解剖中...';
    fetch(`/api/v1/plugins/writeup/admin_trigger`, {
        method:'POST', 
        headers:{'Content-Type': 'application/json', 'CSRF-Token': window.init ? window.init.csrfNonce : ''},
        body: JSON.stringify({team_id: team})
    }).then(r=>r.json()).then(d=> {
        if(!d.success) alert(d.message);
    });
}

function check(team) {
    fetch(`/api/v1/plugins/writeup/result?team_id=${team}`)
    .then(r=>r.json()).then(d=>{
        if(d.data && d.data.status === 'completed') {
           let badge = document.getElementById(`status-${team}`);
           badge.innerText = '已完成';
           badge.className = 'badge bg-success';
           
           let res = d.data.result;
           let html = `<div><span class="${res.confidence >= 50 ? 'text-danger' : 'text-success'} fw-bold">嫌疑指数: ${res.confidence}% - ${res.summary}</span></div>`;
           
           if(res.challenges && res.challenges.length > 0) {
               html += `<div class="mt-2 text-muted small"><strong>🧬 战术指纹记录:</strong><ul>`;
               res.challenges.forEach(c => {
                   let chalName = c.chal_name || '未知题目';
                   let fp = c.fingerprint || '无';
                   let reason = c.suspicion_reason ? ` (<span class="text-danger">${c.suspicion_reason}</span>)` : '';
                   html += `<li>[${chalName}] <code>${fp}</code>${reason}</li>`;
               });
               html += `</ul></div>`;
           }
           document.getElementById(`reason-${team}`).innerHTML = html;
        }
    });
}

function runPlagiarismCheck() {
    let resBox = document.getElementById('plagiarismResult');
    resBox.className = 'alert alert-info shadow-sm';
    resBox.innerText = '🕵️ 正在进行指纹拓扑碰撞计算，请稍候...';
    
    fetch('/api/v1/plugins/writeup/plagiarism_check')
    .then(r=>r.json()).then(d=>{
        resBox.className = 'alert alert-warning shadow-sm';
        if(d.collisions && d.collisions.length > 0) {
            let html = `<h5 class="alert-heading">⚠️ 发现潜在抄袭嫌疑 (指纹碰撞)</h5><hr><ul>`;
            d.collisions.forEach(c => {
                html += `<li><strong>题目 ${c.challenge}</strong> 的战术指纹 <code>${c.fingerprint}</code> 存在高度雷同！涉及队伍：<strong class="text-danger">${c.teams.join(', ')}</strong></li>`;
            });
            html += `</ul><p class="mb-0 small">注：同源指纹可能源自相同的公开网文或私下作弊，请人工复核报告。</p>`;
            resBox.innerHTML = html;
        } else {
            resBox.className = 'alert alert-success shadow-sm';
            resBox.innerHTML = '✅ <strong>查重完成！</strong> 各队伍战术指纹均有差异，未发现明显抄袭行为。';
        }
    });
}

window.onload = () => {
    {% for sub in submissions %}
    check('{{ sub.team_id }}');
    {% endfor %}
}
</script>
{% endblock %}
"""

def load(app):
    writeup_bp = Blueprint('writeup_parser', __name__, template_folder='templates')
    UPLOAD_FOLDER = '/tmp/writeups'
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    def get_redis():
        host = os.environ.get('REDIS_HOST', 'cache')
        port = int(os.environ.get('REDIS_PORT', 6379))
        return redis.Redis(host=host, port=port, db=0, decode_responses=True)

    @writeup_bp.route('/writeup/submit', methods=['GET'])
    @authed_only
    def upload_page(): return render_template_string(USER_HTML)

    @writeup_bp.route('/api/v1/plugins/writeup/upload_only', methods=['POST'])
    @authed_only
    def upload_only():
        team = get_current_team()
        if not team: return jsonify({'success': False, 'message': '未加入队伍'}), 403
        if 'file' not in request.files: return jsonify({'success': False, 'message': '未找到文件实体'}), 400
        
        file = request.files['file']
        if file.filename == '': return jsonify({'success': False, 'message': '文件名不能为空'}), 400
        
        # 【后端安全防御】：大小限制防御 (Content-Length)
        if request.content_length and request.content_length > MAX_FILE_SIZE:
            return jsonify({'success': False, 'message': '⚠️ 拦截：文件体积超出 5MB 限制'}), 413

        # 【后端安全防御】：白名单后缀防御
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'message': '⚠️ 拦截：出于安全考虑，仅支持 .md 或 .txt 后缀的文件'}), 403

        # 防路径穿越重命名机制
        filename = secure_filename(file.filename)
        unique_filename = f"team_{team.id}_{uuid.uuid4().hex[:8]}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(filepath)

        r = get_redis()
        sub_id = f"team_{team.id}"
        sub_data = {'team_id': team.id, 'team_name': team.name, 'file_path': filepath, 'original_filename': filename}
        r.hset('global_writeup_files', sub_id, json.dumps(sub_data))
        return jsonify({'success': True, 'message': '✅ 全局报告已通过安全校验并提交成功！'}), 200

    @writeup_bp.route('/admin/writeups', methods=['GET'])
    @admins_only
    def admin_page():
        r = get_redis()
        subs_raw = r.hgetall('global_writeup_files')
        submissions = [json.loads(v) for v in subs_raw.values()]
        return render_template_string(ADMIN_HTML, submissions=submissions)

    @writeup_bp.route('/api/v1/plugins/writeup/admin_trigger', methods=['POST'])
    @admins_only
    def admin_trigger():
        team_id = request.json.get('team_id')
        r = get_redis()
        sub_data_str = r.hget('global_writeup_files', f"team_{team_id}")
        if not sub_data_str: return jsonify({'success': False, 'message': '找不到该队伍的报告'}), 404
        r.lpush('writeup_parse_queue', sub_data_str)
        r.set(f"global_writeup_status_{team_id}", json.dumps({'status': 'processing', 'result': None}), ex=86400)
        return jsonify({'success': True, 'message': '已触发 AI 分析'})

    @writeup_bp.route('/api/v1/plugins/writeup/result', methods=['GET'])
    def get_result():
        team_id = request.args.get('team_id')
        res = get_redis().get(f"global_writeup_status_{team_id}")
        if res: return jsonify({'success': True, 'data': json.loads(res)}), 200
        return jsonify({'success': False, 'message': '无记录'}), 404

    @writeup_bp.route('/api/v1/plugins/writeup/plagiarism_check', methods=['GET'])
    @admins_only
    def plagiarism_check():
        r = get_redis()
        keys = r.keys('global_writeup_status_*')
        from collections import defaultdict
        fingerprint_db = defaultdict(lambda: defaultdict(list))
        
        for k in keys:
            team_id = k.split('_')[-1]
            team_info_str = r.hget('global_writeup_files', f"team_{team_id}")
            if not team_info_str: continue
            team_name = json.loads(team_info_str).get('team_name', f"Team {team_id}")
            
            res_str = r.get(k)
            if not res_str: continue
            res_json = json.loads(res_str)
            
            if res_json.get('status') == 'completed' and 'result' in res_json:
                chals = res_json['result'].get('challenges', [])
                for chal in chals:
                    c_name = chal.get('chal_name', '未知题目').upper()
                    fp = chal.get('fingerprint', '').upper()
                    # 过滤掉过于简单、无意义或误判的指纹
                    invalid_fps = ['无', 'NONE', 'UNKNOWN', 'N/A', 'NULL', 'NA']
                    if len(fp) > 4 and fp not in invalid_fps:
                        fingerprint_db[c_name][fp].append(team_name)
                        
        collisions = []
        for chal, fp_dict in fingerprint_db.items():
            for fp, teams in fp_dict.items():
                if len(teams) >= 2:
                    collisions.append({"challenge": chal, "fingerprint": fp, "teams": list(set(teams))})
                    
        return jsonify({'success': True, 'collisions': collisions})

    app.register_blueprint(writeup_bp)

    script_path = os.path.join(os.path.dirname(__file__), 'parser_daemon.py')
    print(f"[Writeup Parser] 启动全局 AI 裁判守护进程: {script_path}")
    subprocess.Popen([sys.executable, script_path], preexec_fn=os.setpgrp)