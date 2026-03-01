import os
import sys
import json
import subprocess
import redis
from flask import Blueprint, jsonify, render_template_string, request
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.utils.user import get_current_team
from CTFd.models import db, Solves, Submissions, Challenges, Tags, Hints, HintUnlocks, Teams

# ==========================================
# 🎨 页面模板
# ==========================================

ADMIN_HTML = """
{% extends "admin/base.html" %}
{% block content %}
<!-- 强制引入 Bootstrap 5 Bundle (包含 Modal 逻辑)，以防 CTFd 原生未完全暴露 -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h2 class="mb-1">🏆 赛后智能复盘引擎</h2>
            <p class="text-muted mb-0">按需为指定队伍生成 AI 诊断报告与雷达图，精确控制 API 成本。</p>
        </div>
        <button id="genAllBtn" class="btn btn-danger btn-lg shadow-sm" onclick="triggerGeneration('all')">⚡ 一键全员生成</button>
    </div>
    
    <div class="card shadow-sm">
        <table class="table table-striped table-hover mb-0">
            <thead class="table-dark">
                <tr><th>队伍 ID</th><th>队伍名称</th><th>队伍状态</th><th>复盘报告状态</th><th class="text-end" style="width: 280px;">操作控制</th></tr>
            </thead>
            <tbody>
                {% for t in teams %}
                <tr>
                    <td class="align-middle">{{ t.id }}</td>
                    <td class="align-middle fw-bold">{{ t.name }}</td>
                    <td class="align-middle">
                        {% if t.banned %}<span class="badge bg-danger">Banned</span>
                        {% elif t.hidden %}<span class="badge bg-secondary">Hidden</span>
                        {% else %}<span class="badge bg-success">Active</span>{% endif %}
                    </td>
                    <td class="align-middle" id="status-{{ t.id }}">
                        <span class="text-muted"><i class="fas fa-spinner fa-spin"></i> 检查中...</span>
                    </td>
                    <td class="align-middle text-end">
                        <button class="btn btn-sm btn-outline-secondary me-1" onclick="checkStatus({{ t.id }})" title="刷新当前状态">🔄 刷新</button>
                        <button class="btn btn-sm btn-primary me-1" onclick="triggerGeneration({{ t.id }})" id="btn-{{ t.id }}">🤖 生成</button>
                        <button class="btn btn-sm btn-info text-white d-none" onclick="previewReport({{ t.id }}, '{{ t.name }}')" id="preview-{{ t.id }}">👀 预览</button>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<!-- 预览报告的弹窗 Modal -->
<div class="modal fade" id="previewModal" tabindex="-1" aria-labelledby="modalTitle" aria-hidden="true">
  <div class="modal-dialog modal-xl modal-dialog-scrollable">
    <div class="modal-content">
      <div class="modal-header bg-dark text-white">
        <h5 class="modal-title" id="modalTitle">📄 战队复盘报告预览</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body bg-light">
         <div class="row">
            <!-- 左侧雷达图区域 -->
            <div class="col-md-5 d-flex align-items-center justify-content-center bg-white rounded shadow-sm p-3 me-2">
                <div id="radarChart" style="width: 100%; height: 450px;"></div>
            </div>
            <!-- 右侧 Markdown 点评区域 -->
            <div class="col-md-6 flex-grow-1 bg-white rounded shadow-sm p-4">
                <div id="markdownContent" style="white-space: pre-wrap; font-size: 1.05rem; line-height: 1.7; max-height: 500px; overflow-y: auto;"></div>
            </div>
         </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">关闭预览</button>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
{% endblock %}
{% block scripts %}
<script>
const CSRF_TOKEN = window.init ? window.init.csrfNonce : '';
let chartInstance = null;
let previewModalObj = null;

// 页面加载时自动获取所有状态并初始化 Modal 对象
window.onload = () => {
    // 强制初始化 Bootstrap Modal 对象，确保点击时绝对能弹出来
    previewModalObj = new bootstrap.Modal(document.getElementById('previewModal'), {
        keyboard: true
    });

    {% for t in teams %}
    checkStatus({{ t.id }});
    {% endfor %}
}

function checkStatus(team_id) {
    let stCell = document.getElementById(`status-${team_id}`);
    stCell.innerHTML = '<span class="text-muted"><i class="fas fa-sync fa-spin"></i> 获取中...</span>';
    
    fetch(`/api/v1/plugins/postmatch/status?team_id=${team_id}`)
    .then(r=>r.json()).then(d=> {
        let preBtn = document.getElementById(`preview-${team_id}`);
        if(d.has_report) {
            stCell.innerHTML = '<span class="badge bg-success"><i class="fas fa-check"></i> 已生成</span>';
            preBtn.classList.remove('d-none');
            document.getElementById(`btn-${team_id}`).innerText = "🤖 重新生成";
        } else {
            stCell.innerHTML = '<span class="badge bg-secondary">未生成</span>';
            preBtn.classList.add('d-none');
        }
    }).catch(e => {
        stCell.innerHTML = '<span class="badge bg-danger">网络错误</span>';
    });
}

function triggerGeneration(target) {
    let confirmMsg = target === 'all' ? "警告：这将调用 AI 为全服所有队伍重新生成报告，可能消耗大量额度。确定继续？" : "确定为该队伍(重新)生成专属复盘报告吗？";
    if(!confirm(confirmMsg)) return;

    if(target === 'all') document.getElementById('genAllBtn').innerHTML = "<i class='fas fa-spinner fa-spin'></i> 批量投递中...";
    else document.getElementById(`btn-${target}`).innerHTML = "<i class='fas fa-spinner fa-spin'></i> 投递中...";

    fetch('/api/v1/plugins/postmatch/trigger', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'CSRF-Token': CSRF_TOKEN},
        body: JSON.stringify({ target: target })
    }).then(r=>r.json()).then(d=>{
        alert(d.message);
        if(target === 'all') {
            document.getElementById('genAllBtn').innerText = "⚡ 一键全员生成";
            setTimeout(() => location.reload(), 2000);
        } else {
            document.getElementById(`status-${target}`).innerHTML = '<span class="badge bg-warning text-dark"><i class="fas fa-cog fa-spin"></i> AI 撰写中...</span>';
            // 隐藏预览按钮，防止看旧的
            document.getElementById(`preview-${target}`).classList.add('d-none');
            // 自动轮询查询是否完成
            let itv = setInterval(() => {
                fetch(`/api/v1/plugins/postmatch/status?team_id=${target}`).then(r=>r.json()).then(res=>{
                    if(res.has_report) {
                        clearInterval(itv);
                        checkStatus(target);
                    }
                });
            }, 3000);
        }
    });
}

function previewReport(team_id, team_name) {
    document.getElementById('modalTitle').innerText = `📄 队伍 [${team_name}] 的专属赛后诊断书`;
    document.getElementById('markdownContent').innerHTML = "<h4 class='text-center mt-5'><i class='fas fa-spinner fa-spin'></i> 正在读取报告数据...</h4>";
    
    // 先把弹窗弹出来，防止用户觉得卡顿没反应
    previewModalObj.show();

    fetch(`/api/v1/plugins/postmatch/status?team_id=${team_id}&full=true`)
    .then(r=>r.json()).then(d=> {
        if(d.data) {
            let res = d.data;
            document.getElementById('markdownContent').innerText = res.report_markdown;
            
            // 动态挂载与渲染雷达图
            let radarData = [];
            let radarIndicator = [];
            for (let key in res.radar_chart) {
                radarIndicator.push({name: key, max: 100});
                radarData.push(res.radar_chart[key]);
            }
            
            // 必须等弹窗动画完成 (DOM可见) 后再渲染 ECharts，否则图表尺寸会变成 0x0
            setTimeout(() => {
                if(chartInstance) chartInstance.dispose(); // 销毁旧实例防止重影
                chartInstance = echarts.init(document.getElementById('radarChart'));
                chartInstance.setOption({
                    tooltip: { trigger: 'item' },
                    radar: { indicator: radarIndicator, shape: 'polygon' },
                    series: [{ 
                        name: '队伍能力',
                        type: 'radar', 
                        data: [ { value: radarData, name: 'AI 评分', areaStyle: {color: 'rgba(220, 53, 69, 0.4)'} } ] 
                    }]
                });
            }, 200); 
        }
    });
}
</script>
{% endblock %}
"""

USER_HTML = """
{% extends "base.html" %}
{% block content %}
<div class="container mt-5">
    <h2 class="mb-4 text-center">📊 战队专属赛后能力画像</h2>
    <div id="reportContent" class="card p-5 shadow-sm text-center">
        <h4><i class="fas fa-spinner fa-spin"></i> 正在加载您的 AI 诊断报告...</h4>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
{% endblock %}
{% block scripts %}
<script>
fetch('/api/v1/plugins/postmatch/my_report')
.then(r=>r.json())
.then(d=>{
    let box = document.getElementById('reportContent');
    if(!d.success) {
        box.innerHTML = `<div class="alert alert-warning"><h4>🕵️ 未发现报告</h4><p>${d.message}</p></div>`;
        return;
    }
    let res = d.data;
    let radarData = [], radarIndicator = [];
    for (let key in res.radar_chart) {
        radarIndicator.push({name: key, max: 100});
        radarData.push(res.radar_chart[key]);
    }
    
    let html = `<div class="row"><div class="col-md-5"><div id="radarChart" style="width: 100%; height: 450px; margin: 0 auto;"></div></div>`;
    html += `<div class="col-md-7"><div class="text-start p-4 bg-light rounded" style="white-space: pre-wrap; font-size: 1.1rem; line-height: 1.8; color:#333;">${res.report_markdown}</div></div></div>`;
    box.innerHTML = html;
    
    var myChart = echarts.init(document.getElementById('radarChart'));
    myChart.setOption({
        tooltip: {},
        radar: { indicator: radarIndicator, shape: 'polygon', splitArea: {show: false} },
        series: [{ type: 'radar', data: [ { value: radarData, name: '实战能力', areaStyle: {color: 'rgba(54, 162, 235, 0.5)'}, itemStyle:{color: '#36a2eb'} } ] }]
    });
});
</script>
{% endblock %}
"""

def load(app):
    postmatch_bp = Blueprint('postmatch_report', __name__, template_folder='templates')
    
    def get_redis():
        host = os.environ.get('REDIS_HOST', 'cache')
        port = int(os.environ.get('REDIS_PORT', 6379))
        return redis.Redis(host=host, port=port, db=0, decode_responses=True)

    def extract_team_profile(team):
        solves = Solves.query.filter_by(team_id=team.id).all()
        solved_chals = []
        for s in solves:
            chal = Challenges.query.filter_by(id=s.challenge_id).first()
            if chal:
                tags = [t.value for t in Tags.query.filter_by(challenge_id=chal.id).all()]
                solved_chals.append({'name': chal.name, 'category': chal.category, 'value': chal.value, 'tags': tags})
                
        fails = Submissions.query.filter_by(team_id=team.id, type='incorrect').all()
        fail_stats = {}
        for f in fails:
            chal = Challenges.query.filter_by(id=f.challenge_id).first()
            if chal: fail_stats[chal.name] = fail_stats.get(chal.name, 0) + 1
                
        hints = HintUnlocks.query.filter_by(account_id=team.id).all()
        return {
            'team_id': team.id, 'team_name': team.name,
            'solved_challenges': solved_chals, 'fail_counts': fail_stats, 'hints_used': len(hints)
        }

    @postmatch_bp.route('/admin/postmatch', methods=['GET'])
    @admins_only
    def admin_page():
        teams = Teams.query.all()
        return render_template_string(ADMIN_HTML, teams=teams)
        
    @postmatch_bp.route('/postmatch/report', methods=['GET'])
    @authed_only
    def user_page():
        return render_template_string(USER_HTML)

    @postmatch_bp.route('/api/v1/plugins/postmatch/trigger', methods=['POST'])
    @admins_only
    def trigger_generation():
        target = request.json.get('target', 'all')
        r = get_redis()
        
        if target == 'all':
            teams = Teams.query.filter_by(banned=False, hidden=False).all()
        else:
            teams = Teams.query.filter_by(id=int(target)).all()
            if not teams: return jsonify({'success': False, 'message': '找不到该队伍'})
        
        task_count = 0
        for team in teams:
            profile = extract_team_profile(team)
            r.lpush('postmatch_ai_queue', json.dumps(profile))
            task_count += 1
            
        return jsonify({'success': True, 'message': f'✅ 成功将 {task_count} 支队伍的历史数据发送给 AI 教练！'})

    @postmatch_bp.route('/api/v1/plugins/postmatch/status', methods=['GET'])
    @admins_only
    def get_status():
        team_id = request.args.get('team_id')
        r = get_redis()
        res = r.get(f"postmatch_result_{team_id}")
        if request.args.get('full') == 'true' and res:
            return jsonify({'has_report': True, 'data': json.loads(res)})
        return jsonify({'has_report': res is not None})

    @postmatch_bp.route('/api/v1/plugins/postmatch/my_report', methods=['GET'])
    @authed_only
    def get_my_report():
        team = get_current_team()
        if not team: return jsonify({'success': False, 'message': '您未加入任何战队，无法生成战队画像。'}), 403
        
        r = get_redis()
        res = r.get(f"postmatch_result_{team.id}")
        if res: return jsonify({'success': True, 'data': json.loads(res)})
        return jsonify({'success': False, 'message': '当前战队暂无赛后复盘报告。请联系管理员为您生成。'}) 

    app.register_blueprint(postmatch_bp)

    script_path = os.path.join(os.path.dirname(__file__), 'report_daemon.py')
    print(f"[PostMatch] 启动赛后复盘 AI 守护进程: {script_path}")
    subprocess.Popen([sys.executable, script_path], preexec_fn=os.setpgrp)
