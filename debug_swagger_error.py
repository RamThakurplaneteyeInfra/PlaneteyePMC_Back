import requests


def main():
    url = "http://127.0.0.1:8000/swagger/?format=openapi"
    r = requests.get(url)
    print("status:", r.status_code)
    html = r.text

    token = '<pre class="exception_value">'
    start = html.find(token)
    if start == -1:
        print("Could not find exception_value token. Printing first 1500 chars:\n")
        print(html[:1500])
        return
    start += len(token)
    end = html.find("</pre>", start)
    print("exception_value:\n")
    print(html[start:end].strip())


if __name__ == "__main__":
    main()

