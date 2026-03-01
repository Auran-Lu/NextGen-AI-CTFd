import os
import time
import json
import urllib.request
import ssl
import redis
import traceback
import yaml

def get_config():
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../score_predictor/ai_config.yaml'))
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def generate_report(profile, model_cfg, ctx):
    print(f"[PostMatch Daemon] 正在为队伍 {profile['team_name']} 生成保姆级精细复盘...", flush=True)
    
    # 将字典转为 YAML 传给 AI，结构清晰且省 Token
    profile_yaml = yaml.dump(profile, allow_unicode=True, sort_keys=False)
    
    system_prompt = """你是一位资深、严谨且极具教育责任感的 CTF 战队总教练。比赛已结束，你需要根据队伍在后台的【真实操作日志】给他们出一份极其精细的赛后复盘诊断书。

【你的核心任务与分析逻辑】：
1. 【雷达图评估】：根据他们解题的 Category（方向）生成一个 6 维度的雷达图评分 (0-100分，维度必须固定为：Web, Pwn, Reverse, Crypto, Misc, 实战稳定性)。其中"实战稳定性"由报错次数反向决定，报错越多分数越低。
2. 【战绩总览】：简要总结该队伍的整体表现（偏科还是全能）。
3. 【🏆 高光时刻 (已解出题目分析)】：针对他们成功解出的题目，**必须结合题目的 Tags（标签）**，分析他们掌握了哪些技术栈。
4. 【⚠️ 痛点剖析与补救指南 (核心考点)】：这是最重要的部分！请重点分析他们的 `fail_counts`（错误提交次数高的题目）或未解出的题目。**你必须明确指出这些失误题目的名称，并根据同类题型的常规 Tag 或常识，精准推测该题的考察重点，随后为他们提供“保姆级”的知识点补充建议。**
   - *例如：你在 Web-01 题目上提交了 15 次错误，该题考察重点为 `SQL盲注` 和 `WAF绕过`。说明你们在盲注脚本编写或 tamper 使用上极度欠缺，建议立刻去补充 Python 自动化盲注知识。*
5. 如果他们使用了 `hints_used`（提示），请提醒他们不要过度依赖提示，要注重独立分析能力。

【必须严格按照以下 JSON 格式输出，不得含有 Markdown 代码块包裹符】：
{
  "radar_chart": {
    "Web": 85,
    "Pwn": 10,
    "Reverse": 0,
    "Crypto": 50,
    "Misc": 60,
    "实战稳定性": 30
  },
  "report_markdown": "## 📊 战绩总览\n(整体评价)\n\n## 🏆 高光与技术栈证明\n(结合成功题目的 Tag 分析掌握的知识)\n\n## ⚠️ 痛点剖析与保姆级加练指南\n(必须精细到具体题目名称、推测或直接引用其考察 Tag，给出针对性的技术补充建议)"
}"""

    content_str = f"【队伍 {profile['team_name']} 的比赛后台绝密档案】：\n{profile_yaml}\n\n请严格按格式生成复盘 JSON。"

    payload = {
        "model": model_cfg['model'],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content_str}
        ],
        "temperature": 0.4  # 温度降低一点，保证题号和Tag的精准映射，不胡编乱造
    }
    
    req = urllib.request.Request(
        model_cfg['apiBase'].rstrip('/') + "/chat/completions",
        data=json.dumps(payload).encode('utf-8'),
        headers={"Authorization": f"Bearer {model_cfg['apiKey']}", "Content-Type": "application/json"}
    )
    
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90, context=ctx) as response:
                res = json.loads(response.read().decode('utf-8'))
                result_str = res['choices'][0]['message']['content'].strip()
                
                # 暴力容错清洗
                if result_str.startswith("```json"): result_str = result_str[7:].strip()
                if result_str.startswith("```"): result_str = result_str[3:].strip()
                if result_str.endswith("```"): result_str = result_str[:-3].strip()
                
                if not result_str: raise ValueError("AI 返回内容为空")
                return json.loads(result_str)
                
        except Exception as api_err:
            print(f"[PostMatch Daemon] 请求失败，重试中: {api_err}", flush=True)
            if attempt < 2: time.sleep(3)
            else: raise api_err

def run_worker():
    print("[+] Enhanced Educational AI Coach Daemon Started!", flush=True)
    time.sleep(5)
    
    try:
        ai_cfg = get_config()
        model_cfg = next(m for m in ai_cfg['models'] if m['name'] == ai_cfg['defaultModel'])
    except Exception as e:
        print(f"[-] Config Load Failed: {e}", flush=True)
        return

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    while True:
        try:
            r = redis.Redis(host='cache', port=6379, db=0, decode_responses=True)
            res = r.brpop('postmatch_ai_queue', timeout=0)
            if not res: continue
            
            _, task_data = res
            profile = json.loads(task_data)
            
            try:
                coach_result = generate_report(profile, model_cfg, ctx)
            except Exception as e:
                print(f"[PostMatch Daemon] AI 解析或生成失败: {e}", flush=True)
                coach_result = {
                    "radar_chart": {"Web":0, "Pwn":0, "Reverse":0, "Crypto":0, "Misc":0, "实战稳定性":0},
                    "report_markdown": f"生成诊断报告时发生异常: {str(e)}"
                }
            
            r.set(f"postmatch_result_{profile['team_id']}", json.dumps(coach_result))
            print(f"[PostMatch Daemon] 队伍 {profile['team_name']} 的精细化保姆级报告生成完毕！", flush=True)
            
        except Exception as e:
            traceback.print_exc()
            time.sleep(3)

if __name__ == "__main__":
    run_worker()