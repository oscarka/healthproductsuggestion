import requests
import os
import json

# 获取当前用户的home目录
home = os.path.expanduser("~")
file_path = os.path.join(home, "downloads/uploadfile/test.jpg")

print(f"尝试访问文件: {file_path}")
print(f"文件是否存在: {os.path.exists(file_path)}")

url = 'http://localhost:5001/api/upload'
files = {
    'image': ('test.jpg', open(file_path, 'rb'))
}

response = requests.post(url, files=files)
print('Status Code:', response.status_code)
print('Raw Response:', response.text)
try:
    print('Response:', response.json())
except json.JSONDecodeError as e:
    print('JSON解析错误:', str(e)) 