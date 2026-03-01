import time
import os
import sys
import yaml
import json
import urllib.request
import ssl
import pymysql
import redis
import traceback

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

def get_config():
    config_path = os.path.join(os.path.dirname(__file__), 'ai_config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def run_service():
    print("[+] AI Predictor Service Started - Decoupled Mode (Daemon)", flush=True)
    
    # 延迟 10 秒启动，给 MySQL 和 Redis 容器充足的初始化时间
    time.sleep(10)
    
    try:
        ai_cfg = get_config()
        model_cfg = next(m for m in ai_cfg['models'] if m['name'] == ai_cfg['defaultModel'])
    except Exception as e:
        print(f"[-] AI Config Load Failed: {e}", flush=True)
        return

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # 只要不死，就一直跑
    while True:
        try:
            # 将 Redis 初始化放在循环内，如果 Redis 挂了重启，脚本也能重新连上
            r = redis.Redis(host='cache', port=6379, db=0, decode_responses=True)
            
            # 将 MySQL 连接放在循环内，每次预测完就关掉，防止长时间连接断开 (MySQL Server has gone away)
            db = pymysql.connect(
                host="db", user="ctfd", password="ctfd", database="ctfd", 
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5
            )
            cursor = db.cursor()
            
            cursor.execute("""
                SELECT 
                    s.challenge_id, 
                    t.name as team_name, 
                    c.value, 
                    c.category, 
                    sub.date
                FROM solves s
                JOIN teams t ON s.team_id = t.id
                JOIN challenges c ON s.challenge_id = c.id
                JOIN submissions sub ON s.challenge_id = sub.challenge_id AND s.team_id = sub.team_id
                WHERE sub.type = 'correct'
                ORDER BY sub.date ASC
            """)
            solves = cursor.fetchall()
            
            cursor.execute("SELECT id, name, category, value FROM challenges WHERE state='visible'")
            all_chals = cursor.fetchall()
            db.close()

            solved_ids = {s['challenge_id'] for s in solves}
            unsolved = [f"[{c['category'] or 'Misc'}] {c['name']} ({c['value']}分)" for c in all_chals if c['id'] not in solved_ids]
            
            cat_stats = {}
            for s in solves:
                cat = s['category'] or 'Misc'
                if cat not in cat_stats: cat_stats[cat] = {'total': 0, 'teams': {}}
                cat_stats[cat]['total'] += s['value']
                cat_stats[cat]['teams'][s['team_name']] = cat_stats[cat]['teams'].get(s['team_name'], 0) + s['value']

            print(f"[AI] Fetching prediction from {model_cfg['name']}...", flush=True)
            
            prompt = f"""你是一位顶级的 CTF 赛事解说员。请根据实战数据写一段100字内的幽默解说词。
【各题型得分分布(用于分析偏科)】: {json.dumps(cat_stats, ensure_ascii=False)}
【至今未被攻破的悬念题】: {unsolved[:3]}"""

            payload = {
                "model": model_cfg['model'],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            }
            req = urllib.request.Request(
                model_cfg['apiBase'].rstrip('/') + "/chat/completions",
                data=json.dumps(payload).encode('utf-8'),
                headers={"Authorization": f"Bearer {model_cfg['apiKey']}", "Content-Type": "application/json"}
            )
            
            with urllib.request.urlopen(req, timeout=60, context=ctx) as response:
                res = json.loads(response.read().decode('utf-8'))
                commentary = res['choices'][0]['message']['content'].strip()
                
                r.set('ai_predictor_commentary', commentary)
                print(f"[AI] Update Success: {commentary[:40]}...", flush=True)

        except Exception as e:
            # 无论发生什么错误（断网、数据库连不上、API超时），记录错误
            print(f"[-] Service Error: {e}", flush=True)
            traceback.print_exc()
        
        # 无论返回， 30 s后重发
        print("Waiting 30 seconds for next AI prediction...", flush=True)
        time.sleep(30)

if __name__ == "__main__":
    run_service()