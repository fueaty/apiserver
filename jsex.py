import re
import requests
from bs4 import BeautifulSoup
import execjs
from urllib.parse import urlparse, urlunparse

def rewrite_resource_url(url):
    """重写资源URL，替换域名并添加查询参数"""
    parsed_url = urlparse(url)
    if 'fe-static.xhscdn.com' in parsed_url.netloc:
        new_netloc = parsed_url.netloc.replace('fe-static.xhscdn.com', 'cdn.xiaohongshu.com')
        new_path = parsed_url.path
        # 添加查询参数
        query = parsed_url.query
        if query:
            new_query = f"{query}&business=fe&scene=feplatform"
        else:
            new_query = "business=fe&scene=feplatform"
        return urlunparse(parsed_url._replace(netloc=new_netloc, query=new_query))
    return url

def simulate_browser_request(url):
    """模拟浏览器发送请求，处理反爬机制"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36',
        'Referer': 'https://www.xiaohongshu.com/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Connection': 'keep-alive',
    }
    
    session = requests.Session()
    response = session.get(url, headers=headers)
    
    # 解析HTML并处理资源URL
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 处理script标签
    for script in soup.find_all('script'):
        if script.get('src'):
            original_src = script['src']
            rewritten_src = rewrite_resource_url(original_src)
            script['src'] = rewritten_src
    
    # 处理link标签
    for link in soup.find_all('link', rel='stylesheet'):
        if link.get('href'):
            original_href = link['href']
            rewritten_href = rewrite_resource_url(original_href)
            link['href'] = rewritten_href
    
    # 提取并执行关键JavaScript代码（处理动态参数）
    js_code = ""
    for script in soup.find_all('script', {'formula-runtime': True}):
        js_code += script.string or ""
    
    # 执行JavaScript获取动态参数
    try:
        ctx = execjs.compile(js_code)
        # 模拟eaglet/insight推送函数，避免错误
        ctx.eval("window.eaglet = {push: function() {}}; window.insight = {push: function() {}};")
        # 执行资源加载逻辑
        ctx.eval("try { formula_assets_retry_init(); } catch(e) {}")
    except Exception as e:
        print(f"JavaScript执行错误: {e}")
    
    return {
        'original_url': url,
        'status_code': response.status_code,
        'parsed_html': str(soup),
        'rewritten_resources': [rewrite_resource_url(tag.get('src') or tag.get('href')) 
                               for tag in soup.find_all(['script', 'link']) 
                               if tag.get('src') or tag.get('href')]
    }

if __name__ == "__main__":
    # 测试目标URL（替换为实际需要爬取的小红书页面URL）
    target_url = "https://www.xiaohongshu.com/"
    result = simulate_browser_request(target_url)
    
    # 保存结果到文件
    with open("xiaohongshu_parsed_result.html", "w", encoding="utf-8") as f:
        f.write(result['parsed_html'])
    
    print(f"爬取成功，状态码: {result['status_code']}")
    print(f"重写的资源数量: {len(result['rewritten_resources'])}")
    print(f"解析结果已保存到: xiaohongshu_parsed_result.html")
