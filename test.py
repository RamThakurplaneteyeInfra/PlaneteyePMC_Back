import urllib.request
import json

url = 'http://127.0.0.1:8000/api/cost-performance/'
data = {
    "project_name": "Project Serene Meadows",
    "month_year": "Mar-2023",
    "bac": 112000000,
    "bcws": 3000000,
    "bcwp": 1380000,
    "acwp": 1400000,
    "fcst": 6700000
}

req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as response:
        print(response.getcode())
        print(json.loads(response.read().decode('utf-8')))
except urllib.error.HTTPError as e:
    print(e.code)
    print(e.read().decode('utf-8'))
