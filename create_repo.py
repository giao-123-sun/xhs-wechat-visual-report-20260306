import json
import subprocess
import requests
inp='protocol=https\nhost=github.com\n\n'.encode()
out=subprocess.run(['git','credential','fill'],input=inp,capture_output=True,check=True).stdout.decode('utf-8',errors='ignore')
kv={}
for line in out.strip().splitlines():
    if '=' in line:
        k,v=line.split('=',1)
        kv[k.strip()]=v.strip()
user=kv.get('username')
token=kv.get('password')
if not user or not token:
    raise SystemExit('No GitHub credential found')
repo_name='xhs-wechat-visual-report-20260306'
headers={'Authorization':f'token {token}','Accept':'application/vnd.github+json'}
resp=requests.post('https://api.github.com/user/repos',headers=headers,json={'name':repo_name,'private':False,'description':'WeChat image extraction + Xiaohongshu crawling dataset and static visualization'})
if resp.status_code==422:
    print(json.dumps({'repo_name':repo_name,'html_url':f'https://github.com/{user}/{repo_name}','status':'exists'},ensure_ascii=False))
elif resp.status_code>=300:
    print(resp.status_code,resp.text)
    raise SystemExit('create repo failed')
else:
    data=resp.json()
    print(json.dumps({'repo_name':repo_name,'html_url':data.get('html_url'),'status':'created'},ensure_ascii=False))
