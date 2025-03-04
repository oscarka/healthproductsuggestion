import os
import requests
import json
import logging
from flask import Flask, render_template, request, jsonify, session
from werkzeug.utils import secure_filename
from time import sleep

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
    
    file = request.files.get('image')
    content = request.form.get('content', '')  # 获取content字段
    
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

        # 构造返回数据
        response_data = {
            'code': 200,
            'message': 'success',
            'data': {
                'token': result.get('token'),
                'output': result.get('output')
            }
        }
        logger.debug(f"准备返回数据: {response_data}")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"API处理过程中出错: {str(e)}")
        logger.exception("详细错误信息:")
        error_response = {
            'code': 500,
            'message': str(e),
            'data': None
        }
        logger.debug(f"返回错误响应: {error_response}")
        return jsonify(error_response)

if __name__ == "__main__":
    app.run(host=host, port=port)
