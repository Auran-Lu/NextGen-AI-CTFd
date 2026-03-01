from flask import Blueprint, jsonify
from flask_cors import CORS
from CTFd.models import db, Solves, Challenges, Teams
from CTFd.cache import cache
import time
import redis
import sys
import subprocess
import os


predict_bp = Blueprint('score_predictor', __name__)
CORS(predict_bp)

r_client = redis.Redis(host='cache', port=6379, db=0, decode_responses=True)

def get_decoupled_ai_commentary():
    try:
        commentary = r_client.get('ai_predictor_commentary')
        if commentary:
            return commentary
    except Exception as e:
        print(f"[Redis] AI Cache Read Error: {e}", file=sys.stderr)
    return "AI 正在后台进行深度演算，请稍后刷新大屏..."

def math_prediction_fallback(history_data, future_hours=2):
    if len(history_data) < 2: return []
    first_point = history_data[0]
    last_point = history_data[-1]
    time_diff = last_point["time"] - first_point["time"]
    if time_diff <= 0: return []
    future_time = last_point["time"] + (future_hours * 3600)
    prediction = {"time": future_time}
    for key in last_point.keys():
        if key == "time": continue
        score_diff = last_point[key] - first_point.get(key, 0)
        rate = score_diff / time_diff 
        predicted_score = last_point[key] + (rate * (future_hours * 3600))
        prediction[key] = max(last_point[key], int(predicted_score))
    return [prediction]

@predict_bp.route('/api/v1/plugins/predictor/trends', methods=['GET', 'OPTIONS'])

def get_prediction_trends():
    try:
        solves = db.session.query(
            Solves.challenge_id,
            Teams.name.label('team_name'),
            Challenges.value,
            Challenges.category,  
            Solves.date
        ).join(Teams, Solves.account_id == Teams.id)\
         .join(Challenges, Solves.challenge_id == Challenges.id)\
         .order_by(Solves.date.asc()).all()

        category_stats = {}
        team_scores = {}
        history_timeline = []
        
        for solve in solves:
            team_name = solve.team_name
            score = solve.value
            category = solve.category or 'Misc'
            timestamp = int(solve.date.timestamp())

            if category not in category_stats:
                category_stats[category] = {'total': 0, 'teams': {}}
            category_stats[category]['total'] += score
            if team_name not in category_stats[category]['teams']:
                category_stats[category]['teams'][team_name] = 0
            category_stats[category]['teams'][team_name] += score
            
            if team_name not in team_scores:
                team_scores[team_name] = 0
            team_scores[team_name] += score
            
            snapshot = {"time": timestamp}
            for t_name, t_score in team_scores.items():
                snapshot[t_name] = t_score
            history_timeline.append(snapshot)
            
        team_list = list(team_scores.keys())
        predictions = math_prediction_fallback(history_timeline, future_hours=2)
        commentary = get_decoupled_ai_commentary()

        target_list = []
        for cat_name, stats in category_stats.items():
            sorted_teams = sorted(stats['teams'].items(), key=lambda x: x[1], reverse=True)
            top_text = f"{sorted_teams[0][0]}({sorted_teams[0][1]}pts)" if sorted_teams else "无人攻破"
            target_list.append({"name": f"[{cat_name}]", "score": stats['total'], "top_team": top_text})

        if not target_list:
            target_list = [{"name": "[等待攻破]", "score": 100, "top_team": "-"}]

        return jsonify({
            "success": True,
            "data": {
                "teams": team_list,
                "history": history_timeline,
                "predictions": predictions,
                "targets": target_list,
                "commentary": commentary
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

def load(app):
    app.register_blueprint(predict_bp)
    
    # 【终极开机自启魔法】：在 Flask 加载插件时，异步拉起独立的影子预测进程
    script_path = os.path.join(os.path.dirname(__file__), 'predictor_service.py')
    
    try:
        # 使用 subprocess 在完全独立的会话中启动它，避免被 gunicorn worker 杀死
        # 加上 preexec_fn=os.setpgrp 让它成为进程组长，脱离当前终端/父进程
        subprocess.Popen(
            [sys.executable, script_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setpgrp
        )
        print("[+] Decoupled AI Predictor Daemon started seamlessly!", file=sys.stderr)
    except Exception as e:
        print(f"[-] Failed to start AI Predictor Daemon: {e}", file=sys.stderr)
        
    print("[+] Decoupled Score Predictor Loaded with CORS Support!")
