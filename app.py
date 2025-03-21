import os
import requests
import json
import logging
from flask import Flask, render_template, request, jsonify, session, g
from werkzeug.utils import secure_filename
from time import sleep
import psycopg2
from psycopg2.extras import DictCursor
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = os.urandom(24)

# 获取环境变量中的端口，如果没有则使用5001
port = int(os.environ.get("PORT", 5001))
host = os.environ.get("HOST", "0.0.0.0")  # Railway需要监听所有地址

# 设置日志配置
logging.basicConfig(level=logging.DEBUG)  # 设置日志级别为 DEBUG，这样所有日志信息都会被打印
logger = logging.getLogger(__name__)

# Imgur API 客户端信息
CLIENT_ID = os.environ.get('IMGUR_CLIENT_ID', 'fc527b50366e97e')
CLIENT_SECRET = os.environ.get('IMGUR_CLIENT_SECRET', '24f0caceef6bac73c1bf2143847bc73eb99735ec')

# 在 app 初始化后，init_db 函数之前添加数据库连接
def get_db():
    if not hasattr(g, 'db'):
        # 从环境变量获取数据库URL
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise RuntimeError('DATABASE_URL not set')
            
        # 解析数据库URL
        url = urlparse(database_url)
        
        # 建立连接
        g.db = psycopg2.connect(
            dbname=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port
        )
    return g.db

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()

# 上传图片并获取 URL
def upload_image_to_imgur(image_path):
    logger.debug(f"开始上传图片: {image_path}")
    url = 'https://api.imgur.com/3/upload'
    headers = {'Authorization': f'Client-ID {CLIENT_ID}'}
    
    with open(image_path, 'rb') as image_file:
        files = {'image': image_file}
        response = requests.post(url, headers=headers, files=files)
        
    if response.status_code == 200:
        logger.debug(f"图片上传成功，返回 URL: {response.json()['data']['link']}")
        return response.json()['data']['link']
    else:
        logger.error(f"上传失败: {response.status_code} - {response.text}")
        raise Exception(f"Failed to upload image: {response.json()}")

# 调用 Coze API 并获取结果
def process_with_coze(image_url=None, content=None):
    logger.debug(f"开始调用 Coze API，图片 URL: {image_url}, content: {content}")
    coze_url = 'https://api.coze.com/v1/workflow/run'
    headers = {
        'Authorization': f"Bearer {os.environ.get('COZE_API_TOKEN', 'pat_lmm0o38mIw0OWee8wNOBjBSCWLDRviltMJOFishIqIuRkV5hB8xuzkxSLwrl65wb')}",
        'Content-Type': 'application/json'
    }
    
    # 根据实际传入的内容构建 parameters
    parameters = {}
    if image_url:
        parameters["input"] = image_url
    if content:
        parameters["content"] = content
        
    data = {
        "parameters": parameters,
        "workflow_id": os.environ.get('COZE_WORKFLOW_ID', '7473817378133999623')
    }
    
    logger.debug(f"发送给 Coze 的数据: {data}")  # 添加日志
    
    try:
        response = requests.post(coze_url, json=data, headers=headers)
        response.raise_for_status()

        if response.status_code == 200:
            response_data = response.json()
            logger.debug(f"1. Coze API 原始返回: {response_data}")
            
            if 'data' in response_data:
                try:
                    # 解析第一层JSON
                    result_data = json.loads(response_data['data'])
                    logger.debug(f"2. 第一层解析结果: {result_data}")
                    
                    if 'data' in result_data:
                        # 找到JSON部分
                        json_text = result_data['data']
                        logger.debug(f"3. 提取的文本: {json_text}")
                        
                        start = json_text.find('```json\n') + 8
                        end = json_text.find('\n```', start)
                        
                        if start > 7 and end != -1:
                            json_str = json_text[start:end].strip()
                            logger.debug(f"4. 提取的JSON字符串: {json_str}")
                            
                            parsed_data = json.loads(json_str)
                            logger.debug(f"5. 解析后的数据: {parsed_data}")
                            logger.debug(f"5.1 解析后的数据类型: {type(parsed_data)}")
                            
                            # 返回统一格式的数据
                            final_result = {
                                'token': response_data.get('token', 'N/A'),
                                'output': parsed_data
                            }
                            logger.debug(f"6. 最终返回结果: {final_result}")
                            logger.debug(f"6.1 output字段类型: {type(final_result['output'])}")
                            return final_result
                    
                    raise Exception("未找到有效的JSON数据")
                        
                except json.JSONDecodeError as e:
                    logger.error(f"JSON解析错误: {str(e)}")
                    raise Exception(f"JSON解析错误: {str(e)}")
            else:
                raise Exception("响应中没有data字段")
    except Exception as e:
        logger.error(f"处理请求时出错: {str(e)}")
        raise

@app.route('/')
def index():
    logger.debug("加载主页")
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    logger.debug("接收到上传请求")
    file = request.files.get('image')
    content = request.form.get('content', '').strip()
    
    if not file and not content:
        logger.error("未收到图片或文字内容")
        return jsonify({'error': '请上传图片或输入文字信息'})
    
    try:
        # 情况1: 只有文字
        if content and not file:
            logger.debug("只接收到文字内容")
            result = process_with_coze(content=content)
            
        # 情况2: 只有图片
        elif file and not content:
            logger.debug("只接收到图片")
            image_filename = secure_filename(file.filename)
            image_path = os.path.join('uploads', image_filename)
            os.makedirs('uploads', exist_ok=True)
            file.save(image_path)
            image_url = upload_image_to_imgur(image_path)
            result = process_with_coze(image_url=image_url)
            
        # 情况3: 都有
        else:
            logger.debug("同时接收到图片和文字")
            image_filename = secure_filename(file.filename)
            image_path = os.path.join('uploads', image_filename)
            os.makedirs('uploads', exist_ok=True)
            file.save(image_path)
            image_url = upload_image_to_imgur(image_path)
            result = process_with_coze(image_url=image_url, content=content)
        
        logger.debug(f"准备返回给前端的完整结果: {result}")
        logger.debug(f"result类型: {type(result)}")
        logger.debug(f"result['output']类型: {type(result['output'])}")
        logger.debug(f"result['output']内容: {result['output']}")

        # 构造返回数据
        response_data = {
            'token': result.get('token', 'N/A'),
            'output': result.get('output', 'No result available')
        }
        logger.debug(f"最终构造的response_data: {response_data}")

        return jsonify(response_data)
    except Exception as e:
        logger.error(f"上传和处理过程中出错: {e}")
        logger.exception("详细错误信息:")  # 这会打印完整的错误堆栈
        return jsonify({'error': str(e)})

# 新增API接口路由
@app.route('/api/upload', methods=['POST'])
def api_upload():
    logger.debug("接收到API上传请求")
    logger.debug(f"请求方法: {request.method}")
    logger.debug(f"请求头: {request.headers}")
    logger.debug(f"请求文件: {request.files}")
    logger.debug(f"请求表单: {request.form}")
    logger.debug(f"请求JSON: {request.get_json(silent=True)}")
    
    file = request.files.get('image')
    content = request.form.get('content', '')
    
    # 修改获取 openid 的方式
    openid = request.form.get('openid')  # 先从 form 表单获取
    if not openid and request.get_json():  # 如果表单中没有，尝试从 JSON 获取
        openid = request.get_json().get('openid')
    logger.debug(f"获取到的openid: {openid}")
    
    if not file and not content:
        logger.error("未收到图片或文字内容")
        return jsonify({
            'code': 400,
            'message': '请上传图片或输入文字信息',
            'data': None
        })

    try:
        # 情况1: 只有文字
        if content and not file:
            logger.debug("只接收到文字内容")
            result = process_with_coze(content=content)
            
        # 情况2: 只有图片
        elif file and not content:
            logger.debug("只接收到图片")
            image_filename = secure_filename(file.filename)
            image_path = os.path.join('uploads', image_filename)
            os.makedirs('uploads', exist_ok=True)
            file.save(image_path)
            image_url = upload_image_to_imgur(image_path)
            result = process_with_coze(image_url=image_url)
            
        # 情况3: 都有
        else:
            logger.debug("同时接收到图片和文字")
            image_filename = secure_filename(file.filename)
            image_path = os.path.join('uploads', image_filename)
            os.makedirs('uploads', exist_ok=True)
            file.save(image_path)
            image_url = upload_image_to_imgur(image_path)
            result = process_with_coze(image_url=image_url, content=content)
        
        logger.debug(f"准备返回给前端的完整结果: {result}")
        logger.debug(f"result类型: {type(result)}")
        logger.debug(f"result['output']类型: {type(result['output'])}")
        logger.debug(f"result['output']内容: {result['output']}")
        
        # 检查结果中是否包含 conclusion 字段
        if 'output' in result and isinstance(result['output'], dict):
            logger.debug(f"output字段的keys: {result['output'].keys()}")
            logger.debug(f"conclusion存在于output中: {'conclusion' in result['output']}")
            if 'conclusion' in result['output']:
                logger.debug(f"conclusion内容: {result['output']['conclusion']}")

        # 构造返回数据
        response_data = {
            'code': 200,
            'message': 'success',
            'data': {
                'token': result.get('token'),
                'output': result.get('output')
            }
        }
        logger.debug(f"API响应数据完整结构: {json.dumps(response_data)}")

        # 在返回结果前保存记录
        if openid:
            save_health_record(
                openid=openid,
                content=content,
                result_data=result,
                query_type=2 if file else 1
            )
        
        return jsonify(response_data)

    except Exception as e:
        error_message = str(e)
        # 如果有 openid，保存错误记录
        if openid:
            save_health_record(
                openid=openid,
                content=content,
                result_data=None,
                query_type=2 if file else 1,
                error_message=error_message
            )
        
        logger.error(f"API处理过程中出错: {str(e)}")
        logger.exception("详细错误信息:")
        error_response = {
            'code': 500,
            'message': str(e),
            'data': None
        }
        logger.debug(f"返回错误响应: {error_response}")
        return jsonify(error_response)

# 修改 init_db 函数，添加新表
def init_db():
    try:
        # 从环境变量获取数据库URL
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise RuntimeError('DATABASE_URL not set')
            
        # 解析数据库URL
        url = urlparse(database_url)
        
        # 直接建立连接，不使用 g 对象
        conn = psycopg2.connect(
            dbname=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port
        )
        
        with conn.cursor() as cur:
            # 现有的 users 表创建
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    openid VARCHAR(100) UNIQUE NOT NULL,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_visit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 添加 health_records 表创建，包含 conclusion 字段
            cur.execute("""
                CREATE TABLE IF NOT EXISTS health_records (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    query_content TEXT,
                    query_type SMALLINT,
                    raw_result JSONB,
                    service_elements JSONB,
                    service_examination JSONB,
                    conclusion TEXT,
                    status SMALLINT,
                    error_message TEXT,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 添加 feedback 表创建
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    type VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    status SMALLINT DEFAULT 0,
                    reply TEXT,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reply_time TIMESTAMP
                )
            """)
            conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Init DB error: {str(e)}")

# 在 app 初始化后调用
init_db()

# 修改 login 函数中的数据库操作部分
@app.route('/api/login', methods=['POST'])
def login():
    code = request.json.get('code')
    if not code:
        return jsonify({'error': 'No code provided'}), 400
        
    try:
        # 调用微信接口换取 openid
        url = 'https://api.weixin.qq.com/sns/jscode2session'
        params = {
            'appid': os.environ.get('WX_APPID'),
            'secret': os.environ.get('WX_SECRET'),
            'js_code': code,
            'grant_type': 'authorization_code'
        }
        resp = requests.get(url, params=params)
        openid = resp.json().get('openid')
        
        # 检查或创建用户
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (openid) 
                VALUES (%s)
                ON CONFLICT (openid) 
                DO UPDATE SET last_visit_time = CURRENT_TIMESTAMP
                RETURNING id
                """, 
                (openid,)
            )
            db.commit()
            
        return jsonify({'openid': openid})
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Login failed'}), 500

def save_health_record(openid, content, result_data, query_type=1, error_message=None):
    try:
        logger.debug(f"开始保存健康记录，openid: {openid}")
        db = get_db()
        with db.cursor() as cur:
            # 获取用户ID
            cur.execute("SELECT id FROM users WHERE openid = %s", (openid,))
            user = cur.fetchone()
            logger.debug(f"查询到的用户ID: {user}")
            if not user:
                logger.error(f"未找到用户: {openid}")
                return
            
            user_id = user[0]
            status = 0 if error_message else 1
            
            # 解析结果数据
            service_elements = None
            service_examination = None
            conclusion = None
            if result_data and not error_message:
                output = result_data.get('output', {})
                service_elements = json.dumps(output.get('service_elements', []))
                service_examination = json.dumps(output.get('service_examination', []))
                conclusion = output.get('conclusion')
            
            # 在执行插入前打印参数
            logger.debug(f"准备插入记录: user_id={user[0]}, content={content}, type={query_type}")
            
            # 插入记录，添加 conclusion 字段
            cur.execute(
                """
                INSERT INTO health_records 
                (user_id, query_content, query_type, raw_result, 
                service_elements, service_examination, status, error_message, conclusion)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, content, query_type, 
                json.dumps(result_data) if result_data else None,
                service_elements, service_examination, 
                status, error_message, conclusion)
            )
            db.commit()
            
            # 更新用户的最后访问时间
            cur.execute(
                """
                UPDATE users 
                SET last_visit_time = CURRENT_TIMESTAMP 
                WHERE id = %s
                """,
                (user_id,)
            )
            db.commit()
            logger.debug("记录保存成功")
            
    except Exception as e:
        logger.error(f"Save health record error: {str(e)}")
        logger.exception("详细错误信息:")

# 添加反馈接口
@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    try:
        data = request.get_json() if request.is_json else request.form
        openid = data.get('openid')
        feedback_type = data.get('type')
        content = data.get('content')

        if not all([openid, feedback_type, content]):
            return jsonify({
                'code': 400,
                'message': '缺少必要参数',
                'data': None
            })

        db = get_db()
        with db.cursor() as cur:
            # 获取用户ID
            cur.execute("SELECT id FROM users WHERE openid = %s", (openid,))
            user = cur.fetchone()
            if not user:
                return jsonify({
                    'code': 404,
                    'message': '用户不存在',
                    'data': None
                })

            # 插入反馈记录
            cur.execute("""
                INSERT INTO feedback (user_id, type, content)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (user[0], feedback_type, content))
            
            feedback_id = cur.fetchone()[0]
            db.commit()

        return jsonify({
            'code': 200,
            'message': '提交成功',
            'data': {'id': feedback_id}
        })

    except Exception as e:
        logger.error(f"提交反馈失败: {str(e)}")
        return jsonify({
            'code': 500,
            'message': '服务器错误',
            'data': None
        })

# 获取反馈历史记录接口
@app.route('/api/feedback/history', methods=['GET'])
def get_feedback_history():
    try:
        openid = request.args.get('openid')
        if not openid:
            return jsonify({
                'code': 400,
                'message': '缺少openid参数',
                'data': None
            })

        db = get_db()
        with db.cursor(cursor_factory=DictCursor) as cur:
            # 获取用户的反馈历史
            cur.execute("""
                SELECT f.id, f.type, f.content, f.status, f.reply,
                       TO_CHAR(f.create_time, 'YYYY-MM-DD HH24:MI:SS') as create_time,
                       TO_CHAR(f.reply_time, 'YYYY-MM-DD HH24:MI:SS') as reply_time
                FROM feedback f
                JOIN users u ON f.user_id = u.id
                WHERE u.openid = %s
                ORDER BY f.create_time DESC
            """, (openid,))
            
            feedbacks = cur.fetchall()
            result = []
            for feedback in feedbacks:
                result.append(dict(feedback))

        return jsonify({
            'code': 200,
            'message': 'success',
            'data': result
        })

    except Exception as e:
        logger.error(f"获取反馈历史失败: {str(e)}")
        return jsonify({
            'code': 500,
            'message': '服务器错误',
            'data': None
        })

if __name__ == "__main__":
    app.run(host=host, port=port)
