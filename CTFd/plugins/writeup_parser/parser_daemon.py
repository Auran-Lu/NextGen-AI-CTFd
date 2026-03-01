import os
import time
import json
import urllib.request
import ssl
import redis
import traceback
import yaml
from pypdf import PdfReader
import docx

def get_config():
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../score_predictor/ai_config.yaml'))
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def extract_text_from_file(filepath):
    """
    极强容错的实体文档解析引擎
    """
    ext = filepath.split('.')[-1].lower()
    text = ""
    try:
        if ext == 'pdf':
            reader = PdfReader(filepath)
            for page in reader.pages: 
                page_text = page.extract_text()
                if page_text: text += page_text + "\n"
        elif ext in ['docx', 'doc']:
            doc = docx.Document(filepath)
            text = "\n".join([p.text for p in doc.paragraphs])
        else:
            # 针对 md, txt 或无后缀文件，加入智能编码重试机制
            try:
                with open(filepath, 'r', encoding='utf-8') as f: 
                    text = f.read()
            except UnicodeDecodeError:
                try:
                    with open(filepath, 'r', encoding='gbk') as f: 
                        text = f.read()
                except UnicodeDecodeError:
                    with open(filepath, 'r', encoding='iso-8859-1', errors='ignore') as f: 
                        text = f.read()
                        
    except Exception as e:
        print(f"[Writeup Daemon] 文件解析严重警告: {e}", flush=True)
        text = f"【系统提示：服务器在解剖选手的 {ext} 格式实体文件时发生内部异常 ({str(e)})。这可能是因为文件已损坏或非标准格式。请作为裁判酌情给出嫌疑分】"
        
    return text.strip()

def analyze_report(task, model_cfg, ctx):
    filepath = task.get('file_path')
    original_filename = task.get('original_filename')
    print(f"[Writeup Daemon] 正在解剖队伍 {task['team_name']} 的实体文件: {original_filename}...", flush=True)
    
    report_text = extract_text_from_file(filepath)
    if len(report_text) > 8000:
        report_text = report_text[:8000] + "\n...[超长内容已截断]..."

    system_prompt = """你是一个顶级威胁情报分析师和网络安全裁判。你需要阅读选手提交的渗透测试报告。

【任务1】：评估报告质量。给出 0 到 100 的违规嫌疑指数（纯粹靠自动化扫描、无逻辑、敷衍了事的分数高；有清晰分析过程的分数低）。
【任务2】：提取高精度战术指纹。针对报告中提到的每个解题过程，提取一个由多元素组成的复合指纹（格式：工具名称/手段_关键切入点_特定参数或Payload片段）。
例如：
- 错误指纹：SQLMAP （太笼统）
- 优质指纹：SQLMAP_ID_PARAM_TIME_BLIND_SLEEP_5 （精确到参数和注入类型）
- 优质指纹：MSF_MS17_010_REVERSE_TCP_PORT_4444

【必须严格按以下JSON格式输出，不带任何Markdown代码块标记】：
{
  "is_violation": false,
  "confidence": 30,
  "summary": "报告详细记录了手工探测到SQL注入并编写脚本的完整过程，无明显违规。",
  "challenges": [
    {
      "chal_name": "Web-01(若未提题号请根据内容猜一个简短代号)",
      "suspicion_reason": "使用了非预期的服务器后门",
      "fingerprint": "DIRB_ADMIN_BAK_ZIP_LEAK"
    }
  ]
}
如果报告极度简略，无法提取具体题目，也必须保证 JSON 结构完整，challenges 可为空数组 []。"""

    content_str = f"队伍名称：{task['team_name']}\n文档名：{original_filename}\n报告内容：\n{report_text}\n\n请给出严格规范的 JSON 裁决。"

    payload = {
        "model": model_cfg['model'],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content_str}
        ],
        "temperature": 0.1
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
                
                if result_str.startswith("```json"): result_str = result_str[7:].strip()
                if result_str.startswith("```"): result_str = result_str[3:].strip()
                if result_str.endswith("```"): result_str = result_str[:-3].strip()
                
                if not result_str: raise ValueError("AI 返回了空字符串")
                return json.loads(result_str)
        except Exception as api_err:
            print(f"[Writeup Daemon] 第 {attempt+1} 次请求失败: {api_err}", flush=True)
            if attempt < 2: time.sleep(3)
            else: raise api_err

def run_worker():
    print("[+] Enhanced Robust AI Daemon Started!", flush=True)
    time.sleep(5)
    
    try:
        ai_cfg = get_config()
        model_cfg = next(m for m in ai_cfg['models'] if m['name'] == ai_cfg['defaultModel'])
    except Exception as e:
        return

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    while True:
        try:
            r = redis.Redis(host='cache', port=6379, db=0, decode_responses=True)
            res = r.brpop('writeup_parse_queue', timeout=0)
            if not res: continue
            
            _, task_data = res
            task = json.loads(task_data)
            
            try:
                judge_result = analyze_report(task, model_cfg, ctx)
                # 保留文件在 /tmp/writeups 中
            except Exception as e:
                judge_result = {
                    "is_violation": False, 
                    "confidence": 0, 
                    "summary": f"系统解析或AI调用失败: {str(e)}", 
                    "challenges": []
                }
            
            status_key = f"global_writeup_status_{task['team_id']}"
            r.set(status_key, json.dumps({'status': 'completed', 'result': judge_result}), ex=86400)
            
        except Exception as e:
            time.sleep(3)

if __name__ == "__main__":
    run_worker()